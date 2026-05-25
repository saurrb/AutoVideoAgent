from __future__ import annotations

import textwrap
from pathlib import Path

from autovideo.domain.reel_spec import ReelSpec


def _ass_escape(s: str) -> str:
    return s.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _ass_time_from_seconds(seconds: int) -> str:
    total_cs = max(0, int(round(float(seconds) * 100)))
    hh = total_cs // 360000
    rem = total_cs % 360000
    mm = rem // 6000
    rem = rem % 6000
    ss = rem // 100
    cs = rem % 100
    return f"{hh}:{mm:02d}:{ss:02d}.{cs:02d}"


def _wrap_line(text: str, width: int = 44) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)


def _build_point_line(text: str, n_highlight: int) -> str:
    words = text.split()
    n = max(1, min(n_highlight, len(words)))
    first = " ".join(words[:n])
    rest = " ".join(words[n:])
    base = r"{\rBodyOrange}" + _ass_escape(first) + r"{\rBodyWhite}"
    if rest:
        base += " " + _ass_escape(rest)
    return base


def _build_daily_desire_fact_ass(spec: ReelSpec) -> str:
    end_time = _ass_time_from_seconds(spec.duration_sec)
    badge_text = _ass_escape(spec.heading_line2 or "DESIRE FACT")
    raw = spec.points[0].text.strip() if spec.points else ""

    def _split_hook_answer(text: str) -> tuple[str, str]:
        if "||" in text:
            hook, answer = text.split("||", 1)
            return hook.strip(), answer.strip()
        lowered = text.lower()
        for marker in [" because ", " when ", " so ", " but "]:
            pos = lowered.find(marker)
            if pos > 0:
                hook = text[: pos + len(marker)].strip()
                answer = text[pos + len(marker) :].strip()
                return hook, answer
        words = text.split()
        if len(words) > 7:
            return " ".join(words[:7]).strip(), " ".join(words[7:]).strip()
        return text.strip(), text.strip()

    hook, answer = _split_hook_answer(raw)
    hook = hook.rstrip(".!?")
    if not hook.endswith("..."):
        hook += "..."
    if not answer:
        answer = raw

    body1 = r"\N".join(_wrap_line(_ass_escape(hook), width=24))
    body2 = r"\N".join(_wrap_line(_ass_escape(answer), width=24))

    hook_end = 6.0
    reveal_start = 6.8
    reveal_end = min(float(spec.duration_sec), reveal_start + 3.2)
    card_events = [
        ("0:00:00.00", _ass_time_from_seconds(hook_end), body1),
        (_ass_time_from_seconds(reveal_start), _ass_time_from_seconds(reveal_end), body2),
    ]
    card_font_size = max(56, int(round(float(spec.body_font_size) * 1.35)))

    lines = [
        "[Script Info]",
        "Title: Daily Desire Facts Style",
        "ScriptType: v4.00+",
        "PlayResX: 696",
        "PlayResY: 1280",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        f"Style: Badge,{spec.font},{card_font_size},&H00FFFFFF,&H000000FF,&H00000000,&H90000000,1,0,0,0,100,100,0,0,3,0,0,8,0,0,92,1",
        f"Style: Card,{spec.font},{card_font_size},&H00FFFFFF,&H000000FF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,3,0,0,5,112,112,0,1",
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
        f"Dialogue: 2,0:00:00.00,{end_time},Badge,,0,0,0,,{badge_text}",
    ]
    for start, end, txt in card_events:
        if txt:
            lines.append(f"Dialogue: 1,{start},{end},Card,,0,0,0,,{txt}")
    return "\n".join(lines) + "\n"


def build_ass(template_path: Path, spec: ReelSpec) -> str:
    if spec.page_key == "daily_desire_facts":
        return _build_daily_desire_fact_ass(spec)

    heading = r"\N".join([_ass_escape(spec.heading_line1), _ass_escape(spec.heading_line2)])
    end_time = _ass_time_from_seconds(spec.duration_sec)

    body_parts: list[str] = []
    for i, point in enumerate(spec.points, start=1):
        line = _build_point_line(point.text, point.highlight_first_words)
        body_parts.append(f"{i}. " + line)
    extra_gap_ratio = max(0.0, spec.point_gap_scale - 1.0)
    spacer_font_size = max(1, round(spec.body_font_size * extra_gap_ratio))
    point_separator = r"\N" + r"{\fs" + str(spacer_font_size) + r"} {\rBodyWhite}" + r"\N"
    body_text = point_separator.join(body_parts)

    cta_words = _ass_escape(spec.cta).split()
    cta_high = " ".join(cta_words[:2])
    cta_rest = " ".join(cta_words[2:])
    cta_full = cta_high + (" " + cta_rest if cta_rest else "")
    cta_wrapped = _wrap_line(cta_full, width=44)
    cta_text = ""
    for idx, ln in enumerate(cta_wrapped):
        if idx == 0:
            parts = ln.split()
            hi = " ".join(parts[:2])
            rem = " ".join(parts[2:])
            cta_text += r"{\rCTAOrange}" + hi + r"{\rCTA}" + (" " + rem if rem else "")
        else:
            cta_text += r"\N" + ln

    template = template_path.read_text(encoding="utf-8")
    return template.format(
        font=spec.font,
        title_font_size=spec.title_font_size,
        body_font_size=spec.body_font_size,
        cta_font_size=spec.cta_font_size,
        highlight_color_ass=spec.highlight_color_ass,
        text_color_ass=spec.text_color_ass,
        outline_color_ass=spec.outline_color_ass,
        header_margin_v=spec.header_margin_v,
        body_margin_v=spec.body_margin_v,
        body_margin_l=spec.body_margin_l,
        body_margin_r=spec.body_margin_r,
        cta_x=spec.cta_pos_x,
        cta_y=spec.cta_pos_y,
        end_time=end_time,
        heading=heading,
        body_text=body_text,
        cta_text=cta_text,
    )
