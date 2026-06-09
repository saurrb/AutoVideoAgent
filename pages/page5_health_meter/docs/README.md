# Page5 Health Meter

Page key: `page5_health_meter`

Facebook asset id: `1142661428928770`

Airflow DAG: `page5_health_meter_manual`

## Workflow

1. Generate one AI health concept with Grok text JSON.
2. Build one premium Grok image prompt.
3. Generate one Grok health infographic image only.
4. Derive narration from the same concept.
5. Generate Speechma Pro voice with Ava, pitch `0`, speed `0`, volume `190`.
6. Render final static 720x1280 reel with Page 5 logo, Speechma voice, and background music at 10% of narration volume.
7. Upload/schedule through Meta Business UI.
8. Send Telegram success/failure message.

## Manual Airflow Trigger

Use DAG config:

```json
{
  "target_dates": ["2026-06-04"],
  "slots": ["08:00", "11:00"]
}
```

If empty, the DAG uses next day and the default slots from:

`C:\Users\Saurabh\Documents\AutoVideoAgent\control\airflow_schedule_control.json`

## Creative Rules

- Image-first reels; Grok generates the poster image only.
- Reel duration follows the generated Speechma narration voice.
- No fallback if Grok image generation or Speechma fails.
- Clean white/cream health infographic style.
- Grok writes the final heading, five points, and one question inside the image.
- The lower-right area should stay visually uncluttered; the renderer adds the Page 5 logo there.
- Logo source: `pages/page5_health_meter/assets/logo/logo1.png`.
- Background music source: `pages/page5_health_meter/assets/music_reference/paulyudin-breaking-news-113982.mp3`.
- Background music volume: `10%` relative to narration voice.
- Aggressive curiosity wording is allowed, but no cure/treatment guarantees.

## Safe Aggressive Wording

Use:

- `may support`
- `can help support`
- `your body may need`
- `stop ignoring`
- `quietly affects`

Avoid:

- `cures`
- `reverses disease`
- `heals kidney damage`
- `prevents cancer`
- `doctor secret`
- `miracle`
- `replace medicine`
