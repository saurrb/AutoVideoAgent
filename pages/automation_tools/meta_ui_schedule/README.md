# Meta UI Upload/Schedule Tool

This tool uploads one reel and schedules it through Meta Business UI (BrowserOS/CDP), using the same proven scheduler flow as pages 1/2/3.

## Sample command

```powershell
python "C:\Users\Saurabh\Documents\AutoVideoAgent\pages\automation_tools\meta_ui_schedule\upload_schedule_ui.py" `
  --page-key page4_relationship `
  --asset-id 1157132894144257 `
  --video "C:\Users\Saurabh\Documents\AutoVideoAgent\runs\2026-06-01\page4_relationship\20260601_140252\page4_140711_final_singlepass_720x1280.mp4" `
  --caption "Your caption text here`n`n#tag1 #tag2 #tag3" `
  --when 2026-06-01T17:00
```

Use `--caption` for direct text input.  
Screenshots are saved under:

`C:\Users\Saurabh\Documents\AutoVideoAgent\runs\manual_ui_schedule\...`
