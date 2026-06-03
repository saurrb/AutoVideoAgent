@echo off
taskkill /FI "WINDOWTITLE eq AutoVideoAgent Airflow Webserver" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq AutoVideoAgent Airflow Scheduler" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Page4 Airflow Webserver" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Page4 Airflow Scheduler" /T /F >nul 2>&1
echo Requested stop for AutoVideoAgent Airflow windows.
