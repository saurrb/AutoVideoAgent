from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = PROJECT_ROOT / "control" / "automation_runtime.json"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_PATH = LOG_DIR / "watchdog_recover.log"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _log(line: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{_now_iso()}] {line}\n")


def _task_name_for_page(page_key: str) -> str:
    names = {
        "female_psychology": "AutoVideoAgent_Page1_FemalePsychology_8AM",
        "daily_desire_facts": "AutoVideoAgent_Page2_DailyDesire_830AM",
        "dragon_cinema": "AutoVideoAgent_Page3_DragonCinema_9AM",
    }
    return names.get(page_key, "")


def _load_runtime_pages() -> dict[str, str]:
    if not RUNTIME_PATH.exists():
        return {}
    data = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for p in data.get("pages", []):
        k = str(p.get("page_key", "")).strip()
        if k:
            out[k] = _task_name_for_page(k)
    return out


def _ps_json(script: str) -> list[dict]:
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        script + " | ConvertTo-Json -Depth 5",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    txt = proc.stdout.strip()
    try:
        parsed = json.loads(txt)
    except Exception:
        return []
    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return []


def _kill_stale(max_age_min: int) -> list[int]:
    cutoff = datetime.now() - timedelta(minutes=max_age_min)
    script = r"""
$cutoff = (Get-Date).AddMinutes(-""" + str(max_age_min) + r""")
Get-CimInstance Win32_Process |
Where-Object {
  ($_.Name -in @('python.exe','ffmpeg.exe','grok.exe')) -and
  ($_.CreationDate -lt $cutoff) -and
  (
    ($_.CommandLine -like '*AutoVideoAgent*') -or
    ($_.CommandLine -like '*daily_ui_batch_schedule.py*') -or
    ($_.CommandLine -like '*create_and_post_reel.py*') -or
    ($_.CommandLine -like '*autovideo.app.cli*')
  )
} |
Select-Object ProcessId, Name, CommandLine, CreationDate
"""
    procs = _ps_json(script)
    killed: list[int] = []
    for p in procs:
        pid = int(p.get("ProcessId", 0) or 0)
        if pid <= 0:
            continue
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
            killed.append(pid)
            _log(f"KILLED pid={pid} name={p.get('Name','?')}")
        except Exception as ex:
            _log(f"KILL_FAILED pid={pid} err={ex}")
    _log(f"STALE_SCAN cutoff={cutoff.isoformat(timespec='seconds')} found={len(procs)} killed={len(killed)}")
    return killed


def _task_state(task_name: str) -> str:
    if not task_name:
        return ""
    ps = f"Get-ScheduledTask -TaskName '{task_name}' | Select-Object -ExpandProperty State"
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    return (proc.stdout or "").strip()


def _run_task(task_name: str) -> bool:
    if not task_name:
        return False
    state = _task_state(task_name)
    if state.lower() == "running":
        _log(f"TASK_SKIP task={task_name} reason=already_running")
        return False
    proc = subprocess.run(["schtasks", "/Run", "/TN", task_name], capture_output=True, text=True)
    ok = proc.returncode == 0
    _log(f"TASK_RUN task={task_name} ok={ok} stdout={proc.stdout.strip()} stderr={proc.stderr.strip()}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description="Watchdog for AutoVideoAgent: kill stale pipeline processes and restart task.")
    ap.add_argument("--max-age-min", type=int, default=20, help="Kill matching processes older than this many minutes.")
    ap.add_argument("--page", default="", help="Optional page key to restart only its task.")
    args = ap.parse_args()

    killed = _kill_stale(args.max_age_min)
    pages = _load_runtime_pages()

    restarted = False
    if args.page:
        restarted = _run_task(pages.get(args.page, _task_name_for_page(args.page)))
    else:
        # Default recovery target: daily_desire_facts
        restarted = _run_task(pages.get("daily_desire_facts", _task_name_for_page("daily_desire_facts")))

    print(f"KILLED={len(killed)}")
    print(f"RESTARTED={restarted}")
    print(f"LOG={LOG_PATH}")


if __name__ == "__main__":
    main()

