@echo off
setlocal
set "ROOT_WIN=C:\Users\Saurabh\Documents\AutoVideoAgent"
set "ROOT_WSL=/mnt/c/Users/Saurabh/Documents/AutoVideoAgent"

wsl.exe bash -lc "cd '%ROOT_WSL%' && bash airflow/wsl/setup_airflow_wsl.sh"
endlocal
