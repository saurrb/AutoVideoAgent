from __future__ import annotations

# Page-specific Airflow flow exports. The implementation still lives in
# airflow.lib.page_flows while the codebase is being decomposed safely.
from lib.page_flows import (
    page3_final_render,
    page3_generate_dragon_package,
    page3_scene_a,
    page3_scene_b,
    page3_telegram_slot,
    page3_upload_slot,
)

__all__ = [
    'page3_final_render',
    'page3_generate_dragon_package',
    'page3_scene_a',
    'page3_scene_b',
    'page3_telegram_slot',
    'page3_upload_slot',

]

