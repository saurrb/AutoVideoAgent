import argparse
import json
import subprocess
import textwrap
from pathlib import Path

FFMPEG = Path(r"C:\Users\Saurabh\Documents\AutoVideoAgent\old_videoAgent\tools\ffmpeg\ffmpeg-8.1.1-essentials_build\bin\ffmpeg.exe")


def ass_escape(s: str) -> str:
    return s.replace('\\', r'\\').replace('{', r'\{').replace('}', r'\}')


def wrap_plain(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)


def split_first_words(text: str, n: int) -> tuple[str, str]:
    words = text.split()
    n = max(1, min(n, len(words)))
    return ' '.join(words[:n]), ' '.join(words[n:])


def make_ass(cfg: dict) -> str:
    st = cfg["style"]
    ct = cfg["content"]

    heading = r"\N".join(ass_escape(x) for x in ct["heading"])

    # Heuristic for safe visual line width under current font/margins.
    wrap_w = int(ct.get("wrap_width", 47))

    points_blocks = []
    for i, p in enumerate(ct["points"], start=1):
        first, rest = split_first_words(p["text"], int(p.get("highlight_first_words", 3)))
        full = f"{first} {rest}".strip()
        lines = wrap_plain(full, wrap_w)
        if not lines:
            continue

        first_line_words = lines[0].split()
        n_hi = min(len(first_line_words), len(first.split()))
        hi = ' '.join(first_line_words[:n_hi])
        rem0 = ' '.join(first_line_words[n_hi:])

        block = f"{i}. " + r"{\rBodyOrange}" + ass_escape(hi) + r"{\rBodyWhite}"
        if rem0:
            block += " " + ass_escape(rem0)
        if len(lines) > 1:
            block += r"\N" + r"\N".join(ass_escape(x) for x in lines[1:])
        points_blocks.append(block)

    body_font_size = int(st["body_font_size"])
    point_gap_scale = float(st.get("point_gap_scale", 1.2))
    extra_gap_ratio = max(0.0, point_gap_scale - 1.0)
    spacer_font_size = max(1, round(body_font_size * extra_gap_ratio))
    point_separator = r"\N" + r"{\fs" + str(spacer_font_size) + r"} {\rBodyWhite}" + r"\N"
    body_text = point_separator.join(points_blocks)

    cta = ass_escape(ct["cta"])
    cta_words = cta.split()
    cta_hi = ' '.join(cta_words[:2])
    cta_rest = ' '.join(cta_words[2:])
    cta_lines = wrap_plain((cta_hi + " " + cta_rest).strip(), 44)
    cta_text = r"{\rCTAOrange}" + ass_escape(' '.join(cta_lines[0].split()[:2])) + r"{\rCTA}"
    tail0 = ' '.join(cta_lines[0].split()[2:])
    if tail0:
        cta_text += " " + ass_escape(tail0)
    if len(cta_lines) > 1:
        cta_text += r"\N" + r"\N".join(ass_escape(x) for x in cta_lines[1:])

    cx, cy = st["cta_pos"]

    return f"""[Script Info]
Title: JSON Reel
ScriptType: v4.00+
PlayResX: 696
PlayResY: 1280
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Title,{st['font']},{st['title_font_size']},{st['text_color_ass']},&H000000FF,{st['outline_color_ass']},&H00000000,1,0,0,0,100,100,0,0,1,1.9,0,8,34,34,{st['header_margin_v']},1
Style: BodyWhite,{st['font']},{st['body_font_size']},{st['text_color_ass']},&H000000FF,{st['outline_color_ass']},&H00000000,0,0,0,0,100,118,0,0,1,1.5,0,7,{st['body_margin_l']},{st['body_margin_r']},{st['body_margin_v']},1
Style: BodyOrange,{st['font']},{st['body_font_size']},{st['highlight_color_ass']},&H000000FF,{st['outline_color_ass']},&H00000000,1,0,0,0,100,118,0,0,1,1.5,0,7,{st['body_margin_l']},{st['body_margin_r']},{st['body_margin_v']},1
Style: CTA,{st['font']},{st['cta_font_size']},{st['text_color_ass']},&H000000FF,{st['outline_color_ass']},&H00000000,1,0,0,0,100,100,0,0,1,1.5,0,8,40,40,235,1
Style: CTAOrange,{st['font']},{st['cta_font_size']},{st['highlight_color_ass']},&H000000FF,{st['outline_color_ass']},&H00000000,1,0,0,0,100,100,0,0,1,1.5,0,8,40,40,235,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
Dialogue: 0,0:00:00.00,0:00:03.00,Title,,0,0,0,,{heading}
Dialogue: 0,0:00:00.00,0:00:03.00,BodyWhite,,0,0,0,,{body_text}
Dialogue: 1,0:00:00.00,0:00:03.00,CTA,,0,0,0,,{{\\an8\\pos({cx},{cy})}}{cta_text}
"""


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run(style_path: Path, content_path: Path, out_stem: str | None):
    style = load_json(style_path)
    content = load_json(content_path)
    style.setdefault("style", {})
    style["style"].setdefault("body_margin_l", 88)
    style["style"].setdefault("body_margin_r", 64)
    style["style"].setdefault("point_gap_scale", 1.2)
    cfg = {**style, **content}

    out_dir = content_path.parent
    stem = out_stem or content_path.stem
    ass = out_dir / f"{stem}.ass"
    mp4 = out_dir / f"{stem}.mp4"
    png = out_dir / f"{stem}_t1.png"

    ass.write_text(make_ass(cfg), encoding="utf-8")
    st = cfg["style"]
    vd = cfg["video"]
    assets = cfg["assets"]
    ass_ff = str(ass).replace('\\', '/').replace(':', '\\:')

    cmd = [
        str(FFMPEG), "-y",
        "-f", "lavfi", "-i", f"color=c={vd['background']}:s={vd['resolution']}:r={vd['fps']}:d={vd['duration_sec']}",
        "-i", assets["logo_path"],
        "-i", assets["audio_path"],
        "-filter_complex", f"[1:v]scale={st['logo_scale_width']}:-1[lg];[0:v]subtitles='{ass_ff}'[txt];[txt][lg]overlay=W-w-{st['logo_margin_right']}:H-h-{st['logo_margin_bottom']}[v]",
        "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", str(mp4)
    ]
    subprocess.run(cmd, check=True)
    subprocess.run([str(FFMPEG), "-y", "-ss", "1", "-i", str(mp4), "-frames:v", "1", "-update", "1", str(png)], check=True)
    print(mp4)
    print(png)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("style_json")
    ap.add_argument("content_json")
    ap.add_argument("--out-stem", default=None)
    args = ap.parse_args()
    run(Path(args.style_json), Path(args.content_json), args.out_stem)
