# AutoVideoAgent Airflow UI

This folder contains the local Airflow workspace for `AutoVideoAgent`.

Recommended runtime: WSL2 Ubuntu. The Windows UI-only setup remains here for reference, but WSL2 is the intended path because Airflow's scheduler runs reliably on Linux.

## DAGs

- `page1_female_psychology_manual`
- `page2_daily_desire_facts_manual`
- `page3_dragon_cinema_manual`
- `page4_relationship_manual`

Each DAG is one Facebook page. Each manual trigger expands into one mapped task chain per requested date/slot.

## Trigger Input

Use this JSON shape in Airflow's `Trigger DAG w/ config` box:

```json
{
  "target_dates": ["2026-06-03"],
  "slots": ["10:30", "12:30"]
}
```

You can pass multiple dates and multiple slots:

```json
{
  "target_dates": ["2026-06-03", "2026-06-04"],
  "slots": ["09:00", "12:00", "21:00"]
}
```

If either field is omitted, the DAG uses tomorrow's date and that page's default slots from:

`C:\Users\Saurabh\Documents\AutoVideoAgent\control\automation_runtime.json`

## Visible Steps

Page 1 and Page 2:

- `build_date_slot_requests`
- `prepare_content`
- `render_video`
- `upload_schedule`
- `telegram_notify`

Page 3:

- `build_date_slot_requests`
- `pick_content`
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

## WSL2 Setup

Install WSL2 + Ubuntu from an Administrator terminal:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\install_wsl_ubuntu_admin.cmd
```

After Ubuntu completes first-time setup, install Airflow inside WSL:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\setup_airflow_wsl.cmd
```

Start the WSL-backed Airflow webserver and scheduler:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\start_airflow_wsl.cmd
```

Stop the WSL-backed Airflow processes:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\stop_airflow_wsl.cmd
```

The UI still opens from Windows:

`http://127.0.0.1:8080`

Default login:

`admin / admin`

## Windows UI Fallback

Initialize:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\init_airflow_page4.cmd
```

Start Windows UI only:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\start_airflow_page4.cmd
```

Open UI:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\open_airflow_ui.cmd
```

Stop UI:

```cmd
C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\stop_airflow_page4.cmd
```

## Outputs

Airflow UI runs write per-slot artifacts under:

`C:\Users\Saurabh\Documents\AutoVideoAgent\runs\airflow_ui\<page_key>\<dag_run_id>\...`

Each slot folder contains stage JSON files such as `01_prepare.json`, `02_render.json`, `03_upload.json`, or the page-specific equivalents.
