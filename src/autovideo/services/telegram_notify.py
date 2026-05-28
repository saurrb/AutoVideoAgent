from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and (k not in os.environ):
            os.environ[k] = v


def send_telegram(message: str) -> bool:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return False
    data = urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    req = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST")
    try:
        with urlopen(req, timeout=15) as resp:  # nosec
            return int(getattr(resp, "status", 200)) < 300
    except Exception:
        return False


def reel_status_message(*, page_key: str, slot: str, scheduled_for: str, status: str, video: str = "", error: str = "") -> str:
    lines = [
        "AutoVideoAgent Reel Update",
        f"page: {page_key}",
        f"slot: {slot}",
        f"scheduled_for: {scheduled_for}",
        f"status: {status}",
    ]
    if video:
        lines.append(f"video: {video}")
    if error:
        lines.append(f"error: {error[:300]}")
    return "\n".join(lines)

