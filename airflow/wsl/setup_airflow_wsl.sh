#!/usr/bin/env bash
set -euo pipefail

cd /mnt/c/Users/Saurabh/Documents/AutoVideoAgent
source airflow/wsl/airflow_env.sh

if command -v curl >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  echo "[airflow-wsl] Linux prerequisites already present"
else
  echo "[airflow-wsl] installing Linux packages"
  sudo apt-get update
  sudo apt-get install -y curl python3 python3-venv python3-pip python3-dev build-essential libsqlite3-dev
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "[airflow-wsl] installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

echo "[airflow-wsl] preparing Python 3.12 venv at $AIRFLOW_VENV"
uv python install 3.12
if [ ! -x "$AIRFLOW_VENV/bin/python" ]; then
  uv venv --python 3.12 "$AIRFLOW_VENV"
fi

source "$AIRFLOW_VENV/bin/activate"
python -m ensurepip --upgrade
python -m pip install --upgrade pip setuptools wheel

PYVER="$(python - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
CONSTRAINT="https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-${PYVER}.txt"

echo "[airflow-wsl] installing Airflow 2.10.5 for Python $PYVER"
python -m pip install "apache-airflow==2.10.5" --constraint "$CONSTRAINT"
python -m pip install openpyxl playwright requests pyyaml

airflow db migrate
airflow users create \
  --username admin \
  --firstname Saurabh \
  --lastname User \
  --role Admin \
  --email admin@local.dev \
  --password admin || true

airflow dags list-import-errors
airflow dags list | grep -E "page[1-4]_.*_manual|dag_id" || true

echo "[airflow-wsl] setup complete"
echo "[airflow-wsl] start with: C:\\Users\\Saurabh\\Documents\\AutoVideoAgent\\airflow\\start_airflow_wsl.cmd"
