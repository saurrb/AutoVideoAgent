from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autovideo.services.telegram_notify import load_dotenv, reel_status_message, send_telegram  # noqa: E402

_daily_path = PROJECT_ROOT / "scripts" / "daily_ui_batch_schedule.py"
_spec = importlib.util.spec_from_file_location("daily_ui_batch_schedule", _daily_path)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Unable to load scheduler module: {_daily_path}")
_daily = importlib.util.module_from_spec(_spec)
sys.modules["daily_ui_batch_schedule"] = _daily
_spec.loader.exec_module(_daily)
PagePlan = _daily.PagePlan
_load_plans = _daily._load_plans
_generate_reel = _daily._generate_reel
_upload_and_post_now = _daily._upload_and_post_now


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate and post one reel immediately.")
    ap.add_argument("--page", required=True)
    args = ap.parse_args()

    plans = [p for p in _load_plans() if p.page_key == args.page]
    if not plans:
        raise RuntimeError(f"No enabled plan found for page: {args.page}")
    plan = plans[0]

    run_dir = PROJECT_ROOT / "runs" / "manual_post_now" / datetime.now().strftime("%Y%m%d_%H%M%S")
    shots = run_dir / "screens"
    shots.mkdir(parents=True, exist_ok=True)

    manifest, video, caption = _generate_reel(plan)
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9100", timeout=300000)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        status = _upload_and_post_now(
            ctx.new_page(),
            PagePlan(plan.page_key, plan.asset_id, plan.generator_type, []),
            video,
            caption,
            shots,
        )

    out = {
        "page": plan.page_key,
        "manifest": str(manifest),
        "video": video,
        "status": status,
    }
    (run_dir / "result.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    load_dotenv(PROJECT_ROOT / ".env")
    tele_ok = send_telegram(
        reel_status_message(
            page_key=plan.page_key,
            slot="manual_post_now",
            scheduled_for=datetime.now().isoformat(timespec="minutes"),
            status="posted_now" if status.get("ok") else "failed_post_now",
            video=video,
            error="" if status.get("ok") else json.dumps(status),
        )
    )

    print(f"RUN_DIR={run_dir}")
    print(f"RESULT={run_dir / 'result.json'}")
    print(f"POST_OK={bool(status.get('ok'))}")
    print(f"TELEGRAM_SENT={tele_ok}")


if __name__ == "__main__":
    main()

