from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from dragon_step_common import run, write_done_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", required=True)
    ap.add_argument("--in-a", required=True)
    ap.add_argument("--in-b", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    started = time.time()
    ctx = json.loads(Path(args.context).read_text(encoding="utf-8"))
    ffmpeg = Path(ctx["ffmpeg"])
    ffprobe = Path(ctx["ffprobe"])
    run_dir = Path(ctx["run_dir"])
    a = Path(args.in_a)
    b = Path(args.in_b)
    logo = Path(ctx["logo_path"])

    stem = f"dragon_{ctx['row_id']}_{ctx['schedule_date']}_{ctx['slot_compact']}"
    final_mp4 = run_dir / f"{stem}_final_singlepass_20s_720x1280.mp4"
    if logo.exists():
        run([
            str(ffmpeg), "-y", "-i", str(a), "-i", str(b), "-i", str(logo),
            "-filter_complex",
            "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1[a];"
            "[1:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1[b];"
            "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a0];"
            "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a1];"
            "[a][b]concat=n=2:v=1:a=0[cv];"
            "[a0][a1]concat=n=2:v=0:a=1[ca];"
            "[2:v]scale=60:-1,format=rgba,colorchannelmixer=aa=0.40[lg];"
            "[cv][lg]overlay=W-w-8:H-h-8[v]",
            "-map", "[v]", "-map", "[ca]",
            "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            str(final_mp4)
        ])
    else:
        run([
            str(ffmpeg), "-y", "-i", str(a), "-i", str(b),
            "-filter_complex",
            "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1[a];"
            "[1:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1[b];"
            "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a0];"
            "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a1];"
            "[a][b]concat=n=2:v=1:a=0[v];"
            "[a0][a1]concat=n=2:v=0:a=1[ca]",
            "-map", "[v]", "-map", "[ca]",
            "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            str(final_mp4)
        ])

    meta = run([
        str(ffprobe), "-v", "error", "-show_entries", "stream=width,height", "-show_entries", "format=duration", "-of", "json", str(final_mp4)
    ])

    done = {
        "step": "finalize",
        "status": "ok",
        "row_id": ctx["row_id"],
        "final_mp4": str(final_mp4),
        "ffprobe": json.loads(meta),
        "seconds": round(time.time() - started, 2),
        "timestamp": datetime.utcnow().isoformat(),
    }
    write_done_json(Path(args.out), done)


if __name__ == "__main__":
    main()
