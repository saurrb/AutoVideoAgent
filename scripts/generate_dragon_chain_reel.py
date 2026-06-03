from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autovideo.services.state_store import connect


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 600) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return p.stdout.strip()


def _pick_next_row_db(conn: sqlite3.Connection, page_key: str) -> dict:
    row = conn.execute(
        "SELECT item_id, point_text, caption, hashtags "
        "FROM content_bank_rows "
        "WHERE page_key=? "
        "AND item_id NOT IN (SELECT item_id FROM content_items WHERE page_key=? AND used=1) "
        "AND item_id NOT IN (SELECT content_id FROM used_state WHERE page_key=? AND used=1) "
        "ORDER BY item_id ASC LIMIT 1",
        (page_key, page_key, page_key),
    ).fetchone()
    if not row:
        raise RuntimeError("No unused dragon DB rows left.")
    item_id = int(row[0])
    point_text = str(row[1] or "").strip()
    caption = str(row[2] or "").strip()
    hashtags = str(row[3] or "").strip()
    scene_a_prompt, scene_b_prompt = (point_text.split("||", 1) + [""])[:2]
    scene_a_prompt = scene_a_prompt.strip()
    scene_b_prompt = scene_b_prompt.strip()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO content_items(page_key,item_id,used,used_at) VALUES(?,?,1,?) "
        "ON CONFLICT(page_key,item_id) DO UPDATE SET used=1,used_at=excluded.used_at",
        (page_key, item_id, now),
    )
    conn.execute(
        "INSERT INTO used_state(page_key,content_id,used,used_at) VALUES(?,?,1,?) "
        "ON CONFLICT(page_key,content_id) DO UPDATE SET used=1,used_at=excluded.used_at",
        (page_key, item_id, now),
    )
    conn.commit()
    return {
        "id": item_id,
        "heading": f"Dragon Scene {item_id}",
        "scene_a_prompt": scene_a_prompt,
        "scene_b_prompt": scene_b_prompt or scene_a_prompt,
        "scene_a_duration_sec": 15,
        "scene_b_duration_sec": 15,
        "target_resolution": "720p",
        "target_aspect_ratio": "9:16",
        "caption": caption,
        "hashtags": hashtags,
    }


def _kill_process_tree(pid: int) -> None:
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
    except Exception:
        pass


def _wait_done_json(done_path: Path, timeout_sec: int) -> dict:
    start = time.time()
    while True:
        if done_path.exists():
            return json.loads(done_path.read_text(encoding="utf-8"))
        if (time.time() - start) > timeout_sec:
            raise TimeoutError(f"Timed out waiting for {done_path}")
        time.sleep(1.0)


def _run_step(script: Path, args: list[str], done_path: Path, timeout_sec: int, cleanup_paths: list[Path]) -> dict:
    if done_path.exists():
        done_path.unlink(missing_ok=True)
    cmd = [sys.executable, str(script), *args]
    proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    start = time.time()
    out = ""
    err = ""
    payload: dict | None = None
    while True:
        if done_path.exists():
            payload = json.loads(done_path.read_text(encoding="utf-8"))
            break
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=5)
            raise RuntimeError(
                f"Step exited before done artifact: {script.name}\n"
                f"STDOUT:\n{out}\nSTDERR:\n{err}"
            )
        if (time.time() - start) > timeout_sec:
            _kill_process_tree(proc.pid)
            for p in cleanup_paths:
                try:
                    if p.is_file():
                        p.unlink(missing_ok=True)
                except Exception:
                    pass
            out, err = proc.communicate(timeout=5)
            raise RuntimeError(
                f"Step timeout waiting done artifact: {script.name}\n"
                f"STDOUT:\n{out}\nSTDERR:\n{err}"
            )
        time.sleep(1.0)

    out, err = proc.communicate(timeout=5)
    if proc.returncode != 0:
        raise RuntimeError(f"Step non-zero: {script.name}\nSTDOUT:\n{out}\nSTDERR:\n{err}")
    if payload is None or str(payload.get("status", "")) != "ok":
        raise RuntimeError(f"Step status not ok: {script.name} payload={payload}")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate one Dragon Cinema reel with step-artifact orchestration.")
    ap.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--page", default="dragon_cinema")
    ap.add_argument("--slot", default="", help="Target slot HH:MM used for output file naming.")
    ap.add_argument("--schedule-date", default="", help="Target schedule date YYYY-MM-DD used for output file naming.")
    args = ap.parse_args()

    root = Path(args.project_root).resolve()
    ffmpeg = root / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin" / "ffmpeg.exe"
    ffprobe = root / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin" / "ffprobe.exe"

    db_path = root / "data" / "v2" / "state.sqlite3"
    conn = connect(db_path)
    row = _pick_next_row_db(conn, args.page)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = root / "runs" / datetime.now().strftime("%Y-%m-%d") / args.page / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    schedule_date = str(args.schedule_date or "").strip() or datetime.now().strftime("%Y-%m-%d")
    slot_hhmm = str(args.slot or "").strip() or "unknown"
    slot_compact = slot_hhmm.replace(":", "")

    context = {
        "project_root": str(root),
        "run_dir": str(run_dir),
        "row_id": row["id"],
        "scene_a_prompt": row["scene_a_prompt"],
        "scene_b_prompt": row["scene_b_prompt"],
        "scene_a_duration_sec": row["scene_a_duration_sec"],
        "scene_b_duration_sec": row["scene_b_duration_sec"],
        "target_resolution": row["target_resolution"],
        "target_aspect_ratio": row["target_aspect_ratio"],
        "caption": row["caption"],
        "hashtags": row["hashtags"],
        "ffmpeg": str(ffmpeg),
        "ffprobe": str(ffprobe),
        "logo_path": str(root / "pages" / args.page / "assets" / "logo" / "logo1.png"),
        "schedule_date": schedule_date,
        "slot": slot_hhmm,
        "slot_compact": slot_compact,
    }
    ctx_path = run_dir / "render_context.json"
    ctx_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")

    script_dir = root / "scripts"
    scene_a_done = run_dir / "step_scene_a.done.json"
    scene_b_done = run_dir / "step_scene_b.done.json"
    final_done = run_dir / "step_finalize.done.json"

    scene_a = _run_step(
        script_dir / "dragon_step_scene_a.py",
        ["--context", str(ctx_path), "--out", str(scene_a_done)],
        scene_a_done,
        timeout_sec=1800,
        cleanup_paths=[run_dir / f"dragon_{row['id']}_scene_a.mp4"],
    )
    scene_b = _run_step(
        script_dir / "dragon_step_scene_b.py",
        ["--context", str(ctx_path), "--in-a", scene_a["output_mp4"], "--out", str(scene_b_done)],
        scene_b_done,
        timeout_sec=1800,
        cleanup_paths=[run_dir / f"dragon_{row['id']}_scene_b.mp4", run_dir / f"dragon_{row['id']}_scene_a_last_frame.png"],
    )
    final = _run_step(
        script_dir / "dragon_step_finalize.py",
        ["--context", str(ctx_path), "--in-a", scene_a["output_mp4"], "--in-b", scene_b["output_mp4"], "--out", str(final_done)],
        final_done,
        timeout_sec=600,
        cleanup_paths=[Path(run_dir) / f"dragon_{row['id']}_{schedule_date}_{slot_compact}_final_singlepass_20s_720x1280.mp4"],
    )

    manifest = {
        "page": args.page,
        "run_id": run_id,
        "row_id": row["id"],
        "heading": row["heading"],
        "scene_a_duration_sec": row["scene_a_duration_sec"],
        "scene_b_duration_sec": row["scene_b_duration_sec"],
        "resolution": row["target_resolution"],
        "aspect_ratio": row["target_aspect_ratio"],
        "caption": row["caption"],
        "hashtags": row["hashtags"],
        "scene_a_mp4": scene_a["output_mp4"],
        "scene_b_mp4": scene_b["output_mp4"],
        "scene_a_last_frame": scene_b.get("last_frame", ""),
        "final_mp4": final["final_mp4"],
        "singlepass_attempted": True,
        "singlepass_fallback_used": False,
        "schedule_date": schedule_date,
        "slot": slot_hhmm,
        "ffprobe": final.get("ffprobe", {}),
        "step_artifacts": {
            "scene_a": str(scene_a_done),
            "scene_b": str(scene_b_done),
            "finalize": str(final_done),
        },
    }
    manifest_path = run_dir / f"dragon_{row['id']}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"PAGE={args.page}")
    print(f"ROW_ID={row['id']}")
    print(f"HEADING={row['heading']}")
    print(f"FINAL_MP4={final['final_mp4']}")
    print(f"MANIFEST={manifest_path}")


if __name__ == "__main__":
    main()
