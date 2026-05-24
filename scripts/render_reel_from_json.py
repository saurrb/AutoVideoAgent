import argparse
import json
import subprocess
import textwrap
from pathlib import Path

FFMPEG = Path(r"C:\Users\Saurabh\Documents\AutoVideoAgent\tools\ffmpeg\ffmpeg-8.1.1-essentials_build\bin\ffmpeg.exe")
ASS_TEMPLATE = Path(__file__).with_name("reel_template.ass")
DEFAULT_BODY_MARGIN_L = 88
DEFAULT_BODY_MARGIN_R = 64
DEFAULT_POINT_GAP_SCALE = 1.2


def ass_escape(s: str) -> str:
    return s.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def wrap_line(text: str, width: int = 44) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)


def ass_time_from_seconds(seconds: float | int) -> str:
    total_cs = max(0, int(round(float(seconds) * 100)))
    hh = total_cs // 360000
    rem = total_cs % 360000
    mm = rem // 6000
    rem = rem % 6000
    ss = rem // 100
    cs = rem % 100
    return f"{hh}:{mm:02d}:{ss:02d}.{cs:02d}"


def build_point_line(text: str, n_highlight: int) -> str:
    words = text.split()
    n = max(1, min(n_highlight, len(words)))
    first = " ".join(words[:n])
    rest = " ".join(words[n:])
    base = r"{\rBodyOrange}" + ass_escape(first) + r"{\rBodyWhite}"
    if rest:
        base += " " + ass_escape(rest)
    return base


def validate_and_normalize_cfg(cfg: dict) -> dict:
    for key in ("video", "style", "assets", "content"):
        if key not in cfg:
            raise ValueError(f"Missing top-level key: {key}")

    style = cfg["style"]
    content = cfg["content"]
    assets = cfg["assets"]
    video = cfg["video"]

    required_style = (
        "font", "title_font_size", "body_font_size", "cta_font_size",
        "highlight_color_ass", "text_color_ass", "outline_color_ass",
        "header_margin_v", "body_margin_v", "cta_pos", "logo_scale_width",
        "logo_margin_right", "logo_margin_bottom",
    )
    for key in required_style:
        if key not in style:
            raise ValueError(f"Missing style key: {key}")
    style.setdefault("body_margin_l", DEFAULT_BODY_MARGIN_L)
    style.setdefault("body_margin_r", DEFAULT_BODY_MARGIN_R)
    style.setdefault("point_gap_scale", DEFAULT_POINT_GAP_SCALE)

    for key in ("logo_path", "audio_path"):
        if key not in assets:
            raise ValueError(f"Missing assets key: {key}")
    for key in ("duration_sec", "resolution", "fps", "background"):
        if key not in video:
            raise ValueError(f"Missing video key: {key}")
    for key in ("heading", "points", "cta"):
        if key not in content:
            raise ValueError(f"Missing content key: {key}")
    if not isinstance(content["points"], list) or not content["points"]:
        raise ValueError("content.points must be a non-empty list")
    return cfg


def make_ass(cfg: dict) -> str:
    style = cfg["style"]
    content = cfg["content"]
    video = cfg["video"]
    heading = r"\N".join(ass_escape(x) for x in content["heading"])
    end_time = ass_time_from_seconds(video["duration_sec"])

    body_parts = []
    for i, p in enumerate(content["points"], start=1):
        highlighted = build_point_line(p["text"], int(p.get("highlight_first_words", 3)))
        body_parts.append(f"{i}. " + highlighted)
    body_font_size = int(style["body_font_size"])
    point_gap_scale = float(style.get("point_gap_scale", DEFAULT_POINT_GAP_SCALE))
    extra_gap_ratio = max(0.0, point_gap_scale - 1.0)
    spacer_font_size = max(1, round(body_font_size * extra_gap_ratio))
    point_separator = r"\N" + r"{\fs" + str(spacer_font_size) + r"} {\rBodyWhite}" + r"\N"
    body_text = point_separator.join(body_parts)

    cta = ass_escape(content["cta"])
    cta_words = cta.split()
    cta_high = " ".join(cta_words[:2])
    cta_rest = " ".join(cta_words[2:])
    cta_full = cta_high + (" " + cta_rest if cta_rest else "")
    cta_wrapped = wrap_line(cta_full, width=44)
    cta_text = ""
    for idx, ln in enumerate(cta_wrapped):
        if idx == 0:
            parts = ln.split()
            hi = " ".join(parts[:2])
            rem = " ".join(parts[2:])
            cta_text += r"{\rCTAOrange}" + hi + r"{\rCTA}" + (" " + rem if rem else "")
        else:
            cta_text += r"\N" + ln

    template = ASS_TEMPLATE.read_text(encoding="utf-8")
    return template.format(
        font=style["font"],
        title_font_size=style["title_font_size"],
        body_font_size=style["body_font_size"],
        cta_font_size=style["cta_font_size"],
        highlight_color_ass=style["highlight_color_ass"],
        text_color_ass=style["text_color_ass"],
        outline_color_ass=style["outline_color_ass"],
        header_margin_v=style["header_margin_v"],
        body_margin_v=style["body_margin_v"],
        body_margin_l=style["body_margin_l"],
        body_margin_r=style["body_margin_r"],
        cta_x=style["cta_pos"][0],
        cta_y=style["cta_pos"][1],
        end_time=end_time,
        heading=heading,
        body_text=body_text,
        cta_text=cta_text,
    )


def render_cfg(cfg: dict, stem: str, out_dir: Path) -> tuple[Path, Path, Path]:
    cfg = validate_and_normalize_cfg(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    ass_path = out_dir / f"{stem}.ass"
    mp4_path = out_dir / f"{stem}.mp4"
    frame_path = out_dir / f"{stem}_t1.png"
    ass_path.write_text(make_ass(cfg), encoding="utf-8")

    style = cfg["style"]
    assets = cfg["assets"]
    video = cfg["video"]
    ass_ff = str(ass_path).replace("\\", "/").replace(":", r"\:")
    logo = assets["logo_path"]
    audio = assets["audio_path"]

    cmd = [
        str(FFMPEG), "-y",
        "-f", "lavfi", "-i", f"color=c={video['background']}:s={video['resolution']}:r={video['fps']}:d={video['duration_sec']}",
        "-i", logo,
        "-i", audio,
        "-filter_complex", f"[1:v]scale={style['logo_scale_width']}:-1[lg];[0:v]subtitles='{ass_ff}'[txt];[txt][lg]overlay=W-w-{style['logo_margin_right']}:H-h-{style['logo_margin_bottom']}[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", str(mp4_path),
    ]
    subprocess.run(cmd, check=True)
    cmd2 = [str(FFMPEG), "-y", "-ss", "1", "-i", str(mp4_path), "-frames:v", "1", "-update", "1", str(frame_path)]
    subprocess.run(cmd2, check=True)
    return ass_path, mp4_path, frame_path


def run(cfg_path: Path):
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    ass_path, mp4_path, frame_path = render_cfg(cfg, cfg_path.stem, cfg_path.parent)
    print(ass_path)
    print(mp4_path)
    print(frame_path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path")
    args = ap.parse_args()
    run(Path(args.json_path))
