from __future__ import annotations

import argparse
import os
import sys
import json
import random
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

GRAPH_DEFAULT = "v24.0"


HASHTAG_POOL = [
    "#femalepsychology",
    "#datingtips",
    "#relationshipadvice",
    "#womendating",
    "#attraction",
    "#selfrespect",
    "#emotionalintelligence",
    "#loveadvice",
    "#modernromance",
    "#healthyrelationships",
    "#confidence",
    "#communication",
    "#datingadviceforwomen",
    "#highvaluedating",
    "#relationshipgoals",
    "#selflovejourney",
    "#feminineenergy",
    "#mindsetshift",
    "#personalgrowth",
    "#boundaries",
    "#healingjourney",
    "#secureattachment",
    "#relationshipcoach",
    "#usa",
    "#unitedstates",
    "#americanwomen",
    "#usdating",
    "#newyork",
    "#california",
    "#texas",
    "#florida",
    "#chicago",
    "#losangeles",
    "#miami",
    "#dallas",
    "#houston",
    "#atlanta",
    "#seattle",
    "#boston",
    "#washingtondc",
    "#sandiego",
    "#phoenix",
    "#lasvegas",
    "#philadelphia",
    "#charlotte",
    "#denver",
    "#austin",
]
STOP_TAG_WORDS = {
    "with",
    "from",
    "that",
    "this",
    "your",
    "have",
    "will",
    "stay",
    "into",
    "more",
    "when",
    "what",
    "who",
    "why",
    "how",
    "calm",
    "clear",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Render reel and publish to Facebook in one command.")
    p.add_argument("--page", required=True, help="Page key from configs/pages/<page>.yaml")
    p.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    p.add_argument("--meta-config", default="secrets/meta_config.json")
    p.add_argument("--caption-file", default="", help="Optional text file. If set, use this caption exactly.")
    p.add_argument("--dry-run", action="store_true", help="Render + caption only, skip Facebook publish.")
    p.add_argument("--timeout-seconds", type=int, default=900)
    return p


def _run_render(project_root: Path, page: str) -> tuple[Path, dict[str, Any]]:
    cmd = [
        sys.executable,
        "-m",
        "autovideo.app.cli",
        "--project-root",
        str(project_root),
        "render",
        "--page",
        page,
    ]
    env = os.environ.copy()
    src_path = str((project_root / "src").resolve())
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_path if not prev else (src_path + os.pathsep + prev)
    proc = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise SystemExit(f"Render failed.\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

    manifest_path: Path | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("MANIFEST="):
            manifest_path = Path(line.split("=", 1)[1].strip())
            break
    if manifest_path is None or not manifest_path.exists():
        raise SystemExit(f"Could not resolve MANIFEST path from render output.\n{proc.stdout}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest_path, manifest


def _slug_words(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9 ]+", " ", text).lower().strip()
    return [w for w in cleaned.split() if len(w) > 2]


def build_caption(manifest: dict[str, Any], hashtag_count: int = 7) -> str:
    spec = manifest.get("spec", {})
    h1 = str(spec.get("heading_line1", "")).strip().title()
    h2 = str(spec.get("heading_line2", "")).strip().title()
    # Safety normalization in case any legacy content still has misspelling.
    h1 = h1.replace("Psycology", "Psychology")
    h2 = h2.replace("Psycology", "Psychology")
    points = spec.get("points", [])

    lead = ""
    if points:
        lead = str(points[0].get("text", "")).strip()
    if not lead:
        lead = "Strong women choose calm consistency, not chaos."

    lead = re.sub(r"\s+", " ", lead)
    if len(lead) > 120:
        lead = lead[:117].rstrip() + "..."

    opener = f"{h1}: {h2}." if h1 and h2 else "Female Psychology insights."
    sentence = f"{opener} {lead}"

    pool = list(dict.fromkeys(HASHTAG_POOL))
    random.shuffle(pool)
    selected = []
    for tag in pool:
        if tag.lower() not in {t.lower() for t in selected}:
            selected.append(tag)
        if len(selected) >= hashtag_count:
            break

    return f"{sentence}\n\n{' '.join(selected)}"


def graph_url(version: str, path: str, video: bool = False) -> str:
    host = "graph-video.facebook.com" if video else "graph.facebook.com"
    return f"https://{host}/{version}/{path}"


def request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.request(method, url, timeout=180, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text}
    if response.status_code >= 400:
        err = payload.get("error", {})
        msg = err.get("message", response.text)
        code = err.get("code")
        sub = err.get("error_subcode")
        detail = f" code={code}" if code else ""
        detail += f" subcode={sub}" if sub else ""
        raise SystemExit(f"Meta API failed: {msg}{detail}")
    return payload


def graph_post(version: str, path: str, **data: Any) -> dict[str, Any]:
    return request_json("POST", graph_url(version, path), data=data)


def graph_get(version: str, path: str, access_token: str, **params: str) -> dict[str, Any]:
    return request_json("GET", graph_url(version, path), params={"access_token": access_token, **params})


def upload_binary(upload_url: str, access_token: str, video_path: Path) -> None:
    headers = {
        "Authorization": f"OAuth {access_token}",
        "offset": "0",
        "file_size": str(video_path.stat().st_size),
    }
    with video_path.open("rb") as fh:
        res = requests.post(upload_url, headers=headers, data=fh, timeout=600)
    if res.status_code >= 400:
        try:
            p = res.json()
        except ValueError:
            p = {"raw": res.text}
        msg = p.get("error", {}).get("message", res.text)
        raise SystemExit(f"Binary upload failed: {msg}")


def wait_for_facebook_video(version: str, video_id: str, access_token: str, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_status: dict[str, Any] = {}
    while time.time() < deadline:
        last_status = graph_get(version, video_id, access_token, fields="status")
        status = last_status.get("status") or {}
        proc = (status.get("processing_phase") or {}).get("status")
        pub = (status.get("publishing_phase") or {}).get("status")
        print(f"FACEBOOK_STATUS=processing:{proc} publishing:{pub}", flush=True)
        if proc in {"complete", "succeeded"} or pub in {"complete", "published"}:
            return
        if proc == "error" or pub == "error":
            raise SystemExit(f"Facebook processing failed: {last_status}")
        time.sleep(10)
    raise SystemExit(f"Timed out waiting for Facebook publish: {last_status}")


def publish_facebook_reel(meta_cfg: dict[str, Any], video_path: Path, caption: str, timeout_seconds: int) -> str:
    version = str(meta_cfg.get("graph_version", GRAPH_DEFAULT))
    access_token = str(meta_cfg.get("page_access_token", "")).strip()
    page_id = str(meta_cfg.get("page_id", "")).strip()
    if not access_token or not page_id:
        raise SystemExit("meta_config is missing page_access_token or page_id.")
    # Stable publishing path for pages: direct video upload as published post.
    upload_endpoint = graph_url(version, f"{page_id}/videos", video=True)
    with video_path.open("rb") as fh:
        created = request_json(
            "POST",
            upload_endpoint,
            data={
                "access_token": access_token,
                "description": caption,
                "published": "true",
            },
            files={"source": fh},
        )
    video_id = str(created.get("id", ""))
    if not video_id:
        raise SystemExit(f"Video upload did not return id: {created}")
    print(f"FACEBOOK_VIDEO_ID={video_id}")
    wait_for_facebook_video(version, video_id, access_token, timeout_seconds)
    print(f"FACEBOOK_VIDEO_RESULT={json.dumps(created, ensure_ascii=True)}")
    return video_id


def main() -> None:
    args = build_parser().parse_args()
    project_root = Path(args.project_root).resolve()
    meta_config_path = (project_root / args.meta_config).resolve()

    manifest_path, manifest = _run_render(project_root, args.page)
    output_mp4 = Path(manifest["output_mp4"]).resolve()

    if args.caption_file:
        caption = Path(args.caption_file).read_text(encoding="utf-8").strip()
    else:
        caption = build_caption(manifest, hashtag_count=7)

    caption_out = manifest_path.with_suffix(".caption.txt")
    caption_out.write_text(caption + "\n", encoding="utf-8")

    print(f"PAGE={args.page}")
    print(f"MANIFEST={manifest_path}")
    print(f"VIDEO={output_mp4}")
    print("CAPTION=")
    print(caption)
    print(f"CAPTION_FILE={caption_out}")

    if args.dry_run:
        print("PUBLISH=SKIPPED_DRY_RUN")
        return

    meta_cfg = json.loads(meta_config_path.read_text(encoding="utf-8"))
    reel_id = publish_facebook_reel(meta_cfg, output_mp4, caption, args.timeout_seconds)
    print(f"PUBLISHED_REEL_ID={reel_id}")


if __name__ == "__main__":
    main()
