# AutoVideoAgent Airflow UI

This folder contains the WSL-backed Airflow workspace for `AutoVideoAgent`.

Airflow is now the production orchestrator for all six pages. The previous Windows-native Airflow experiment and Page 4-only launchers have been removed.

## DAGs

- `page1_female_psychology_manual`
- `page2_daily_desire_facts_manual`
- `page3_dragon_cinema_manual`
- `page4_relationship_manual`
- `page5_health_meter_manual`
- `page6_the_dark_theory_manual`

Each DAG is one Facebook page. Each trigger expands into one mapped task chain per requested date/slot.

## Trigger Input

Use this JSON in Airflow's `Trigger DAG w/ config` box:

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

If either field is omitted, the DAG uses its defaults from:

`C:\Users\Saurabh\Documents\AutoVideoAgent\control\airflow_schedule_control.json`

## Visible Steps

Page 1 and Page 2:

- `build_date_slot_requests`
- `prepare_content`
- `render_video`
- `upload_schedule`
- `telegram_notify`

Page 3:

- `build_date_slot_requests`
- `generate_dragon_package`
- `scene_a_generate`
- `scene_b_generate`
- `final_render`
- `upload_schedule`
- `telegram_notify`

Page 4:

- `build_date_slot_requests`
- `generate_content`
- `speechma_voice`
- `grok_scene_images`
- `render_video`
- `upload_schedule`
- `telegram_notify`

Page 5:

- `build_date_slot_requests`
- `generate_health_concept`
- `build_grok_image_prompt`
- `grok_generate_image`
- `speechma_voice`
- `render_video`
- `upload_schedule`
- `telegram_notify`

Page 6:

- `build_date_slot_requests`
- `generate_content`
- `speechma_voice`
- `grok_scene_images`
- `render_video`
- `upload_schedule`
- `telegram_notify`

## WSL2 Setup

Install WSL2 + Ubuntu from an Administrator terminal:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\install_wsl_ubuntu_admin.cmd
```

After Ubuntu completes first-time setup, install Airflow inside WSL:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\setup_airflow_wsl.cmd
```

Start Airflow:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\start_airflow_wsl.cmd
```

Open UI:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\open_airflow_ui.cmd
```

Stop Airflow:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\stop_airflow_wsl.cmd
```

UI:

`http://127.0.0.1:8080`

Default login:

`admin / admin`

## Outputs

Airflow UI runs write per-slot artifacts under:

`C:\Users\Saurabh\Documents\AutoVideoAgent\runs\airflow_ui\<page_key>\<dag_run_id>\...`

Each slot folder contains stage JSON files such as `01_prepare.json`, `02_render.json`, `03_upload.json`, or the page-specific equivalents.
