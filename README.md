# AutoVideoAgent

Airflow-driven local automation for creating and scheduling Facebook/Instagram reels across six pages.

Production orchestration lives in Airflow. Legacy Windows Task Scheduler commands, Graph API posting commands, and standalone daily batch scripts are no longer the primary path.

## Active Pages

| Page | DAG | Folder | Default Run | Default Scheduled Slots |
| --- | --- | --- | --- | --- |
| Page 1 Female Psychology | `page1_female_psychology_manual` | `pages/page1_female_psychology` | 01:00 | `10:30, 12:30, 14:30, 16:30, 18:30, 20:30, 22:30` |
| Page 2 Daily Desire Facts | `page2_daily_desire_facts_manual` | `pages/page2_daily_desire_facts` | 02:00 | `10:30, 12:30, 14:30, 16:30, 18:30, 20:30, 22:30` |
| Page 3 Dragon Cinema | `page3_dragon_cinema_manual` | `pages/page3_dragon_cinema` | 03:00 | `09:00, 11:00, 13:00, 15:00, 17:00, 19:00, 21:00, 23:00` |
| Page 4 Relationship | `page4_relationship_manual` | `pages/page4_relationship` | 05:00 | `09:00, 12:00, 15:00, 18:00, 21:00` |
| Page 5 Health Meter | `page5_health_meter_manual` | `pages/page5_health_meter` | 04:00 | `08:00, 11:00, 14:00, 17:00, 20:00, 23:00` |
| Page 6 The Dark Theory | `page6_the_dark_theory_manual` | `pages/page6_the_dark_theory` | 06:00 | `09:30, 12:30, 15:30, 18:30, 21:30` |

Daily scheduled DAG runs target the next day by default.

## Start Airflow

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\start_airflow_wsl.cmd
```

Open the UI:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\open_airflow_ui.cmd
```

Default local login:

```text
admin / admin
```

Stop Airflow:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\stop_airflow_wsl.cmd
```

## Manual Airflow Trigger

Use Airflow's trigger config with this JSON:

```json
{
  "target_dates": ["2026-06-04"],
  "slots": ["10:30", "12:30"]
}
```

Multiple dates and multiple slots are supported:

```json
{
  "target_dates": ["2026-06-04", "2026-06-05"],
  "slots": ["09:00", "12:00", "21:00"]
}
```

If `target_dates` or `slots` are omitted, the DAG uses defaults from `control/airflow_schedule_control.json`.

## Current Runtime Model

- Airflow creates one visible task chain per requested slot.
- Each slot is gated so slots run sequentially inside a DAG run.
- A failed slot sends Telegram failure details and does not block the remaining slots.
- Meta upload/scheduling uses the browser UI helper, not Graph API posting.
- Runtime state is centralized in `data/v2/state.sqlite3`.
- Generated outputs are written under `runs/airflow_ui/...` and ignored by git.

## Important Folders

- `airflow/dags`: all page DAGs.
- `airflow/lib`: shared Airflow helpers and flow exports.
- `airflow/lib/flows`: page-specific Airflow flow import boundaries.
- `pages/page1_female_psychology`: Page 1 content/assets.
- `pages/page2_daily_desire_facts`: Page 2 content/assets.
- `pages/page3_dragon_cinema`: Page 3 content/assets.
- `pages/page4_relationship`: Page 4 content/assets/render scripts.
- `pages/page5_health_meter`: Page 5 content/assets/render scripts.
- `pages/page6_the_dark_theory`: Page 6 content/assets.
- `pages/automation_tools`: shared Speechma, Grok, and Meta UI tools.
- `pages/page3_dragon_cinema/scripts`: Page 3 subprocess scripts.
- `scripts/maintenance`: cleanup/log/Telegram utility scripts.
- `scripts/db`: database reload helpers.
- `scripts/templates`: shared render templates.
- `src/autovideo`: shared renderer, content, DB, caption, and config services.
- `src/autovideo/services/text_utils.py`: centralized mojibake repair and text/JSON cleanup.
- `src/autovideo/services/grok_cli.py`: centralized Grok CLI resolution and limit/credit detection.
- `control`: runtime and Airflow schedule control JSON.
- `configs/pages`: page render/content configuration.
- `tools/ffmpeg`: bundled FFmpeg/FFprobe used by renderers.
- `archive`: old experiments and legacy files, ignored by git.

## Reload Content From Excel

Each Excel-driven page content folder has a `reload_to_db.py` helper. Run it after editing that page's Excel file.

Example:

```cmd
python C:\Users\Saurabh\Documents\AutoVideoAgent\pages\page1_female_psychology\content\reload_to_db.py
```

## Stop Page Processes

For emergency cleanup of active page-related processes:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\pages\stopAll\stop_all_pages.cmd
```

