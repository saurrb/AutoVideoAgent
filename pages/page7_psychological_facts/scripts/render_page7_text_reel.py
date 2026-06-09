from __future__ import annotations

import argparse
import json
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

W, H = 720, 1280
WHITE = (242, 241, 233)
ORANGE = (232, 166, 28)
BLACK = (0, 0, 0)
PAGE_ROOT = Path(__file__).resolve().parents[1]
FONT_BEBAS = PAGE_ROOT / "assets" / "fonts" / "BebasNeue-Regular.ttf"
FONT_BODY_OSWALD = PAGE_ROOT / "assets" / "fonts" / "Oswald-Regular.ttf"
FONT_FALLBACK = Path(r"C:\Windows\Fonts\impact.ttf")


def font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FONT_BEBAS), size=size)
    except Exception:
        return ImageFont.truetype(str(FONT_FALLBACK), size=size)


def body_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FONT_BODY_OSWALD), size=size)
    except Exception:
        return font(size)

def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int, min_size: int = 24):
    size = start
    while size >= min_size:
        f = font(size)
        tw, _ = text_size(draw, text, f)
        if tw <= max_width:
            return f
        size -= 1
    return font(min_size)


def draw_distressed_text(base: Image.Image, xy: tuple[float, float], text: str, fnt: ImageFont.FreeTypeFont, fill: tuple[int, int, int], *, seed: int, amount: int = 140):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text(xy, text, font=fnt, fill=fill + (255,))

    rng = random.Random(seed)
    mask = layer.getchannel("A")
    scratch = Image.new("L", base.size, 0)
    sd = ImageDraw.Draw(scratch)
    x0, y0 = int(xy[0]), int(xy[1])
    tw, th = text_size(ImageDraw.Draw(base), text, fnt)
    for _ in range(amount):
        x = rng.randint(max(0, x0), min(W - 1, x0 + tw))
        y = rng.randint(max(0, y0 + 8), min(H - 1, y0 + th - 2))
        length = rng.randint(2, 11)
        sd.line((x, y, x + rng.randint(-1, 1), y + length), fill=rng.randint(95, 185), width=1)
    scratch = ImageChops.multiply(scratch, mask)
    new_alpha = ImageChops.subtract(mask, scratch.point(lambda p: min(255, int(p * 1.35))))
    layer.putalpha(new_alpha)
    base.alpha_composite(layer)


def spaced_text_width(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, word_spacing: int) -> int:
    words = text.split()
    if not words:
        return 0
    return sum(text_size(draw, word, fnt)[0] for word in words) + word_spacing * (len(words) - 1)


def point_text(point) -> str:
    if isinstance(point, dict):
        return str(point.get("text", "")).strip()
    return str(point).strip()



def draw_spaced_words(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    fnt: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    word_spacing: int,
) -> None:
    x, y = xy
    words = text.split()
    for idx, word in enumerate(words):
        draw.text((x, y), word, font=fnt, fill=fill, stroke_width=0)
        x += text_size(draw, word, fnt)[0]
        if idx < len(words) - 1:
            x += word_spacing


def wrap(draw, text: str, fnt: ImageFont.FreeTypeFont, max_width: int, word_spacing: int = 0) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        width = spaced_text_width(draw, candidate, fnt, word_spacing) if word_spacing else text_size(draw, candidate, fnt)[0]
        if width <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def ffmpeg_path(value: Path | str) -> str:
    text = str(value)
    normalized = text.replace("\\", "/")
    if normalized.startswith("/mnt/") and len(normalized) > 6 and normalized[6] == "/":
        return f"{normalized[5].upper()}:\\{normalized[7:].replace('/', '\\')}"
    return text


def render_frame(data: dict, output: Path):
    img = Image.new("RGBA", (W, H), BLACK + (255,))
    draw = ImageDraw.Draw(img)

    title_left = data["title_left"].upper()
    title_highlight = data["title_highlight"].upper()
    title_font = fit_font(draw, f"{title_left} {title_highlight}", 680, 108, 78)
    y = 103
    left_w, _ = text_size(draw, title_left + " ", title_font)
    high_w, _ = text_size(draw, title_highlight, title_font)
    x = (W - left_w - high_w) / 2
    draw_distressed_text(img, (x, y), title_left + " ", title_font, WHITE, seed=31, amount=175)
    draw_distressed_text(img, (x + left_w, y), title_highlight, title_font, ORANGE, seed=37, amount=60)

    sub = data["subheading"].upper()
    sub_font = fit_font(draw, sub, 440, 54, 38)
    sub_w, sub_h = text_size(draw, sub, sub_font)
    sub_y = 255
    line_y = sub_y + sub_h // 2 + 1
    draw.line((92, line_y, 137, line_y), fill=WHITE, width=2)
    draw.line((W - 137, line_y, W - 92, line_y), fill=WHITE, width=2)
    draw.text(((W - sub_w) / 2, sub_y), sub, font=sub_font, fill=ORANGE)

    num_font = font(50)
    body_font_obj = body_font(35)
    start_y = 350
    point_gap = 38
    x_num = 66
    x_line = 151
    x_body = 183
    max_body_w = 415
    body_word_spacing = 8
    line_step = 39

    y_cursor = start_y
    for i, point in enumerate(data["points"][:5], 1):
        body_text = point_text(point)
        y0 = y_cursor
        lines = wrap(draw, body_text, body_font_obj, max_body_w, body_word_spacing)[:4]
        block_h = max(86, (len(lines) * line_step) - 2)
        draw.text((x_num, y0), f"{i:02d}.", font=num_font, fill=ORANGE)
        divider_offset = 10
        draw.line((x_line, y0 + divider_offset, x_line, y0 + block_h + divider_offset), fill=ORANGE, width=2)
        yy = y0 + 0
        for line in lines:
            draw_spaced_words(draw, (x_body, yy), line, body_font_obj, WHITE, body_word_spacing)
            yy += line_step
        y_cursor += block_h + point_gap

    footer = data.get("footer", "@PSYCHOLOGICAL FACTS").upper()
    footer_font = font(34)
    fw, _ = text_size(draw, footer, footer_font)
    fx = W - fw - 62
    fy = H - 112
    if footer.startswith("@"):
        draw.text((fx, fy), "@", font=footer_font, fill=ORANGE)
        atw, _ = text_size(draw, "@", footer_font)
        draw.text((fx + atw + 4, fy), footer[1:], font=footer_font, fill=WHITE)
    else:
        draw.text((fx, fy), footer, font=footer_font, fill=WHITE)

    output.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(output, quality=96)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--content", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--duration", type=float, default=9.94)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    data = json.loads(Path(args.content).read_text(encoding="utf-8-sig"))
    out_mp4 = Path(args.output)
    frame = out_mp4.with_suffix(".png")
    render_frame(data, frame)
    cmd = [
        args.ffmpeg, "-y",
        "-loop", "1", "-t", str(args.duration), "-i", ffmpeg_path(frame),
        "-i", ffmpeg_path(args.audio),
        "-vf", "scale=720:1280,format=yuv420p,noise=alls=1.4:allf=t+u",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest", "-r", "30",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        ffmpeg_path(out_mp4),
    ]
    subprocess.run(cmd, check=True)
    done = {"output": str(out_mp4), "frame": str(frame), "audio": str(Path(args.audio)), "duration": args.duration, "font": str(FONT_BEBAS)}
    out_mp4.with_suffix(".done.json").write_text(json.dumps(done, indent=2), encoding="utf-8")
    print(json.dumps(done, indent=2))


if __name__ == "__main__":
    main()









