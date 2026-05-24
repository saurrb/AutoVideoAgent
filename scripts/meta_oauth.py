from __future__ import annotations

import argparse
import json
import time
import urllib.parse
from pathlib import Path
from wsgiref.simple_server import make_server

import requests

GRAPH_VERSION = "v24.0"
DEFAULT_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "pages_manage_metadata",
    "business_management",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Meta OAuth and save a long-lived user token.")
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--app-secret", required=True)
    parser.add_argument("--token-out", required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--scopes", default=",".join(DEFAULT_SCOPES))
    return parser


def graph_get(path: str, params: dict[str, str]) -> dict:
    response = requests.get(f"https://graph.facebook.com/{GRAPH_VERSION}/{path}", params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def main() -> None:
    args = build_parser().parse_args()
    redirect_uri = f"http://localhost:{args.port}/"
    scopes = [scope.strip() for scope in args.scopes.split(",") if scope.strip()]
    token_out = Path(args.token_out)
    token_out.parent.mkdir(parents=True, exist_ok=True)
    query = urllib.parse.urlencode(
        {"client_id": args.app_id, "redirect_uri": redirect_uri, "scope": ",".join(scopes), "response_type": "code"}
    )
    print(f"AUTH_URL=https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?{query}", flush=True)

    captured = {"code": None, "error": None}

    def app(environ, start_response):
        params = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        captured["code"] = (params.get("code") or [None])[0]
        captured["error"] = (params.get("error_description") or params.get("error") or [None])[0]
        body = b"Authorization received. You can close this tab."
        start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
        return [body]

    with make_server("localhost", args.port, app) as httpd:
        while captured["code"] is None and captured["error"] is None:
            httpd.handle_request()

    if captured["error"]:
        raise SystemExit(f"OAuth failed: {captured['error']}")

    short_lived = graph_get(
        "oauth/access_token",
        {"client_id": args.app_id, "redirect_uri": redirect_uri, "client_secret": args.app_secret, "code": captured["code"]},
    )
    long_lived = graph_get(
        "oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": args.app_id,
            "client_secret": args.app_secret,
            "fb_exchange_token": short_lived["access_token"],
        },
    )
    payload = {
        "access_token": long_lived["access_token"],
        "token_type": long_lived.get("token_type", "bearer"),
        "expires_in": long_lived.get("expires_in"),
        "created_at": int(time.time()),
        "scopes": scopes,
    }
    token_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"TOKEN_SAVED={token_out}", flush=True)


if __name__ == "__main__":
    main()
