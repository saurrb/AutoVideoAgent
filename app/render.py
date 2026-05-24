from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def render_black_reel(
    ffmpeg_exe: Path,
    out_file: Path,
    lines: list[str],
    music_file: Path,
    font_file: Path,
    logo_file: Path | None = None,
    duration_seconds: int = 24,
) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    block = "\n".join([f"{i + 1}. {line}" for i, line in enumerate(lines)])
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".txt") as tf:
        tf.write(block)
        txt_path = Path(tf.name)
    txt_for_ffmpeg = str(txt_path).replace("\\", "/").replace(":", r"\:")
    font_for_ffmpeg = str(font_file).replace("\\", "/").replace(":", r"\:")
    draw = (
        f"drawtext=fontfile='{font_for_ffmpeg}':"
        f"textfile='{txt_for_ffmpeg}':fontcolor=white:fontsize=56:"
        "x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=28"
    )
    try:
        cmd = [str(ffmpeg_exe), "-y", "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:r=30:d={duration_seconds}"]
        if logo_file and logo_file.exists():
            cmd += ["-i", str(logo_file)]
        cmd += ["-stream_loop", "-1", "-i", str(music_file)]
        if logo_file and logo_file.exists():
            filter_complex = (
                f"[0:v]{draw}[base];"
                "[1:v]scale=170:-1[logo];"
                "[base][logo]overlay=x=W-w-56:y=90"
            )
            cmd += ["-filter_complex", filter_complex]
        else:
            cmd += ["-vf", draw]
        cmd += [
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(out_file),
        ]
        subprocess.run(cmd, check=True)
    finally:
        txt_path.unlink(missing_ok=True)
