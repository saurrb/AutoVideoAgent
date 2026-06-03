# Grok Video CLI Tool

## What it does
Generates scene videos from blank-line-separated scene prompts using Grok CLI only.
No UI fallback.

## Copy-paste command (CMD)
```bat
python "C:\Users\Saurabh\Documents\AutoVideoAgent\pages\automation_tools\grok_video_cli\grok_cli_scene_generate.py" --prompt-file "C:\path\scene_prompts.txt" --output-dir "C:\path\grok_outputs"
```

## Notes
- Target per scene: 6s, 480p, 9:16
- Writes `grok_outputs.done.json` in output folder
