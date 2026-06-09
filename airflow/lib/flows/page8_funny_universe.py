from __future__ import annotations

# Page-specific Airflow flow exports. The implementation still lives in
# airflow.lib.page_flows while the codebase is being decomposed safely.
from lib.page_flows import (
    page8_generate_comic_content,
    page8_grok_animated_video,
    page8_render_video,
    page8_telegram_slot,
    page8_upload_slot,
)

__all__ = [
    "page8_generate_comic_content",
    "page8_grok_animated_video",
    "page8_render_video",
    "page8_telegram_slot",
    "page8_upload_slot",
]
