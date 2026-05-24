from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests


def _graph_url(version: str, path: str, video: bool = False) -> str:
    host = "graph-video.facebook.com" if video else "graph.facebook.com"
    return f"https://{host}/{version}/{path}"


def _request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.request(method, url, timeout=180, **kwargs)
    payload = response.json()
    if response.status_code >= 400:
        message = payload.get("error", {}).get("message", response.text)
        raise RuntimeError(f"Meta API failed: {message}")
    return payload


def _graph_post(version: str, path: str, **data: Any) -> dict[str, Any]:
    return _request_json("POST", _graph_url(version, path), data=data)


def _graph_get(version: str, path: str, access_token: str, **params: str) -> dict[str, Any]:
    return _request_json(
        "GET",
        _graph_url(version, path),
        params={"access_token": access_token, **params},
    )


def _upload_binary(upload_url: str, access_token: str, video_path: Path) -> None:
    size = video_path.stat().st_size
    headers = {
        "Authorization": f"OAuth {access_token}",
        "offset": "0",
        "file_size": str(size),
    }
    with video_path.open("rb") as fh:
        response = requests.post(upload_url, headers=headers, data=fh, timeout=600)
    payload = response.json()
    if response.status_code >= 400:
        message = payload.get("error", {}).get("message", response.text)
        raise RuntimeError(f"Meta binary upload failed: {message}")


def _wait_for_facebook_video(version: str, video_id: str, access_token: str, timeout_seconds: int = 900) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status = _graph_get(version, video_id, access_token, fields="status").get("status", {})
        processing = (status.get("processing_phase") or {}).get("status")
        publishing = (status.get("publishing_phase") or {}).get("status")
        if processing in {"complete", "succeeded"} or publishing in {"complete", "published"}:
            return
        if processing == "error" or publishing == "error":
            raise RuntimeError(f"Facebook processing failed: {status}")
        time.sleep(10)
    raise RuntimeError("Timed out waiting for Facebook video processing.")


def publish_facebook_reel(config_path: Path, local_video_path: Path, caption: str) -> str:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    version = config.get("graph_version", "v24.0")
    access_token = config["page_access_token"]
    page_id = config["page_id"]

    started = _graph_post(version, f"{page_id}/video_reels", access_token=access_token, upload_phase="start")
    video_id = started["video_id"]
    _upload_binary(started["upload_url"], access_token, local_video_path)
    _graph_post(
        version,
        f"{page_id}/video_reels",
        access_token=access_token,
        upload_phase="finish",
        video_id=video_id,
        description=caption,
    )
    _wait_for_facebook_video(version, video_id, access_token)
    return str(video_id)
