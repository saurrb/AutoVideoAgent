#!/usr/bin/env bash
set -euo pipefail

cd /mnt/c/Users/Saurabh/Documents/AutoVideoAgent
source airflow/wsl/airflow_env.sh

if [ ! -x "$AIRFLOW_VENV/bin/airflow" ]; then
  echo "[airflow-wsl] missing $AIRFLOW_VENV. Run airflow/setup_airflow_wsl.cmd first."
  exit 1
fi

source "$AIRFLOW_VENV/bin/activate"
mkdir -p "$AIRFLOW_ROOT/runtime_logs" "$AIRFLOW_ROOT/pids"

if [ -f "$AIRFLOW_ROOT/pids/webserver.pid" ] && kill -0 "$(cat "$AIRFLOW_ROOT/pids/webserver.pid")" 2>/dev/null; then
  echo "[airflow-wsl] webserver already running"
else
  nohup airflow webserver --port 8080 > "$AIRFLOW_ROOT/runtime_logs/wsl_webserver.out.log" 2> "$AIRFLOW_ROOT/runtime_logs/wsl_webserver.err.log" &
  echo $! > "$AIRFLOW_ROOT/pids/webserver.pid"
  echo "[airflow-wsl] webserver pid $(cat "$AIRFLOW_ROOT/pids/webserver.pid")"
fi

if [ -f "$AIRFLOW_ROOT/pids/scheduler.pid" ] && kill -0 "$(cat "$AIRFLOW_ROOT/pids/scheduler.pid")" 2>/dev/null; then
  echo "[airflow-wsl] scheduler already running"
else
  nohup airflow scheduler > "$AIRFLOW_ROOT/runtime_logs/wsl_scheduler.out.log" 2> "$AIRFLOW_ROOT/runtime_logs/wsl_scheduler.err.log" &
  echo $! > "$AIRFLOW_ROOT/pids/scheduler.pid"
  echo "[airflow-wsl] scheduler pid $(cat "$AIRFLOW_ROOT/pids/scheduler.pid")"
fi

echo "[airflow-wsl] UI: http://127.0.0.1:8080"
