from __future__ import annotations

import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autovideo.domain.reel_spec import ReelSpec
from autovideo.services.ass_renderer import build_ass
from autovideo.services.config_loader import dump_json


def render_reel(
    ffmpeg_exe: Path,
    ass_template_path: Path,
    run_dir: Path,
    stem: str,
    spec: ReelSpec,
    background_video: str,
    dark_overlay: float,
) -> tuple[Path, Path, Path, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    ass_path = run_dir / f"{stem}.ass"
    mp4_path = run_dir / f"{stem}.mp4"
    png_path = run_dir / f"{stem}_t1.png"
    manifest_path = run_dir / f"{stem}.manifest.json"

    ass_path.write_text(build_ass(ass_template_path, spec), encoding="utf-8")
    ass_ff = str(ass_path).replace("\\", "/").replace(":", r"\:")
    w, h = spec.resolution.split("x")

    cmd = [
        str(ffmpeg_exe),
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        background_video,
        "-i",
        spec.logo_path,
        "-i",
        spec.audio_path,
        "-filter_complex",
        (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},trim=duration={spec.duration_sec},setpts=PTS-STARTPTS,"
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@{dark_overlay}:t=fill[bg];"
            f"[1:v]scale={spec.logo_scale_width}:-1[lg];"
            f"[bg]subtitles='{ass_ff}'[txt];"
            f"[txt][lg]overlay=W-w-{spec.logo_margin_right}:H-h-{spec.logo_margin_bottom}[v]"
        ),
        "-map",
        "[v]",
        "-map",
        "2:a",
        "-t",
        str(spec.duration_sec),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "17",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        str(mp4_path),
    ]
    subprocess.run(cmd, check=True)
    subprocess.run(
        [str(ffmpeg_exe), "-y", "-ss", "1", "-i", str(mp4_path), "-frames:v", "1", "-update", "1", str(png_path)],
        check=True,
    )

    manifest: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "output_mp4": str(mp4_path),
        "output_png": str(png_path),
        "output_ass": str(ass_path),
        "dark_overlay": dark_overlay,
        "background_video": background_video,
        "spec": asdict(spec),
    }
    dump_json(manifest_path, manifest)
    return ass_path, mp4_path, png_path, manifest_path
