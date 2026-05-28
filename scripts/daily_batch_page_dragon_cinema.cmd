@echo off
cd /d "C:\Users\Saurabh\Documents\AutoVideoAgent"
set "LOG_DIR=C:\Users\Saurabh\Documents\AutoVideoAgent\logs"
set "LOG_FILE=%LOG_DIR%\dragon_cinema_live.log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
echo.>>"%LOG_FILE%"
echo ===== [%DATE% %TIME%] TASK START: dragon_cinema =====>>"%LOG_FILE%"
for /f "delims=" %%a in ('powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Saurabh\Documents\AutoVideoAgent\scripts\cleanup_stale_processes.ps1" -ProjectRoot "C:\Users\Saurabh\Documents\AutoVideoAgent" -MinAgeMinutes 10') do echo %%a>>"%LOG_FILE%"
start "AutoVideoAgent Live Events - dragon_cinema" powershell -NoExit -ExecutionPolicy Bypass -File "C:\Users\Saurabh\Documents\AutoVideoAgent\scripts\tail_latest_events.ps1" -PageKey "dragon_cinema"
python "C:\Users\Saurabh\Documents\AutoVideoAgent\scripts\job_runner.py" --page dragon_cinema >> "%LOG_FILE%" 2>&1
echo ===== [%DATE% %TIME%] TASK END: dragon_cinema =====>>"%LOG_FILE%"
