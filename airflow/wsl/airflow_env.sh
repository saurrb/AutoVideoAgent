#!/usr/bin/env bash
set -euo pipefail

export PROJECT_ROOT="/mnt/c/Users/Saurabh/Documents/AutoVideoAgent"
export AIRFLOW_ROOT="$PROJECT_ROOT/airflow"
export AIRFLOW_HOME="$HOME/.autovideo_airflow_home"
export AIRFLOW_VENV="$HOME/.autovideo_airflow_venv"
export AIRFLOW__CORE__DAGS_FOLDER="$AIRFLOW_ROOT/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES="False"
export AIRFLOW__CORE__DEFAULT_TIMEZONE="Asia/Calcutta"
export AIRFLOW__CORE__EXECUTOR="SequentialExecutor"
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="sqlite:///$AIRFLOW_HOME/airflow.db"
export PYTHONPATH="$AIRFLOW_ROOT:$PROJECT_ROOT/src:$PROJECT_ROOT"
export PYTHONUTF8=1

mkdir -p "$AIRFLOW_HOME" "$AIRFLOW_ROOT/runtime_logs"
