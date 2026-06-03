@echo off
setlocal

set "ROOT=C:\Users\Saurabh\Documents\AutoVideoAgent"
set "AIRFLOW_ROOT=%ROOT%\airflow"
set "AIRFLOW_HOME=%AIRFLOW_ROOT%\home"
set "VENV=%AIRFLOW_ROOT%\.venv"
set "PYTHONUTF8=1"
set "AIRFLOW__CORE__DAGS_FOLDER=%AIRFLOW_ROOT%\dags"
set "AIRFLOW__CORE__LOAD_EXAMPLES=False"
set "AIRFLOW__CORE__DEFAULT_TIMEZONE=Asia/Calcutta"
set "AIRFLOW__CORE__EXECUTOR=SequentialExecutor"
set "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=sqlite:///%AIRFLOW_HOME:\=/%/airflow.db"
set "PYTHONPATH=%AIRFLOW_ROOT%\shims;%ROOT%"

if not exist "%VENV%\Scripts\python.exe" (
  python -m venv "%VENV%"
)

call "%VENV%\Scripts\activate.bat"
python -m pip install --upgrade pip setuptools wheel
python -m pip install "apache-airflow==2.10.5" --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.12.txt"
python -m pip install openpyxl playwright requests pyyaml
airflow db migrate
airflow users create --username admin --firstname Saurabh --lastname User --role Admin --email admin@local.dev --password admin

echo AIRFLOW_HOME=%AIRFLOW_HOME%
echo DAGS=%AIRFLOW__CORE__DAGS_FOLDER%
echo USER=admin
echo PASSWORD=admin
endlocal
