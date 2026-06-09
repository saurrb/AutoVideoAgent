from __future__ import annotations

import sys
from pathlib import Path

import pendulum
from airflow.decorators import dag, task, task_group
from airflow.models.param import Param
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import get_current_context
from airflow.sensors.base import PokeReturnValue
from airflow.utils.trigger_rule import TriggerRule

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AIRFLOW_ROOT = PROJECT_ROOT / "airflow"
if str(AIRFLOW_ROOT) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_ROOT))

from lib.common import (  # noqa: E402
    build_run_root,
    build_slot_dir,
    get_page_airflow_defaults,
    get_page_airflow_schedule,
    get_page_runtime,
    parse_target_requests,
    send_batch_start,
    send_batch_summary,
)
from lib.flows.page5_health_meter import (  # noqa: E402
    page5_build_grok_image_prompt,
    page5_generate_health_concept,
    page5_grok_generate_image,
    page5_render_video,
    page5_speechma_voice,
    page5_telegram_slot,
    page5_upload_slot,
)

PAGE_KEY = "page5_health_meter"
PAGE_CFG = get_page_runtime(PAGE_KEY)
AIRFLOW_DEFAULTS = get_page_airflow_defaults(PAGE_KEY)
DEFAULT_SLOTS = AIRFLOW_DEFAULTS["posting_slots"]
DEFAULT_TARGET_DAY_OFFSET = AIRFLOW_DEFAULTS["target_day_offset"]
DEFAULT_TIMEZONE = AIRFLOW_DEFAULTS["timezone"]
LOCAL_TZ = pendulum.timezone("Asia/Calcutta")
AIRFLOW_SCHEDULE = get_page_airflow_schedule(PAGE_KEY)


@dag(
    dag_id="page5_health_meter_manual",
    description="Page 5 Health Meter run with visible AI concept, Grok image, Speechma voice, render, upload, and Telegram steps.",
    schedule=AIRFLOW_SCHEDULE,
    start_date=pendulum.datetime(2026, 6, 3, tz=LOCAL_TZ),
    catchup=False,
    max_active_runs=1,
    params={
        "target_dates": Param(
            [],
            type="array",
            title="Target dates",
            description="Dates in YYYY-MM-DD format, for example 2026-06-04. Leave empty to use tomorrow.",
        ),
        "slots": Param(
            [],
            type="array",
            title="Time slots",
            description="24-hour slots in HH:MM format, for example 09:00 or 21:30. Leave empty to use page defaults.",
        ),
    },
    tags=["page5", "health_meter", "manual"],
)
def build_dag():
    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")

    @task(task_id="build_date_slot_requests")
    def build_requests(dag_run=None):
        context = get_current_context()
        params = context.get("params", {}) or {}
        conf = (dag_run.conf if dag_run else {}) or {}
        if not conf:
            conf = {
                key: params.get(key)
                for key in ("target_dates", "slots")
                if params.get(key)
            }
        requests = parse_target_requests(PAGE_KEY, conf, DEFAULT_SLOTS, DEFAULT_TARGET_DAY_OFFSET, DEFAULT_TIMEZONE)
        run_root = build_run_root(PAGE_KEY, dag_run.run_id if dag_run else "manual")
        previous_done = ""
        for item in requests:
            item["run_root"] = str(run_root)
            slot_dir = build_slot_dir(run_root, item)
            item["slot_complete_path"] = str(slot_dir / "slot_complete.json")
            item["prev_slot_complete_path"] = previous_done
            previous_done = item["slot_complete_path"]
        return requests

    @task(task_id="daily_start_message")
    def daily_start_message(requests: list[dict]):
        run_root = str(requests[0].get("run_root", "")) if requests else ""
        send_batch_start(PAGE_KEY, requests, run_root)
        return requests

    @task.sensor(task_id="wait_previous_slot", poke_interval=30, timeout=86400, mode="reschedule")
    def wait_previous_slot(request: dict):
        previous_done = str(request.get("prev_slot_complete_path") or "")
        if not previous_done or Path(previous_done).exists():
            return PokeReturnValue(is_done=True, xcom_value=request)
        return PokeReturnValue(is_done=False)

    generate_health_concept = task(task_id="generate_health_concept")(page5_generate_health_concept)
    build_grok_image_prompt = task(task_id="build_grok_image_prompt")(page5_build_grok_image_prompt)
    grok_generate_image = task(task_id="grok_generate_image")(page5_grok_generate_image)
    speechma_voice = task(task_id="speechma_voice")(page5_speechma_voice)
    render_video = task(task_id="render_video")(page5_render_video)
    upload_schedule = task(task_id="upload_schedule")(page5_upload_slot)
    telegram_notify = task(task_id="telegram_notify")(page5_telegram_slot)

    @task(task_id="daily_end_summary", trigger_rule=TriggerRule.ALL_DONE)
    def daily_end_summary(requests: list[dict]):
        run_root = str(requests[0].get("run_root", "")) if requests else ""
        return send_batch_summary(PAGE_KEY, requests, run_root)

    requests = build_requests()
    started_requests = daily_start_message(requests)

    @task_group(group_id="slot_flow")
    def slot_flow(request: dict):
        gated = wait_previous_slot(request)
        concept = generate_health_concept(gated)
        prompt = build_grok_image_prompt(concept)
        image = grok_generate_image(prompt)
        voice = speechma_voice(image)
        rendered = render_video(voice)
        uploaded = upload_schedule(rendered)
        telegram_notify(uploaded)

    flows = slot_flow.expand(request=started_requests)
    summary = daily_end_summary(started_requests)
    start >> requests >> started_requests >> flows >> summary >> end


dag = build_dag()

