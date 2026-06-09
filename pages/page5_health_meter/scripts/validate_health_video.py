from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autovideo.services.text_utils import normalize_text  # noqa: E402


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout or ""


def _probe(ffprobe: Path, video: Path) -> dict:
    raw = _run([str(ffprobe), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)])
    return json.loads(raw)


def _duration(probe: dict) -> float:
    try:
        return float(probe.get("format", {}).get("duration") or 0)
    except Exception:
        return 0.0


def _has_audio(probe: dict) -> bool:
    return any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("/mnt/c/Windows/Fonts/arialbd.ttf" if bold else "/mnt/c/Windows/Fonts/arial.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf"),
        Path("/mnt/c/Windows/Fonts/segoeuib.ttf" if bold else "/mnt/c/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _clean_text(value: str) -> str:
    return normalize_text(value, collapse_spaces=True)


def _build_overlay(concept_json: Path, logo_path: Path, output_png: Path) -> None:
    concept = json.loads(concept_json.read_text(encoding="utf-8-sig"))
    headline = _clean_text(concept.get("headline", "Health Meter"))
    topic = _clean_text(concept.get("topic", "Daily wellness guide"))
    rows = concept.get("rows") if isinstance(concept.get("rows"), list) else []

    overlay = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Soft premium poster card that hides Grok's unreliable generated text.
    draw.rounded_rectangle((36, 48, 684, 1212), radius=36, fill=(253, 248, 231, 252))
    draw.rounded_rectangle((36, 48, 684, 1212), radius=36, outline=(18, 120, 118, 220), width=4)
    draw.rectangle((36, 48, 684, 176), fill=(8, 42, 48, 255))
    draw.rounded_rectangle((36, 48, 684, 176), radius=36, outline=(8, 42, 48, 0), width=1)
    draw.rectangle((36, 128, 684, 176), fill=(8, 42, 48, 255))

    brand_font = _font(31, bold=True)
    headline_font = _font(47, bold=True)
    topic_font = _font(24, bold=True)
    item_font = _font(31, bold=True)
    benefit_font = _font(24, bold=False)
    number_font = _font(34, bold=True)

    draw.text((62, 68), "THE HEALTH METER", font=brand_font, fill=(64, 245, 226, 255))
    draw.text((62, 116), topic.upper()[:38], font=topic_font, fill=(255, 204, 92, 255))

    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((118, 118), Image.Resampling.LANCZOS)
        lx = 684 - logo.width - 28
        ly = 58
        overlay.alpha_composite(logo, (lx, ly))

    y = 214
    for line in _wrap_text(draw, headline, headline_font, 610)[:2]:
        draw.text((62, y), line, font=headline_font, fill=(9, 34, 40, 255))
        y += 56
    draw.line((62, y + 12, 660, y + 12), fill=(232, 172, 49, 255), width=5)
    y += 54

    row_top = y
    row_h = 136
    accent_colors = [
        (16, 151, 146, 255),
        (231, 139, 37, 255),
        (36, 116, 184, 255),
        (104, 157, 44, 255),
        (200, 66, 58, 255),
    ]
    for idx, row in enumerate(rows[:5], start=1):
        top = row_top + (idx - 1) * row_h
        color = accent_colors[(idx - 1) % len(accent_colors)]
        draw.rounded_rectangle((62, top, 660, top + 112), radius=22, fill=(255, 255, 250, 255), outline=(226, 220, 196, 255), width=2)
        draw.ellipse((82, top + 24, 146, top + 88), fill=color)
        draw.text((95, top + 39), f"{idx:02d}", font=number_font, fill=(255, 255, 255, 255))
        draw.line((166, top + 24, 166, top + 88), fill=(232, 172, 49, 220), width=3)

        item = _clean_text(row.get("item", ""))
        benefit = _clean_text(row.get("benefit", ""))
        draw.text((188, top + 20), item[:28], font=item_font, fill=(12, 44, 51, 255))
        benefit_lines = _wrap_text(draw, benefit, benefit_font, 430)[:2]
        by = top + 60
        for benefit_line in benefit_lines:
            draw.text((188, by), benefit_line, font=benefit_font, fill=(45, 63, 64, 255))
            by += 31

    footer = "Save this quick wellness guide"
    draw.rounded_rectangle((104, 1130, 616, 1184), radius=24, fill=(8, 42, 48, 235))
    footer_font = _font(27, bold=True)
    bbox = draw.textbbox((0, 0), footer, font=footer_font)
    draw.text(((720 - (bbox[2] - bbox[0])) // 2, 1144), footer, font=footer_font, fill=(255, 230, 142, 255))

    output_png.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(output_png)


def main() -> None:
    ap = argparse.ArgumentParser(description="Normalize Page5 Grok video to 6s 720x1280 with audio.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--ffmpeg", required=True)
    ap.add_argument("--ffprobe", required=True)
    ap.add_argument("--concept-json", default="")
    ap.add_argument("--logo", default="")
    ap.add_argument("--duration", type=float, default=6.0)
    args = ap.parse_args()

    input_mp4 = Path(args.input)
    output_mp4 = Path(args.output)
    ffmpeg = Path(args.ffmpeg)
    ffprobe = Path(args.ffprobe)
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    if not input_mp4.exists():
        raise FileNotFoundError(f"Input video not found: {input_mp4}")
    before = _probe(ffprobe, input_mp4)
    if not _has_audio(before):
        raise RuntimeError("Grok video has no audio stream. Page5 requires music/SFX in the generated video.")

    base_filter = (
        "scale=720:1280:force_original_aspect_ratio=increase,"
        "crop=720:1280,fps=30,"
        "eq=contrast=1.08:saturation=1.12:brightness=0.015,"
        "unsharp=5:5:0.55:3:3:0.25"
    )
    concept_json = Path(args.concept_json) if args.concept_json else Path()
    logo_path = Path(args.logo) if args.logo else Path()
    overlay_png = output_mp4.with_name(output_mp4.stem + "_overlay.png")
    if concept_json.exists():
        _build_overlay(concept_json, logo_path, overlay_png)
        filter_complex = f"[0:v]{base_filter}[v0];[v0][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
        cmd = [
            str(ffmpeg),
            "-y",
            "-i",
            str(input_mp4),
            "-i",
            str(overlay_png),
            "-t",
            f"{float(args.duration):.3f}",
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_mp4),
        ]
    else:
        cmd = [
            str(ffmpeg),
            "-y",
            "-i",
            str(input_mp4),
            "-t",
            f"{float(args.duration):.3f}",
            "-vf",
            base_filter + ",format=yuv420p",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_mp4),
        ]
    _run(cmd)

    after = _probe(ffprobe, output_mp4)
    final_duration = _duration(after)
    if final_duration < 5.5:
        raise RuntimeError(f"Final video too short: {final_duration:.2f}s")
    if not _has_audio(after):
        raise RuntimeError("Final video lost audio stream.")

    done = output_mp4.with_suffix(".done.json")
    payload = {
        "status": "ok",
        "input_mp4": str(input_mp4),
        "output_mp4": str(output_mp4),
        "duration_sec": final_duration,
        "has_audio": True,
        "overlay_png": str(overlay_png) if overlay_png.exists() else "",
        "probe": after,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    done.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OUTPUT_MP4={output_mp4}")
    print(f"DONE={done}")


if __name__ == "__main__":
    main()

