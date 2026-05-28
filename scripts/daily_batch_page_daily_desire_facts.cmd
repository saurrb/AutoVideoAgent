@echo off
cd /d "C:\Users\Saurabh\Documents\AutoVideoAgent"
set "LOG_DIR=C:\Users\Saurabh\Documents\AutoVideoAgent\logs"
set "LOG_FILE=%LOG_DIR%\daily_desire_facts_live.log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
echo.>>"%LOG_FILE%"
echo ===== [%DATE% %TIME%] TASK START: daily_desire_facts =====>>"%LOG_FILE%"
for /f "delims=" %%a in ('powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Saurabh\Documents\AutoVideoAgent\scripts\cleanup_stale_processes.ps1" -ProjectRoot "C:\Users\Saurabh\Documents\AutoVideoAgent" -MinAgeMinutes 10') do echo %%a>>"%LOG_FILE%"
start "AutoVideoAgent Live Events - daily_desire_facts" powershell -NoExit -ExecutionPolicy Bypass -File "C:\Users\Saurabh\Documents\AutoVideoAgent\scripts\tail_latest_events.ps1" -PageKey "daily_desire_facts"
python "C:\Users\Saurabh\Documents\AutoVideoAgent\scripts\job_runner.py" --page daily_desire_facts >> "%LOG_FILE%" 2>&1
echo ===== [%DATE% %TIME%] TASK END: daily_desire_facts =====>>"%LOG_FILE%"
