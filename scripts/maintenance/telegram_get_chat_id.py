from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import urlopen


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


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN in environment or .env")
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    with urlopen(url, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise SystemExit("Telegram API returned non-ok response.")
    found: list[int] = []
    for item in data.get("result", []):
        for key in ("message", "edited_message", "channel_post"):
            obj = item.get(key) or {}
            chat = obj.get("chat") or {}
            cid = chat.get("id")
            if isinstance(cid, int):
                found.append(cid)
    uniq = sorted(set(found))
    if not uniq:
        print("No chat_id found yet. Send /start to your bot, then run again.")
        return
    print("Found chat_id values:")
    for cid in uniq:
        print(cid)


if __name__ == "__main__":
    main()

