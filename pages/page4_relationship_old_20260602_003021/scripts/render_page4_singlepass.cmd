@echo off
setlocal
if "%~1"=="" (
  echo Usage: render_page4_singlepass.cmd ^<manifest_json^>
  exit /b 1
)
python "C:\Users\Saurabh\Documents\AutoVideoAgent\pages\page4_relationship\scripts\render_page4_singlepass.py" --manifest "%~1"
exit /b %ERRORLEVEL%

