# Page 4 Pipeline Design

## Goals
- Keep page 1/2/3 untouched
- Isolate page 4 runtime into deterministic stage artifacts
- Reuse shared automation tools
- Preserve existing scheduler integration

## Flow
- `scripts/generate_page4_reel.py` (global wrapper)
  -> `pages/page4_relationship/scripts/page4_pipeline.py`
  -> `prepare_page4_narration_and_scenes.py`
  -> `automation_tools/grok_image_cli/grok_cli_scene_images_generate.py`
  -> `scripts/render_page4_singlepass.py`

## Contracts
- Standard stdout keys:
  - `MANIFEST=...`
  - `VIDEO=...`
- Run folder is always under:
  - `runs/<yyyy-mm-dd>/page4_relationship/<yyyymmdd_hhmmss>/`
- Stage markers under `state/` directory.

## Assets
- Logo: `assets/logo/logo1.png`
- Voice profile: `content/voice_profile.json`

## Recovery
- If pipeline fails, inspect latest run:
  - `state/*.json`
  - `page4_prepare_*.manifest.json`
  - `page4_*.manifest.json`
