# Daily Desire Facts Page Workspace

Page key: `daily_desire_facts`
Page folder: `pages/page2_daily_desire_facts`

## Active Flow

This page is run through Airflow DAG:

`page2_daily_desire_facts_manual`

The DAG uses:

- content DB rows loaded from `content/reel_content_bank.xlsx`
- random generated background images from `assets/backgrounds/generated`
- page logo from `assets/logo/logo1.png`
- page music from `assets/music`
- Meta Business UI scheduling through `pages/automation_tools/meta_ui_schedule`

## Content Reload

After editing the Excel content bank, run:

```cmd
python C:\Users\Saurabh\Documents\AutoVideoAgent\pages\page2_daily_desire_facts\content\reload_to_db.py
```

## Manual Airflow Trigger Example

```json
{
  "target_dates": ["2026-06-04"],
  "slots": ["13:00", "17:00"]
}
```
