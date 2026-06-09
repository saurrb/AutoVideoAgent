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
from airflow.utils.dates import days_ago

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AIRFLOW_ROOT = PROJECT_ROOT / "airflow"
if str(AIRFLOW_ROOT) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_ROOT))

from lib.common import build_run_root, build_slot_dir, get_page_airflow_defaults, get_page_airflow_schedule, get_page_runtime, parse_target_requests, send_batch_start, send_batch_summary  # noqa: E402
from lib.flows.page2_daily_desire_facts import page12_prepare_slot, page12_render_slot, page12_telegram_slot, page12_upload_slot  # noqa: E402

PAGE_KEY = "daily_desire_facts"
PAGE_CFG = get_page_runtime(PAGE_KEY)
AIRFLOW_DEFAULTS = get_page_airflow_defaults(PAGE_KEY)
DEFAULT_SLOTS = AIRFLOW_DEFAULTS["posting_slots"]
DEFAULT_TARGET_DAY_OFFSET = AIRFLOW_DEFAULTS["target_day_offset"]
DEFAULT_TIMEZONE = AIRFLOW_DEFAULTS["timezone"]
LOCAL_TZ = pendulum.timezone("Asia/Calcutta")
AIRFLOW_SCHEDULE = get_page_airflow_schedule(PAGE_KEY)


@dag(
    dag_id="page2_daily_desire_facts_manual",
    description="Page 2 daily run with visible per-slot generation, render, upload, and Telegram steps.",
    schedule=AIRFLOW_SCHEDULE,
    start_date=pendulum.datetime(2026, 6, 1, tz=LOCAL_TZ),
    catchup=False,
    max_active_runs=1,
    params={
        "target_dates": Param(
            [],
            type="array",
            title="Target dates",
            description="Dates in YYYY-MM-DD format, for example 2026-06-03. Leave empty to use tomorrow.",
        ),
        "slots": Param(
            [],
            type="array",
            title="Time slots",
            description="24-hour slots in HH:MM format, for example 09:00 or 21:30. Leave empty to use page defaults.",
        ),
    },
    tags=["page2", "daily_desire_facts", "manual"],
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

    prepare_content = task(task_id="prepare_content")(page12_prepare_slot)
    render_video = task(task_id="render_video")(page12_render_slot)
    upload_schedule = task(task_id="upload_schedule")(page12_upload_slot)
    telegram_notify = task(task_id="telegram_notify")(page12_telegram_slot)

    @task(task_id="daily_end_summary", trigger_rule=TriggerRule.ALL_DONE)
    def daily_end_summary(requests: list[dict]):
        run_root = str(requests[0].get("run_root", "")) if requests else ""
        return send_batch_summary(PAGE_KEY, requests, run_root)

    requests = build_requests()
    started_requests = daily_start_message(requests)
    @task_group(group_id="slot_flow")
    def slot_flow(request: dict):
        gated = wait_previous_slot(request)
        prepared = prepare_content(gated)
        rendered = render_video(prepared)
        uploaded = upload_schedule(rendered)
        telegram_notify(uploaded)

    flows = slot_flow.expand(request=started_requests)
    summary = daily_end_summary(started_requests)
    start >> requests >> started_requests >> flows >> summary >> end


dag = build_dag()

