from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContentPoint:
    text: str
    highlight_first_words: int
    source_item_id: int


@dataclass
class ReelSpec:
    page_key: str
    duration_sec: int
    resolution: str
    fps: int
    background_color: str
    heading_line1: str
    heading_line2: str
    points: list[ContentPoint]
    cta: str
    font: str
    title_font_size: int
    body_font_size: int
    cta_font_size: int
    highlight_color_ass: str
    text_color_ass: str
    outline_color_ass: str
    header_margin_v: int
    body_margin_v: int
    body_margin_l: int
    body_margin_r: int
    point_gap_scale: float
    cta_pos_x: int
    cta_pos_y: int
    logo_path: str
    logo_scale_width: int
    logo_margin_right: int
    logo_margin_bottom: int
    audio_path: str
