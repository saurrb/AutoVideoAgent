# Page 4 Pipeline Design

## Goals

- Keep Page 4 isolated from Page 1, Page 2, and Page 3 rendering assumptions.
- Use deterministic stage artifacts inside each Airflow slot folder.
- Reuse shared automation tools for Speechma, Grok image generation, and Meta UI scheduling.
- Keep narration, image generation, panning render, caption timing, and upload visible as Airflow tasks.

## Current Airflow Flow

DAG:

- `airflow/dags/page4_relationship_manual.py`

Flow exports:

- `airflow/lib/flows/page4_relationship.py`

Current implementation source:

- `airflow/lib/page_flows.py`

Visible task sequence:

- `generate_content`
- `speechma_voice`
- `grok_triptych_images`
- `render_panning_reel`
- `upload_schedule`
- `telegram_notify`

## Tools Used

- `pages/automation_tools/speechma/speechma_run.ps1`
- `pages/automation_tools/grok_image_cli/grok_cli_scene_images_generate.py`
- `pages/page4_relationship/scripts/render_page4_singlepass.py`
- `pages/automation_tools/meta_ui_schedule/upload_schedule_ui.py`

## Contracts

Each slot writes stage JSON files under:

- `runs/airflow_ui/page4_relationship/<dag_run_id>/<yyyy-mm-dd>/<hhmm>/`

Important artifacts include:

- `01_generate_content.json`
- `02_speechma_voice.json`
- `03_grok_scene_images.json`
- `04_render_panning_reel.json`
- `05_upload.json`
- `06_telegram.json`

## Assets

- Logo: `assets/logo/logo1.png`
- Music: `assets/music/`
- Voice profile: `content/voice_profile.json`

## Recovery

If a slot fails, inspect that slot folder in `runs/airflow_ui/page4_relationship/...` and the matching Airflow task log.
