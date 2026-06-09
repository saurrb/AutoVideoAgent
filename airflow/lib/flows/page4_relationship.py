from __future__ import annotations

# Page-specific Airflow flow exports. The implementation still lives in
# airflow.lib.page_flows while the codebase is being decomposed safely.
from lib.page_flows import (
    page4_generate_content,
    page4_grok_scene_images,
    page4_render_video,
    page4_speechma_voice,
    page4_telegram_slot,
    page4_upload_slot,
)

__all__ = [
    'page4_generate_content',
    'page4_grok_scene_images',
    'page4_render_video',
    'page4_speechma_voice',
    'page4_telegram_slot',
    'page4_upload_slot',

]

