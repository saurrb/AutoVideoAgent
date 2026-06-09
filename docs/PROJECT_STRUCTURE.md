# Project Structure

AutoVideoAgent is organized around Airflow as the production runner.

## Orchestration

- `airflow/dags/`: one DAG per page.
- `airflow/lib/common.py`: schedule parsing, runtime config, Telegram notifications, Meta UI upload wrapper.
- `airflow/lib/page_flows.py`: shared implementation currently used by page flow exports.
- `airflow/lib/flows/`: page-specific flow import boundaries used by DAGs.
- `airflow/wsl/`: WSL Airflow setup/start/stop scripts.
- `control/airflow_schedule_control.json`: daily DAG run schedules, target-day offset, default slots.
- `control/automation_runtime.json`: page asset IDs, page keys, and runtime metadata.

## Shared Code

- `src/autovideo/app/cli.py`: render CLI for Page 1 and Page 2 style reels.
- `src/autovideo/services/video_renderer.py`: shared FFmpeg/Pillow render service.
- `src/autovideo/services/caption_builder.py`: caption and hashtag builder used by Airflow.
- `src/autovideo/services/content_provider.py`: DB/Excel content loading.
- `src/autovideo/services/text_utils.py`: shared mojibake repair, text normalization, JSON extraction, and list cleanup.
- `src/autovideo/services/grok_cli.py`: shared Grok CLI path resolution, text execution, and limit/credit error detection.
- `src/autovideo/services/state_store.py`: SQLite schema and state helpers.
- `src/autovideo/services/telegram_notify.py`: Telegram message formatting and delivery.

## Per-Page Workspaces

- `pages/page1_female_psychology/`: Page 1 content, logo, music, backgrounds, docs.
- `pages/page2_daily_desire_facts/`: Page 2 content, logo, music, generated backgrounds, docs.
- `pages/page3_dragon_cinema/`: Page 3 Dragon content, logo, docs.
- `pages/page4_relationship/`: Page 4 narration, Speechma/Grok/render assets and scripts.
- `pages/page5_health_meter/`: Page 5 Health Meter assets, docs, and render scripts.
- `pages/page6_the_dark_theory/`: Page 6 Dark Theory logo, music, and docs.

## Shared Automation Tools

- `pages/automation_tools/speechma/`: Speechma Pro voice generation.
- `pages/automation_tools/grok_image_cli/`: Grok image generation helper.
- `pages/automation_tools/grok_video_cli/`: Grok video CLI helper.
- `pages/automation_tools/grok_video_ui_extension/`: Grok extension automation helper.
- `pages/automation_tools/meta_ui_schedule/`: Meta Business UI upload and schedule helper.

## Utility Scripts

- `pages/page3_dragon_cinema/scripts/`: Page 3 Grok video generation and final render subprocesses.
- `scripts/maintenance/`: stale-process cleanup, live event tailing, Telegram chat-id helper.
- `scripts/db/`: Excel-to-SQLite reload helper.
- `scripts/templates/`: shared ASS subtitle template.
- `scripts/legacy/`: retained legacy helpers that are not the primary Airflow path.

## Runtime Data

- `data/v2/state.sqlite3`: canonical SQLite state DB for Excel/DB-backed pages.
- `runs/`: generated reels, manifests, logs, screenshots, and Airflow run artifacts. Ignored by git.
- `airflow/runtime_logs/`: WSL Airflow logs. Ignored by git.
- `airflow/pids/`: WSL Airflow process IDs. Ignored by git.
- `archive/`: old experiments and legacy files. Ignored by git.

## Configs

- `configs/global.yaml`: shared render defaults.
- `configs/pages/page1_female_psychology.yaml`: Page 1 render/content config.
- `configs/pages/page2_daily_desire_facts.yaml`: Page 2 render/content config.
- `configs/pages/page3_dragon_cinema.yaml`: Page 3 render/content config.
- `configs/pages/page4_relationship.yaml`: Page 4 render/content config.

Legacy runtime page keys are still supported by `src/autovideo/services/config_loader.py`:

- `female_psychology` -> `page1_female_psychology.yaml`
- `daily_desire_facts` -> `page2_daily_desire_facts.yaml`
- `dragon_cinema` -> `page3_dragon_cinema.yaml`

## Removed or Archived Legacy Paths

Old Windows Task Scheduler scripts, Graph API posting commands, root `.venv`, Windows Airflow shims, root test prompts, and one-off generated assets are either removed or archived under `archive/`.

