from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'control' / 'automation_runtime.json'
PAGE_KEY = 'page4_relationship'
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autovideo.services.telegram_notify import load_dotenv, reel_status_message, send_telegram  # noqa: E402


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\\nSTDOUT:\\n{p.stdout}\\nSTDERR:\\n{p.stderr}")
    return p.stdout or ''


def _parse_key(stdout: str, key: str) -> str:
    pref = f'{key}='
    for ln in stdout.splitlines():
        if ln.startswith(pref):
            return ln.split('=', 1)[1].strip()
    raise RuntimeError(f'Missing {key}=... in output')


def _load_page_cfg() -> dict:
    cfg = json.loads(RUNTIME.read_text(encoding='utf-8-sig'))
    for p in cfg.get('pages', []):
        if str(p.get('page_key', '')).strip() == PAGE_KEY:
            return p
    raise RuntimeError(f'Page config not found in runtime: {PAGE_KEY}')


def _next_day_slot_dt(slot_hhmm: str) -> datetime:
    hh, mm = [int(x) for x in slot_hhmm.split(':')]
    now = datetime.now()
    dt = (now + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return dt


def main() -> None:
    load_dotenv(ROOT / ".env")
    page_cfg = _load_page_cfg()
    asset_id = str(page_cfg.get('facebook_asset_id', '')).strip()
    slots = [str(s).strip() for s in page_cfg.get('posting_slots', []) if str(s).strip()]
    if not asset_id:
        raise RuntimeError('Missing facebook_asset_id for page4_relationship')
    if not slots:
        raise RuntimeError('No posting_slots found for page4_relationship')

    run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = ROOT / 'runs' / 'manual_batch_page4' / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict] = []
    print(f'BATCH_RUN_DIR={run_dir}')

    for slot in slots:
        target_dt = _next_day_slot_dt(slot)
        print(f'--- SLOT {slot} -> {target_dt.isoformat(timespec="minutes")}')
        rec = {
            'slot': slot,
            'target': target_dt.isoformat(timespec='minutes'),
            'manifest': '',
            'video': '',
            'upload_result': '',
            'status': 'failed',
            'error': '',
        }
        try:
            gen_out = _run([sys.executable, str(ROOT / 'scripts' / 'generate_page4_reel.py')])
            manifest_path = Path(_parse_key(gen_out, 'MANIFEST'))
            video_path = Path(_parse_key(gen_out, 'VIDEO'))
            manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
            caption = str(manifest.get('caption', '')).strip()

            up_cmd = [
                sys.executable,
                str(ROOT / 'pages' / 'automation_tools' / 'meta_ui_schedule' / 'upload_schedule_ui.py'),
                '--page-key', PAGE_KEY,
                '--asset-id', asset_id,
                '--video', str(video_path),
                '--caption', caption,
                '--when', target_dt.strftime('%Y-%m-%dT%H:%M'),
            ]
            up_out = _run(up_cmd)

            rec.update({
                'manifest': str(manifest_path),
                'video': str(video_path),
                'upload_result': up_out.strip(),
                'status': 'scheduled',
                'error': '',
            })
            print(f"SCHEDULED slot={slot} video={video_path.name}")
            send_telegram(
                reel_status_message(
                    page_key=PAGE_KEY,
                    slot=slot,
                    scheduled_for=target_dt.isoformat(timespec='minutes'),
                    status='scheduled',
                    video=str(video_path),
                )
            )
        except Exception as ex:
            rec['error'] = f"{type(ex).__name__}: {ex}"
            print(f"FAILED slot={slot} error={rec['error']}")
            send_telegram(
                reel_status_message(
                    page_key=PAGE_KEY,
                    slot=slot,
                    scheduled_for=target_dt.isoformat(timespec='minutes'),
                    status='failed_render_or_upload',
                    error=rec['error'],
                )
            )

        summary.append(rec)
        (run_dir / f'slot_{slot.replace(":", "")}.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding='utf-8')

    (run_dir / 'summary.json').write_text(json.dumps({'page': PAGE_KEY, 'run_id': run_id, 'results': summary}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'SUMMARY={run_dir / "summary.json"}')
    ok_count = sum(1 for r in summary if r.get("status") == "scheduled")
    fail_count = sum(1 for r in summary if r.get("status") != "scheduled")
    send_telegram(
        "\n".join(
            [
                "AutoVideoAgent KPI",
                f"page: {PAGE_KEY}",
                f"run_id: {run_id}",
                f"scheduled: {ok_count}",
                f"failed: {fail_count}",
                f"summary: {run_dir / 'summary.json'}",
            ]
        )
    )


if __name__ == '__main__':
    main()
