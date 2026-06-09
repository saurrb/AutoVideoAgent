from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout or ""


def _media_arg(path: Path) -> str:
    text = str(path)
    if os.name != "nt" and text.startswith("/mnt/c/"):
        return "C:\\" + text[len("/mnt/c/") :].replace("/", "\\")
    return text


def _probe_audio_seconds(ffprobe: Path, audio_path: Path) -> float:
    raw = _run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            _media_arg(audio_path),
        ]
    ).strip()
    return max(1.0, float(raw))


def main() -> None:
    ap = argparse.ArgumentParser(description="Render Page5 image-first reel with Speechma voice and music.")
    ap.add_argument("--image", required=True)
    ap.add_argument("--voice", required=True)
    ap.add_argument("--music", required=True)
    ap.add_argument("--logo", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--ffmpeg", required=True)
    ap.add_argument("--ffprobe", required=True)
    ap.add_argument("--music-volume", type=float, default=0.10)
    args = ap.parse_args()

    image = Path(args.image)
    voice = Path(args.voice)
    music = Path(args.music)
    logo = Path(args.logo)
    output = Path(args.output)
    ffmpeg = Path(args.ffmpeg)
    ffprobe = Path(args.ffprobe)
    output.parent.mkdir(parents=True, exist_ok=True)

    for label, path in {
        "image": image,
        "voice": voice,
        "music": music,
        "logo": logo,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
    }.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing {label}: {path}")

    duration = _probe_audio_seconds(ffprobe, voice)
    frames = math.ceil(duration * 30)
    music_volume = max(0.0, min(1.0, float(args.music_volume)))

    filter_complex = (
        f"[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,"
        "eq=contrast=1.055:saturation=1.06:brightness=0.005,"
        "unsharp=5:5:0.45:3:3:0.15[v0];"
        "[1:v]scale=98:98:force_original_aspect_ratio=decrease,format=rgba,"
        "colorchannelmixer=aa=1.0[lg];"
        "[v0][lg]overlay=x=W-w-34:y=H-h-34:format=auto,vignette=PI/9[v];"
        f"[2:a]volume=1.0[a_voice];[3:a]volume={music_volume:.4f}[a_music];"
        "[a_voice][a_music]amix=inputs=2:duration=first:dropout_transition=0,"
        "alimiter=limit=0.92[a]"
    )
    cmd = [
        str(ffmpeg),
        "-y",
        "-loop",
        "1",
        "-t",
        f"{duration:.3f}",
        "-i",
        _media_arg(image),
        "-i",
        _media_arg(logo),
        "-i",
        _media_arg(voice),
        "-stream_loop",
        "-1",
        "-i",
        _media_arg(music),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        _media_arg(output),
    ]
    _run(cmd)

    probe_raw = _run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate",
            "-of",
            "json",
            _media_arg(output),
        ]
    )
    payload = {
        "status": "ok",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "image": str(image),
        "voice": str(voice),
        "music": str(music),
        "music_volume_relative_to_voice": music_volume,
        "logo": str(logo),
        "output_mp4": str(output),
        "duration_sec": duration,
        "frames": frames,
        "probe": json.loads(probe_raw),
    }
    done_path = output.with_suffix(".done.json")
    done_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(output))
    print(str(done_path))


if __name__ == "__main__":
    main()
