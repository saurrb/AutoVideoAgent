# Page 4 Relationship

Page key: `page4_relationship`
Page folder: `pages/page4_relationship`

## Active Flow

This page is run through Airflow DAG:

`page4_relationship_manual`

The old Page 4 prototype was removed after the redesigned Airflow flow became active.

## Pipeline

1. `generate_content`: create narration, caption, and hashtags.
2. `speechma_voice`: generate Speechma Pro MP3 voice.
3. `grok_triptych_images`: generate 3-5 landscape triptych images from Grok CLI.
4. `render_panning_reel`: merge all images side by side, pan across the full story strip, and render final 720x1280 reel with narration, 10% background music, captions, and logo.
5. `upload_schedule`: upload/schedule through Meta Business UI.
6. `telegram_notify`: send success/failure update.

## Shared Tools

Page 4 uses shared tools from:

`C:\Users\Saurabh\Documents\AutoVideoAgent\pages\automation_tools`

Important tools:

- `speechma/speechma_run.ps1`
- `grok_image_cli/grok_cli_scene_images_generate.py`
- `meta_ui_schedule/upload_schedule_ui.py`

## Outputs

Airflow run outputs are written under:

`C:\Users\Saurabh\Documents\AutoVideoAgent\runs\airflow_ui\page4_relationship\...`

## Manual Airflow Trigger Example

```json
{
  "target_dates": ["2026-06-04"],
  "slots": ["09:00", "12:00"]
}
```
