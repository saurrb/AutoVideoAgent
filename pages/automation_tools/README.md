# Automation Tools

Shared automation tools for Page 4 and future pages.

## Modules
- `speechma/` : text-to-voice automation
- `grok_video_cli/` : Grok CLI video scene generation (primary)
- `grok_image_cli/` : Grok CLI image generation
- `grok_video_ui_extension/` : BrowserOS extension-based UI automation (manual mode)

## Page 4 usage
- Page 4 now uses direct script invocations from:
  - `speechma/speechma_run.ps1`
  - `grok_video_cli/grok_cli_scene_generate.py`
- No CLI->UI fallback is used in Page 4 pipeline.

Open each module README for copy-paste local CMD commands.
