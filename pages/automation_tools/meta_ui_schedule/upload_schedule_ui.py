from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[3]
SCHEDULER_CANDIDATES = [
    ROOT / "scripts" / "legacy" / "daily_ui_batch_schedule.py",
    ROOT / "scripts" / "daily_ui_batch_schedule.py",
]


def _load_scheduler():
    scheduler = next((path for path in SCHEDULER_CANDIDATES if path.exists()), SCHEDULER_CANDIDATES[0])
    if not scheduler.exists():
        checked = ", ".join(str(path) for path in SCHEDULER_CANDIDATES)
        raise FileNotFoundError(f"Unable to find Meta UI scheduler module. Checked: {checked}")
    spec = importlib.util.spec_from_file_location("daily_ui_batch_schedule", scheduler)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load scheduler module: {scheduler}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["daily_ui_batch_schedule"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    ap = argparse.ArgumentParser(description="Upload and schedule one reel via Meta Business UI (CDP BrowserOS).")
    ap.add_argument("--page-key", required=True)
    ap.add_argument("--asset-id", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--caption-file", default="")
    ap.add_argument("--caption", default="")
    ap.add_argument("--when", required=True, help="Local datetime in YYYY-MM-DDTHH:MM")
    args = ap.parse_args()

    mod = _load_scheduler()
    when_dt = datetime.fromisoformat(args.when)
    video = str(Path(args.video).resolve())

    caption = (args.caption or "").strip()
    if args.caption_file:
        caption = Path(args.caption_file).read_text(encoding="utf-8-sig").strip()

    plan = mod.PagePlan(
        page_key=args.page_key,
        asset_id=args.asset_id,
        generator_type="manual_ui",
        slots=[when_dt.strftime("%H:%M")],
    )

    shot_dir = ROOT / "runs" / "manual_ui_schedule" / datetime.now().strftime("%Y%m%d_%H%M%S") / "screens"
    shot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9100", timeout=120000)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        status = mod._upload_and_schedule_with_retry(ctx, plan, video, caption, when_dt, shot_dir)

    safe = {
        "ok": bool(status.get("ok")),
        "attempt": status.get("attempt"),
        "retried": status.get("retried"),
        "target_time": when_dt.isoformat(timespec="minutes"),
        "shot_dir": str(shot_dir),
    }
    print("RESULT=" + json.dumps(safe, ensure_ascii=False))
    if not safe["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
