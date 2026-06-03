#!/usr/bin/env bash
set -euo pipefail

cd /mnt/c/Users/Saurabh/Documents/AutoVideoAgent
source airflow/wsl/airflow_env.sh

for name in scheduler webserver; do
  pid_file="$AIRFLOW_ROOT/pids/${name}.pid"
  if [ -f "$pid_file" ]; then
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "[airflow-wsl] stopped $name pid $pid"
    fi
    rm -f "$pid_file"
  fi
done
