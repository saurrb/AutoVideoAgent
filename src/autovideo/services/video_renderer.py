from __future__ import annotations

import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
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
    render_profile: str = "production",
) -> tuple[Path, Path, Path, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    ass_path = run_dir / f"{stem}.ass"
    mp4_path = run_dir / f"{stem}.mp4"
    png_path = run_dir / f"{stem}_t1.png"
    manifest_path = run_dir / f"{stem}.manifest.json"

    # ASS cache: reuse compiled subtitle if inputs are identical.
    cache_dir = run_dir.parent / ".ass_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    ass_key_src = f"{ass_template_path}|{asdict(spec)}"
    ass_key = hashlib.sha1(ass_key_src.encode("utf-8")).hexdigest()
    cache_ass_path = cache_dir / f"{ass_key}.ass"
    if cache_ass_path.exists():
        ass_path.write_bytes(cache_ass_path.read_bytes())
    else:
        built = build_ass(ass_template_path, spec)
        ass_path.write_text(built, encoding="utf-8")
        cache_ass_path.write_text(built, encoding="utf-8")
    ass_ff = str(ass_path).replace("\\", "/").replace(":", r"\:")
    w, h = spec.resolution.split("x")
    bg_ext = Path(background_video).suffix.lower()
    is_image_bg = bg_ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

    cmd = [str(ffmpeg_exe), "-y"]
    if is_image_bg:
        # Stable/faster image background path: no infinite stream loop.
        cmd += ["-loop", "1", "-t", str(spec.duration_sec)]
    else:
        cmd += ["-stream_loop", "-1"]
    if render_profile == "fast_preview":
        preset = "veryfast"
        crf = "22"
    else:
        preset = "medium"
        crf = "17"

    cmd += [
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
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@{dark_overlay}:t=fill,"
            f"eq=saturation=1.18:contrast=1.06:brightness=0.03[bg];"
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
        preset,
        "-crf",
        crf,
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

    qa_frames: dict[str, str] = {}
    qa_ok = True
    # Visual QA frame extraction is useful for production, but expensive for fast preview.
    if render_profile != "fast_preview":
        qa_dir = run_dir / "qa_frames"
        qa_dir.mkdir(parents=True, exist_ok=True)
        mid_sec = max(1, spec.duration_sec // 2)
        end_sec = max(1, spec.duration_sec - 1)
        qa_points = [("t1", 1), ("tmid", mid_sec), ("tendm1", end_sec)]
        for tag, sec in qa_points:
            q = qa_dir / f"{stem}_{tag}.png"
            subprocess.run(
                [str(ffmpeg_exe), "-y", "-ss", str(sec), "-i", str(mp4_path), "-frames:v", "1", "-update", "1", str(q)],
                check=True,
            )
            qa_frames[tag] = str(q)
        qa_ok = all(Path(v).exists() and Path(v).stat().st_size > 10_000 for v in qa_frames.values())

    manifest: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "output_mp4": str(mp4_path),
        "output_png": str(png_path),
        "output_ass": str(ass_path),
        "dark_overlay": dark_overlay,
        "render_profile": render_profile,
        "background_video": background_video,
        "qa_frames": qa_frames,
        "qa_text_check_ok": qa_ok,
        "spec": asdict(spec),
    }
    dump_json(manifest_path, manifest)
    return ass_path, mp4_path, png_path, manifest_path
