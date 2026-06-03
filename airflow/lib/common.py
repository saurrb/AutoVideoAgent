from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AIRFLOW_ROOT = PROJECT_ROOT / "airflow"
RUNTIME_PATH = PROJECT_ROOT / "control" / "automation_runtime.json"
AIRFLOW_SCHEDULE_PATH = PROJECT_ROOT / "control" / "airflow_schedule_control.json"
SRC_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autovideo.services.telegram_notify import load_dotenv, reel_status_message, send_telegram  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

_SLOT_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
PAGE_LABELS = {
    "female_psychology": "Female Psychology",
    "daily_desire_facts": "Daily Desire Facts",
    "dragon_cinema": "Dragon Cinema",
    "page4_relationship": "Relationship Page",
}


def load_runtime() -> dict[str, Any]:
    return json.loads(RUNTIME_PATH.read_text(encoding="utf-8-sig"))


def load_airflow_schedule_control() -> dict[str, Any]:
    if AIRFLOW_SCHEDULE_PATH.exists():
        return json.loads(AIRFLOW_SCHEDULE_PATH.read_text(encoding="utf-8-sig"))
    return {"timezone": "Asia/Calcutta", "pages": {}}


def get_page_runtime(page_key: str) -> dict[str, Any]:
    payload = load_runtime()
    for page in payload.get("pages", []):
        if str(page.get("page_key", "")).strip() == page_key:
            return page
    raise RuntimeError(f"Page config not found in runtime: {page_key}")


def _time_to_daily_cron(run_time: str) -> str:
    text = str(run_time or "").strip()
    if not _SLOT_RE.match(text):
        raise RuntimeError(f"Invalid Airflow daily_run_time HH:MM: {text}")
    hour, minute = text.split(":", 1)
    return f"{int(minute)} {int(hour)} * * *"


def get_page_airflow_schedule(page_key: str) -> str | None:
    """Read per-page Airflow schedule from control/airflow_schedule_control.json."""
    payload = load_airflow_schedule_control()
    page = (payload.get("pages") or {}).get(page_key) or {}
    if page and not bool(page.get("enabled", True)):
        return None
    if page.get("daily_run_time"):
        return _time_to_daily_cron(str(page["daily_run_time"]))

    page_runtime = get_page_runtime(page_key)
    if not bool(page_runtime.get("enabled", True)):
        return None
    return _time_to_daily_cron(str(page_runtime.get("morning_run_time", "")))


def get_page_airflow_defaults(page_key: str) -> dict[str, Any]:
    """Defaults for auto and manual Airflow runs, sourced from control JSON."""
    payload = load_airflow_schedule_control()
    page = (payload.get("pages") or {}).get(page_key) or {}
    runtime = get_page_runtime(page_key)
    slots = page.get("posting_slots")
    if not isinstance(slots, list) or not slots:
        slots = runtime.get("posting_slots", [])
    target_day_offset = page.get("target_day_offset", runtime.get("schedule_horizon_days", 1))
    try:
        target_day_offset = int(target_day_offset)
    except Exception:
        raise RuntimeError(f"Invalid target_day_offset for {page_key}: {target_day_offset}")
    return {
        "timezone": str(payload.get("timezone") or runtime.get("timezone") or "Asia/Calcutta"),
        "target_day_offset": target_day_offset,
        "posting_slots": [validate_slot(str(x)) for x in slots if str(x).strip()],
    }


def validate_slot(slot: str) -> str:
    slot = str(slot or "").strip()
    if not _SLOT_RE.match(slot):
        raise RuntimeError(f"Invalid slot HH:MM: {slot}")
    return slot


def _coerce_trigger_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
                return _coerce_trigger_list(parsed)
            except json.JSONDecodeError:
                pass
        if "," in stripped:
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return [stripped]
    if isinstance(value, (list, tuple)):
        result: list[Any] = []
        for item in value:
            result.extend(_coerce_trigger_list(item))
        return result
    return [value]


def parse_target_requests(
    page_key: str,
    conf: dict[str, Any] | None,
    default_slots: list[str],
    default_target_day_offset: int = 1,
    timezone_name: str = "Asia/Calcutta",
) -> list[dict[str, str]]:
    conf = conf or {}
    target_dates = _coerce_trigger_list(conf.get("target_dates"))
    slots = _coerce_trigger_list(conf.get("slots"))
    if not target_dates:
        tz = ZoneInfo(timezone_name)
        target_dates = [(datetime.now(tz) + timedelta(days=int(default_target_day_offset))).strftime("%Y-%m-%d")]
    if not slots:
        slots = list(default_slots)

    requests: list[dict[str, str]] = []
    for date_text in target_dates:
        normalized_date = datetime.fromisoformat(str(date_text).strip()).strftime("%Y-%m-%d")
        for slot in slots:
            hhmm = validate_slot(str(slot))
            requests.append(
                {
                    "page_key": page_key,
                    "target_date": normalized_date,
                    "slot": hhmm,
                    "target_iso": f"{normalized_date}T{hhmm}",
                    "slot_key": f"{normalized_date}_{hhmm.replace(':', '')}",
                }
            )
    requests.sort(key=lambda x: (x["target_date"], x["slot"]))
    return requests


def safe_run_id(run_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(run_id or "manual"))


def build_run_root(page_key: str, run_id: str) -> Path:
    path = PROJECT_ROOT / "runs" / "airflow_ui" / page_key / safe_run_id(run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_slot_dir(run_root: Path, request: dict[str, Any]) -> Path:
    path = run_root / str(request["target_date"]) / str(request["slot"]).replace(":", "")
    path.mkdir(parents=True, exist_ok=True)
    return path


def page_label(page_key: str) -> str:
    return PAGE_LABELS.get(page_key, str(page_key).replace("_", " ").title())


def _pretty_date(value: str) -> str:
    text = str(value or "").strip()
    try:
        return datetime.fromisoformat(text.split("T", 1)[0]).strftime("%d %b %Y")
    except Exception:
        return text


def _pretty_time(value: str) -> str:
    text = str(value or "").strip()
    if "T" in text:
        text = text.split("T", 1)[1]
    try:
        return datetime.strptime(text[:5], "%H:%M").strftime("%I:%M %p").lstrip("0")
    except Exception:
        return text


def _windows_text_path(value: str | Path) -> str:
    return _wsl_to_windows_path(value).replace("/", "\\")


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run_checked(cmd: list[str], cwd: Path | None = None, timeout: int | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(str(x) for x in cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout or ""


def _wsl_to_windows_path(value: str | Path) -> str:
    text = str(value).replace("\\", "/")
    if text.startswith("/mnt/") and len(text) > 6 and text[6] == "/":
        return f"{text[5].upper()}:/{text[7:]}"
    return str(value)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_meta_upload(*, page_key: str, asset_id: str, video: Path, caption: str, when_iso: str) -> dict[str, Any]:
    script = PROJECT_ROOT / "pages" / "automation_tools" / "meta_ui_schedule" / "upload_schedule_ui.py"
    python_exe = "python.exe" if os.name != "nt" else sys.executable
    script_arg = _wsl_to_windows_path(script) if os.name != "nt" else str(script)
    video_arg = _wsl_to_windows_path(video) if os.name != "nt" else str(video)
    stdout = run_checked(
        [
            python_exe,
            script_arg,
            "--page-key",
            page_key,
            "--asset-id",
            asset_id,
            "--video",
            video_arg,
            "--caption",
            caption,
            "--when",
            when_iso,
        ]
    )
    result = {}
    for line in stdout.splitlines():
        if line.startswith("RESULT="):
            result = json.loads(line.split("=", 1)[1])
            break
    return {"stdout": stdout.strip(), "result": result}


def send_status(
    page_key: str,
    slot: str,
    scheduled_for: str,
    status: str,
    *,
    video: str = "",
    error: str = "",
    run_folder: str = "",
    failed_stage: str = "",
) -> None:
    send_telegram(
        reel_status_message(
            page_key=page_key,
            page_label=page_label(page_key),
            slot=slot,
            scheduled_for=scheduled_for,
            status=status,
            video=video,
            error=error,
            run_folder=_windows_text_path(run_folder) if run_folder else "",
            failed_stage=failed_stage,
        )
    )


def send_batch_start(page_key: str, requests: list[dict[str, Any]], run_root: str = "") -> None:
    if not requests:
        return
    target_dates = sorted({str(item.get("target_date", "")) for item in requests if item.get("target_date")})
    slots = [str(item.get("slot", "")) for item in requests if item.get("slot")]
    message = "\n".join(
        [
            "[STARTED] Daily Batch Started",
            "",
            f"Page: {page_label(page_key)}",
            f"Run Date: {datetime.now(ZoneInfo('Asia/Calcutta')).strftime('%d %b %Y, %I:%M %p').replace(' 0', ' ')}",
            f"Posting Date: {', '.join(_pretty_date(x) for x in target_dates)}",
            f"Slots: {', '.join(slots)}",
            f"Total Reels: {len(requests)}",
            "",
            f"Run Folder: {_windows_text_path(run_root)}" if run_root else "",
        ]
    ).strip()
    send_telegram(message)


def send_batch_summary(page_key: str, requests: list[dict[str, Any]], run_root: str = "") -> dict[str, Any]:
    total = len(requests)
    scheduled = 0
    failed = 0
    pending = 0
    failures: list[str] = []
    for item in requests:
        complete_path = Path(str(item.get("slot_complete_path") or ""))
        if not complete_path.exists():
            pending += 1
            continue
        payload = read_json(complete_path)
        status = str(payload.get("status", "")).lower()
        if status == "complete":
            scheduled += 1
        elif status == "failed":
            failed += 1
            failures.append(
                f"{item.get('slot', '')}: {payload.get('failed_stage', 'unknown')} - {str(payload.get('error', ''))[:120]}"
            )
        else:
            pending += 1
    target_dates = sorted({str(item.get("target_date", "")) for item in requests if item.get("target_date")})
    status_label = "COMPLETE" if failed == 0 and pending == 0 else "ATTENTION"
    lines = [
        f"[{status_label}] Daily Batch Summary",
        "",
        f"Page: {page_label(page_key)}",
        f"Posting Date: {', '.join(_pretty_date(x) for x in target_dates)}",
        "",
        f"Scheduled: {scheduled}",
        f"Failed: {failed}",
        f"Pending: {pending}",
        f"Total: {total}",
        "",
        f"Run Folder: {_windows_text_path(run_root)}" if run_root else "",
    ]
    if failures:
        lines.extend(["", "Failures:"])
        lines.extend(failures[:5])
    send_telegram("\n".join(x for x in lines if x != ""))
    return {"scheduled": scheduled, "failed": failed, "pending": pending, "total": total, "run_root": run_root}
