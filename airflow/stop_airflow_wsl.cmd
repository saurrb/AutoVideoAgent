@echo off
setlocal
set "ROOT_WSL=/mnt/c/Users/Saurabh/Documents/AutoVideoAgent"

wsl.exe bash -lc "cd '%ROOT_WSL%' && bash airflow/wsl/stop_airflow_wsl.sh"
endlocal
