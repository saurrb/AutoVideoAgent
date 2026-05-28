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


def _latest_mp4_from_grok_sessions(home: Path) -> Path:
    base = home / ".grok" / "sessions"
    files = sorted(base.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError("No mp4 found in Grok sessions.")
    return files[0]


def _latest_mp4_newer_than(home: Path, since_ts: float) -> Path | None:
    base = home / ".grok" / "sessions"
    files = sorted(base.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        try:
            if f.stat().st_mtime > since_ts:
                return f
        except Exception:
            continue
    return None


def _wait_for_stable_file(path: Path, checks: int = 2, sleep_sec: float = 1.5) -> None:
    last_size = -1
    stable_hits = 0
    while stable_hits < checks:
        size = path.stat().st_size if path.exists() else 0
        if size > 0 and size == last_size:
            stable_hits += 1
        else:
            stable_hits = 0
        last_size = size
        time.sleep(sleep_sec)


def _run_grok_and_wait_for_mp4(
    grok_exe: Path,
    prompt: str,
    *,
    cwd: Path,
    home: Path,
    poll_sec: float = 3.0,
    max_wait_sec: int = 0,
) -> Path:
    start_ts = time.time()
    proc = subprocess.Popen(
        [str(grok_exe), "-p", prompt],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        while True:
            newest = _latest_mp4_newer_than(home, start_ts - 0.5)
            if newest is not None:
                _wait_for_stable_file(newest)
                try:
                    if proc.poll() is None:
                        proc.terminate()
                except Exception:
                    pass
                return newest

            if proc.poll() is not None:
                out, err = proc.communicate(timeout=5)
                raise RuntimeError(
                    "Grok exited before producing mp4.\n"
                    f"STDOUT:\n{out}\nSTDERR:\n{err}"
                )

            if max_wait_sec > 0 and (time.time() - start_ts) > max_wait_sec:
                try:
                    proc.kill()
                except Exception:
                    pass
                raise TimeoutError(
                    f"Grok mp4 did not appear within {max_wait_sec}s for prompt: {prompt[:120]}..."
                )
            time.sleep(poll_sec)
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass


def _parse_seconds(v: object, default: int = 10) -> int:
    if v is None:
        return default
    s = str(v).strip()
    if not s:
        return default
    m = re.search(r"\d+", s)
    return int(m.group(0)) if m else default


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
        "scene_a_duration_sec": 10,
        "scene_b_duration_sec": 10,
        "target_resolution": "720p",
        "target_aspect_ratio": "9:16",
        "caption": caption,
        "hashtags": hashtags,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate one Dragon Cinema reel (10s+10s chain) via Grok + FFmpeg.")
    ap.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--page", default="dragon_cinema")
    ap.add_argument("--sheet", default="Sheet1")
    args = ap.parse_args()

    root = Path(args.project_root).resolve()
    xlsx = root / "pages" / args.page / "content" / "dragon_scenes.xlsx"
    ffmpeg = root / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin" / "ffmpeg.exe"
    ffprobe = root / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin" / "ffprobe.exe"
    grok = Path.home() / ".grok" / "bin" / "grok.exe"

    if not grok.exists():
        raise FileNotFoundError(f"Grok CLI not found: {grok}")

    db_path = root / "data" / "v2" / "state.sqlite3"
    conn = connect(db_path)
    row = _pick_next_row_db(conn, args.page)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = root / "runs" / datetime.now().strftime("%Y-%m-%d") / args.page / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Scene A
    prompt_a = (
        f"Generate one video. Duration {row['scene_a_duration_sec']} seconds. "
        f"Resolution {row['target_resolution']}. Aspect ratio {row['target_aspect_ratio']}. "
        f"Prompt: {row['scene_a_prompt']} "
        "Return only the generated video file path."
    )
    scene_a = _run_grok_and_wait_for_mp4(
        grok,
        prompt_a,
        cwd=root,
        home=Path.home(),
        poll_sec=3.0,
        max_wait_sec=0,
    )
    scene_a_out = run_dir / f"dragon_{row['id']}_scene_a.mp4"
    scene_a_out.write_bytes(scene_a.read_bytes())

    # Last frame of A
    last_frame = run_dir / f"dragon_{row['id']}_scene_a_last_frame.png"
    _run(
        [
            str(ffmpeg),
            "-y",
            "-sseof",
            "-0.2",
            "-i",
            str(scene_a_out),
            "-vframes",
            "1",
            "-update",
            "1",
            str(last_frame),
        ]
    )

    # Scene B continuation
    prompt_b = (
        f"Use this image as continuity reference and continue the story: {last_frame}. "
        f"Generate one video. Duration {row['scene_b_duration_sec']} seconds. "
        f"Resolution {row['target_resolution']}. Aspect ratio {row['target_aspect_ratio']}. "
        f"Prompt: {row['scene_b_prompt']} "
        "Return only the generated video file path."
    )
    scene_b = _run_grok_and_wait_for_mp4(
        grok,
        prompt_b,
        cwd=root,
        home=Path.home(),
        poll_sec=3.0,
        max_wait_sec=0,
    )
    scene_b_out = run_dir / f"dragon_{row['id']}_scene_b.mp4"
    scene_b_out.write_bytes(scene_b.read_bytes())

    # Stitch A + B
    concat_txt = run_dir / "concat.txt"
    concat_txt.write_text("file 'dragon_{id}_scene_a.mp4'\nfile 'dragon_{id}_scene_b.mp4'\n".format(id=row["id"]), encoding="ascii")
    final_mp4 = run_dir / f"dragon_{row['id']}_final_20s.mp4"
    _run(
        [
            str(ffmpeg),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-c",
            "copy",
            str(final_mp4),
        ],
        cwd=run_dir,
    )

    # Logo overlay (same concept as page1/page2).
    logo_path = root / "pages" / args.page / "assets" / "logo" / "logo1.png"
    final_logo_mp4 = run_dir / f"dragon_{row['id']}_final_20s_logo.mp4"
    if logo_path.exists():
        _run(
            [
                str(ffmpeg),
                "-y",
                "-i",
                str(final_mp4),
                "-i",
                str(logo_path),
                "-filter_complex",
                "[1:v]scale=60:-1,format=rgba,colorchannelmixer=aa=0.40[lg];[0:v][lg]overlay=W-w-8:H-h-8[v]",
                "-map",
                "[v]",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                str(final_logo_mp4),
            ]
        )
        final_mp4 = final_logo_mp4

    # Final normalize: force 720x1280 for all dragon outputs.
    final_720 = run_dir / f"dragon_{row['id']}_final_20s_720x1280.mp4"
    _run(
        [
            str(ffmpeg),
            "-y",
            "-i",
            str(final_mp4),
            "-vf",
            "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(final_720),
        ]
    )
    final_mp4 = final_720

    meta = _run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "stream=width,height",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(final_mp4),
        ]
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
        "scene_a_mp4": str(scene_a_out),
        "scene_b_mp4": str(scene_b_out),
        "scene_a_last_frame": str(last_frame),
        "final_mp4": str(final_mp4),
        "ffprobe": json.loads(meta),
    }
    manifest_path = run_dir / f"dragon_{row['id']}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"PAGE={args.page}")
    print(f"ROW_ID={row['id']}")
    print(f"HEADING={row['heading']}")
    print(f"FINAL_MP4={final_mp4}")
    print(f"MANIFEST={manifest_path}")


if __name__ == "__main__":
    main()
