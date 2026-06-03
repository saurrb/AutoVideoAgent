from __future__ import annotations

import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Any

from autovideo.domain.reel_spec import ReelSpec
from autovideo.services.ass_renderer import build_ass
from autovideo.services.config_loader import dump_json


def _windows_to_wsl_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if len(normalized) > 2 and normalized[1:3] == ":/":
        drive = normalized[0].lower()
        return f"/mnt/{drive}/{normalized[3:]}"
    return value


def _local_file_path(value: str | Path) -> Path:
    path_value = str(value)
    if os.name != "nt":
        path_value = _windows_to_wsl_path(path_value)
    return Path(path_value)


def _wsl_to_windows_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if normalized.startswith("/mnt/") and len(normalized) > 6 and normalized[6] == "/":
        drive = normalized[5].upper()
        return f"{drive}:/{normalized[7:]}"
    return value


def _ffmpeg_arg_path(value: str | Path, *, ffmpeg_exe: Path) -> str:
    path_value = str(value)
    if os.name != "nt" and str(ffmpeg_exe).lower().endswith(".exe"):
        return _wsl_to_windows_path(path_value)
    return path_value


def _ffmpeg_filter_path(value: str | Path, *, ffmpeg_exe: Path) -> str:
    path_value = _ffmpeg_arg_path(value, ffmpeg_exe=ffmpeg_exe).replace("\\", "/")
    return path_value.replace(":", r"\:")


def _font_path(name: str) -> Path:
    candidates: list[Path]
    if os.name == "nt":
        base = Path("C:/Windows/Fonts")
        candidates = [base / name]
    else:
        candidates = [Path("/mnt/c/Windows/Fonts") / name, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _render_female_psychology_card(png_path: Path, spec: ReelSpec) -> None:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    width, height = [int(x) for x in spec.resolution.split("x", 1)]
    yellow = (255, 186, 22)
    white = (245, 245, 240)
    muted = (222, 222, 218)
    black = (2, 2, 2)
    line = (236, 186, 52)
    impact = _font_path("impact.ttf")
    arial_n_bold = _font_path("ARIALNB.TTF")
    arial_bold = _font_path("arialbd.ttf")

    def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            return ImageFont.truetype(str(_font_path("arialbd.ttf")), size)

    def text_w(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
        if not text:
            return 0
        box = draw.textbbox((0, 0), text, font=font)
        return box[2] - box[0]

    def text_h(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
        box = draw.multiline_textbbox((0, 0), text, font=font, spacing=8)
        return box[3] - box[1]

    def fit_font(draw: ImageDraw.ImageDraw, text: str, font_path: Path, max_width: int, start: int, minimum: int) -> ImageFont.FreeTypeFont:
        for size in range(start, minimum - 1, -2):
            fnt = load_font(font_path, size)
            if text_w(draw, text, fnt) <= max_width:
                return fnt
        return load_font(font_path, minimum)

    def wrap_pixels(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if text_w(draw, candidate, font) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def draw_distressed_text(base: Image.Image, xy: tuple[int, int], text: str, font: ImageFont.FreeTypeFont, fill: tuple[int, int, int]) -> None:
        import random

        draw = ImageDraw.Draw(base)
        x, y = xy
        draw.text((x + 2, y + 2), text, font=font, fill=(45, 45, 45))
        draw.text((x, y), text, font=font, fill=fill)
        mask = Image.new("L", base.size, 0)
        md = ImageDraw.Draw(mask)
        md.text((x, y), text, font=font, fill=255)
        scratch = Image.new("RGBA", base.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(scratch)
        rng = random.Random(43 + len(text))
        bbox = draw.textbbox((x, y), text, font=font)
        for _ in range(70):
            sx = rng.randint(max(0, bbox[0]), min(width - 1, bbox[2]))
            sy = rng.randint(max(0, bbox[1]), min(height - 1, bbox[3]))
            sw = rng.randint(2, 10)
            sh = rng.randint(1, 4)
            sd.rectangle((sx, sy, sx + sw, sy + sh), fill=(0, 0, 0, 78))
        scratch.putalpha(Image.composite(scratch.getchannel("A"), Image.new("L", base.size, 0), mask))
        base.alpha_composite(scratch)

    image = Image.new("RGBA", (width, height), black + (255,))
    noise = Image.effect_noise((width, height), 9).convert("L")
    image.alpha_composite(Image.merge("RGBA", (noise, noise, noise, Image.new("L", (width, height), 18))))
    for radius, alpha in [(580, 18), (430, 14), (280, 10)]:
        glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((width // 2 - radius, 110 - radius, width // 2 + radius, 110 + radius), fill=(255, 255, 255, alpha))
        image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))

    draw = ImageDraw.Draw(image)
    heading1 = (spec.heading_line1 or "FEMALE PSYCHOLOGY").upper()
    heading2 = (spec.heading_line2 or "ATTRACTION FACT").upper()
    title_font = fit_font(draw, heading1, impact, width - 72, 104, 52)
    title_w = text_w(draw, heading1, title_font)
    draw_distressed_text(image, ((width - title_w) // 2, 118), heading1, title_font, white)

    category_font = fit_font(draw, heading2, impact, width - 210, 46, 30)
    category_w = text_w(draw, heading2, category_font)
    category_y = 286
    category_x = (width - category_w) // 2
    draw.line((category_x - 72, category_y + 24, category_x - 22, category_y + 24), fill=muted, width=3)
    draw.line((category_x + category_w + 22, category_y + 24, category_x + category_w + 72, category_y + 24), fill=muted, width=3)
    draw.text((category_x, category_y), heading2, font=category_font, fill=yellow)

    number_font = load_font(impact, 50)
    body_font = load_font(arial_n_bold if arial_n_bold.exists() else arial_bold, 43)
    body_max_width = 440
    points = [point.text.strip() for point in spec.points[:5]]
    wrapped = [wrap_pixels(draw, point, body_font, body_max_width) for point in points]

    def total_body_height(linesets: list[list[str]], font: ImageFont.FreeTypeFont) -> int:
        line_height = text_h(draw, "Ag", font) + 8
        return sum(max(2, len(lines)) * line_height for lines in linesets) + 56 * (len(linesets) - 1)

    while total_body_height(wrapped, body_font) > 745 and body_font.size > 32:
        body_font = load_font(arial_n_bold if arial_n_bold.exists() else arial_bold, body_font.size - 2)
        wrapped = [wrap_pixels(draw, point, body_font, body_max_width) for point in points]

    y = 405
    number_x = 78
    line_x = 150
    text_x = 184
    line_height = text_h(draw, "Ag", body_font) + 8
    for idx, lines in enumerate(wrapped, start=1):
        block_height = max(2, len(lines)) * line_height
        draw.text((number_x, y + 4), f"{idx:02d}.", font=number_font, fill=yellow)
        draw.line((line_x, y - 6, line_x, y + block_height + 6), fill=line, width=2)
        for line_idx, body_line in enumerate(lines):
            draw.text((text_x, y + line_idx * line_height), body_line, font=body_font, fill=white)
        y += block_height + 56

    logo_path = _local_file_path(spec.logo_path)
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        target_w = max(96, min(124, int(width * 0.15)))
        target_h = int(logo.height * (target_w / logo.width))
        logo = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)
        image.alpha_composite(logo, (width - target_w - 48, height - target_h - 54))

    png_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(png_path, quality=95)


def _render_female_psychology_reel(
    ffmpeg_exe: Path,
    run_dir: Path,
    stem: str,
    spec: ReelSpec,
    render_profile: str,
) -> tuple[Path, Path, Path, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    ass_path = run_dir / f"{stem}.ass"
    png_path = run_dir / f"{stem}_t1.png"
    mp4_path = run_dir / f"{stem}.mp4"
    manifest_path = run_dir / f"{stem}.manifest.json"
    ass_path.write_text("; image-card render: no ASS subtitles\n", encoding="utf-8")
    _render_female_psychology_card(png_path, spec)

    if render_profile == "fast_preview":
        preset = "veryfast"
        crf = "18"
    else:
        preset = "medium"
        crf = "17"

    cmd = [
        str(ffmpeg_exe),
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(spec.fps),
        "-i",
        _ffmpeg_arg_path(png_path, ffmpeg_exe=ffmpeg_exe),
        "-stream_loop",
        "-1",
        "-i",
        _ffmpeg_arg_path(spec.audio_path, ffmpeg_exe=ffmpeg_exe),
        "-t",
        str(spec.duration_sec),
        "-vf",
        f"scale={spec.resolution},format=yuv420p",
        "-r",
        str(spec.fps),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        crf,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        "-movflags",
        "+faststart",
        _ffmpeg_arg_path(mp4_path, ffmpeg_exe=ffmpeg_exe),
    ]
    subprocess.run(cmd, check=True)

    qa_frames: dict[str, str] = {}
    qa_ok = True
    if render_profile != "fast_preview":
        qa_dir = run_dir / "qa_frames"
        qa_dir.mkdir(parents=True, exist_ok=True)
        for tag, sec in [("t1", 1), ("tmid", max(1, spec.duration_sec // 2)), ("tendm1", max(1, spec.duration_sec - 1))]:
            q = qa_dir / f"{stem}_{tag}.png"
            subprocess.run(
                [
                    str(ffmpeg_exe),
                    "-y",
                    "-ss",
                    str(sec),
                    "-i",
                    _ffmpeg_arg_path(mp4_path, ffmpeg_exe=ffmpeg_exe),
                    "-frames:v",
                    "1",
                    "-update",
                    "1",
                    _ffmpeg_arg_path(q, ffmpeg_exe=ffmpeg_exe),
                ],
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
        "dark_overlay": 0.0,
        "render_profile": render_profile,
        "background_video": "",
        "render_style": "female_psychology_black_yellow_fact_card",
        "qa_frames": qa_frames,
        "qa_text_check_ok": qa_ok,
        "spec": asdict(spec),
    }
    dump_json(manifest_path, manifest)
    return ass_path, mp4_path, png_path, manifest_path


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

    if spec.page_key == "female_psychology":
        return _render_female_psychology_reel(
            ffmpeg_exe=ffmpeg_exe,
            run_dir=run_dir,
            stem=stem,
            spec=spec,
            render_profile=render_profile,
        )

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
    ass_ff = _ffmpeg_filter_path(ass_path, ffmpeg_exe=ffmpeg_exe)
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
        _ffmpeg_arg_path(background_video, ffmpeg_exe=ffmpeg_exe),
        "-i",
        _ffmpeg_arg_path(spec.logo_path, ffmpeg_exe=ffmpeg_exe),
        "-i",
        _ffmpeg_arg_path(spec.audio_path, ffmpeg_exe=ffmpeg_exe),
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
        _ffmpeg_arg_path(mp4_path, ffmpeg_exe=ffmpeg_exe),
    ]
    subprocess.run(cmd, check=True)
    subprocess.run(
        [
            str(ffmpeg_exe),
            "-y",
            "-ss",
            "1",
            "-i",
            _ffmpeg_arg_path(mp4_path, ffmpeg_exe=ffmpeg_exe),
            "-frames:v",
            "1",
            "-update",
            "1",
            _ffmpeg_arg_path(png_path, ffmpeg_exe=ffmpeg_exe),
        ],
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
                [
                    str(ffmpeg_exe),
                    "-y",
                    "-ss",
                    str(sec),
                    "-i",
                    _ffmpeg_arg_path(mp4_path, ffmpeg_exe=ffmpeg_exe),
                    "-frames:v",
                    "1",
                    "-update",
                    "1",
                    _ffmpeg_arg_path(q, ffmpeg_exe=ffmpeg_exe),
                ],
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
