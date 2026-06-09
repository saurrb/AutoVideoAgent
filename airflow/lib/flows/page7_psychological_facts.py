from __future__ import annotations

# Page-specific Airflow flow exports. The implementation still lives in
# airflow.lib.page_flows while the codebase is being decomposed safely.
from lib.page_flows import (
    page7_generate_fact_content,
    page7_render_video,
    page7_telegram_slot,
    page7_upload_slot,
)

__all__ = [
    "page7_generate_fact_content",
    "page7_render_video",
    "page7_telegram_slot",
    "page7_upload_slot",
]
