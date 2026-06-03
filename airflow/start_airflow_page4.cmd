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

if not exist "%VENV%\Scripts\airflow.exe" (
  echo Airflow is not initialized. Run init_airflow_page4.cmd first.
  exit /b 1
)

start "AutoVideoAgent Airflow Webserver" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%AIRFLOW_ROOT%\run_airflow_webserver.ps1"
start "" http://127.0.0.1:8080

echo Airflow UI: http://127.0.0.1:8080
echo Login: admin / admin
echo Note: native Windows web UI works here, but the Airflow scheduler still needs WSL2 or Docker for reliable automation.
endlocal
