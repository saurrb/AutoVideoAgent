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


def reel_status_message(
    *,
    page_key: str,
    slot: str,
    scheduled_for: str,
    status: str,
    video: str = "",
    error: str = "",
    page_label: str = "",
    run_folder: str = "",
    failed_stage: str = "",
) -> str:
    status_text = str(status or "").strip().lower()
    label = (page_label or page_key.replace("_", " ").title()).strip()
    title = "[SCHEDULED] Reel Scheduled" if status_text in {"scheduled", "complete"} else "[FAILED] Reel Failed"
    lines = [
        title,
        "",
        f"Page: {label}",
        f"Slot: {slot}",
        f"Publish Time: {scheduled_for}",
        f"Status: {status_text.upper() or 'UNKNOWN'}",
    ]
    if status_text not in {"scheduled", "complete"} and failed_stage:
        lines.append(f"Failed Stage: {failed_stage}")
    if video:
        lines.extend(["", f"Video: {video}"])
    if run_folder:
        lines.append(f"Run Folder: {run_folder}")
    if error:
        lines.extend(["", f"Reason: {error[:500]}"])
    return "\n".join(lines)
