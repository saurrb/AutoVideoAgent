from __future__ import annotations

# Page-specific Airflow flow exports. The implementation still lives in
# airflow.lib.page_flows while the codebase is being decomposed safely.
from lib.page_flows import (
    page12_prepare_slot,
    page12_render_slot,
    page12_upload_slot,
    page12_telegram_slot,
)

__all__ = [
    'page12_prepare_slot',
    'page12_render_slot',
    'page12_upload_slot',
    'page12_telegram_slot',

]

