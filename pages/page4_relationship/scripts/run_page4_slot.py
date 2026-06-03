from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PAGE_KEY = "page4_relationship"
RUNTIME = PROJECT_ROOT / "control" / "automation_runtime.json"
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autovideo.services.telegram_notify import load_dotenv, reel_status_message, send_telegram  # noqa: E402


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout or ""


def _parse_key(stdout: str, key: str) -> str:
    prefix = f"{key}="
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"Missing {key}=... in output")


def _load_page_cfg() -> dict:
    payload = json.loads(RUNTIME.read_text(encoding="utf-8-sig"))
    for page in payload.get("pages", []):
        if str(page.get("page_key", "")).strip() == PAGE_KEY:
            return page
    raise RuntimeError(f"Page config not found in runtime: {PAGE_KEY}")


def _target_dt(slot_hhmm: str, explicit_date: str | None) -> datetime:
    hh, mm = [int(x) for x in slot_hhmm.split(":")]
    if explicit_date:
        base = datetime.fromisoformat(explicit_date)
        return base.replace(hour=hh, minute=mm, second=0, microsecond=0)
    now = datetime.now()
    return (now + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and schedule one Page 4 reel.")
    parser.add_argument("--slot", required=True, help="Target slot in HH:MM")
    parser.add_argument("--target-date", default="", help="Optional target date YYYY-MM-DD")
    parser.add_argument("--run-root", default="", help="Optional parent run directory for result files")
    parser.add_argument("--label", default="", help="Optional label for logging")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    page_cfg = _load_page_cfg()
    asset_id = str(page_cfg.get("facebook_asset_id", "")).strip()
    if not asset_id:
        raise RuntimeError("Missing facebook_asset_id for page4_relationship")

    slot = str(args.slot).strip()
    dt = _target_dt(slot, args.target_date.strip() or None)

    run_root = Path(args.run_root).resolve() if args.run_root else (
        PROJECT_ROOT / "runs" / "airflow_page4" / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    run_root.mkdir(parents=True, exist_ok=True)

    record = {
        "page": PAGE_KEY,
        "slot": slot,
        "target": dt.isoformat(timespec="minutes"),
        "label": args.label.strip(),
        "status": "failed",
        "manifest": "",
        "video": "",
        "upload_result": "",
        "error": "",
        "saved_at": "",
    }

    try:
        generate_stdout = _run([sys.executable, str(PROJECT_ROOT / "scripts" / "generate_page4_reel.py")])
        manifest_path = Path(_parse_key(generate_stdout, "MANIFEST"))
        video_path = Path(_parse_key(generate_stdout, "VIDEO"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        caption = str(manifest.get("caption", "")).strip()

        upload_stdout = _run(
            [
                sys.executable,
                str(
                    PROJECT_ROOT
                    / "pages"
                    / "automation_tools"
                    / "meta_ui_schedule"
                    / "upload_schedule_ui.py"
                ),
                "--page-key",
                PAGE_KEY,
                "--asset-id",
                asset_id,
                "--video",
                str(video_path),
                "--caption",
                caption,
                "--when",
                dt.strftime("%Y-%m-%dT%H:%M"),
            ]
        )

        record.update(
            {
                "status": "scheduled",
                "manifest": str(manifest_path),
                "video": str(video_path),
                "upload_result": upload_stdout.strip(),
                "error": "",
            }
        )
        send_telegram(
            reel_status_message(
                page_key=PAGE_KEY,
                slot=slot,
                scheduled_for=dt.isoformat(timespec="minutes"),
                status="scheduled",
                video=str(video_path),
            )
        )
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        send_telegram(
            reel_status_message(
                page_key=PAGE_KEY,
                slot=slot,
                scheduled_for=dt.isoformat(timespec="minutes"),
                status="failed_render_or_upload",
                error=record["error"],
            )
        )
        raise
    finally:
        record["saved_at"] = datetime.now().isoformat(timespec="seconds")
        out_file = run_root / f"slot_{slot.replace(':', '')}.json"
        out_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"RESULT_FILE={out_file}")
        print(f"SLOT={slot}")
        print(f"TARGET={dt.isoformat(timespec='minutes')}")
        print(f"STATUS={record['status']}")


if __name__ == "__main__":
    main()
