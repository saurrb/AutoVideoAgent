from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests

GRAPH_VERSION = "v24.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True, help="Path to token JSON from meta_oauth.py.")
    parser.add_argument("--save-config", required=True, help="Path to output config json.")
    parser.add_argument("--page-id", default="")
    return parser


def graph_get(path: str, access_token: str, **params: str) -> dict:
    response = requests.get(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{path}",
        params={"access_token": access_token, **params},
        timeout=60,
    )
    payload = response.json()
    if response.status_code >= 400:
        raise RuntimeError(payload.get("error", {}).get("message", response.text))
    return payload


def graph_post(path: str, access_token: str, **params: str) -> dict:
    response = requests.post(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{path}",
        data={"access_token": access_token, **params},
        timeout=60,
    )
    payload = response.json()
    if response.status_code >= 400:
        raise RuntimeError(payload.get("error", {}).get("message", response.text))
    return payload


def main() -> None:
    args = build_parser().parse_args()
    token = json.loads(Path(args.token).read_text(encoding="utf-8"))["access_token"]
    me = graph_get("me", token, fields="id,name")
    perms = graph_get("me/permissions", token).get("data", [])
    granted = sorted([p.get("permission", "") for p in perms if p.get("status") == "granted"])
    pages = graph_get("me/accounts", token, fields="id,name,access_token,tasks", limit="100").get("data", [])
    if not pages:
        raise SystemExit("No pages found.")
    selected = next((p for p in pages if p.get("id") == args.page_id), pages[0])
    page_token = selected.get("access_token", "")
    can_create_reels_endpoint = False
    reels_probe_error = ""
    if page_token:
        try:
            # Non-destructive probe: ask Graph for edge metadata only.
            _ = graph_get(f"{selected.get('id')}/video_reels", page_token, metadata="1", limit="1")
            can_create_reels_endpoint = True
        except Exception as exc:
            reels_probe_error = str(exc)
    config = {
        "graph_version": GRAPH_VERSION,
        "user_id": me.get("id"),
        "user_name": me.get("name"),
        "granted_user_permissions": granted,
        "page_id": selected.get("id"),
        "page_name": selected.get("name"),
        "page_tasks": selected.get("tasks", []),
        "page_access_token": selected.get("access_token"),
        "can_access_video_reels_edge": can_create_reels_endpoint,
        "video_reels_probe_error": reels_probe_error,
    }
    out = Path(args.save_config)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"CONFIG_SAVED={out}")
    print(f"USER={me.get('name')} ({me.get('id')})")
    print(f"PAGE={selected.get('name')} ({selected.get('id')})")
    print(f"PAGE_TASKS={','.join(selected.get('tasks', []))}")
    print(f"HAS_pages_manage_posts={'pages_manage_posts' in granted}")
    print(f"VIDEO_REELS_EDGE_OK={can_create_reels_endpoint}")
    if reels_probe_error:
        print(f"VIDEO_REELS_EDGE_ERROR={reels_probe_error}")


if __name__ == "__main__":
    main()
