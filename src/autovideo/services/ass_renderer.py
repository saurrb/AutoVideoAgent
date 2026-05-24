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


def build_ass(template_path: Path, spec: ReelSpec) -> str:
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
