$root = "C:\Users\Saurabh\Documents\AutoVideoAgent"
$airflowRoot = Join-Path $root "airflow"
$env:AIRFLOW_HOME = Join-Path $airflowRoot "home"
$env:AIRFLOW__CORE__DAGS_FOLDER = Join-Path $airflowRoot "dags"
$env:AIRFLOW__CORE__LOAD_EXAMPLES = "False"
$env:AIRFLOW__CORE__DEFAULT_TIMEZONE = "Asia/Calcutta"
$env:AIRFLOW__CORE__EXECUTOR = "SequentialExecutor"
$env:AIRFLOW__DATABASE__SQL_ALCHEMY_CONN = "sqlite:///C:/Users/Saurabh/Documents/AutoVideoAgent/airflow/home/airflow.db"
$env:PYTHONPATH = (Join-Path $airflowRoot "shims") + ";" + $root

& (Join-Path $airflowRoot ".venv\Scripts\python.exe") -m airflow webserver --debug --port 8080
