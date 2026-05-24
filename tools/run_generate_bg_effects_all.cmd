@echo off
setlocal

set "ROOT=C:\Users\Saurabh\Documents\AutoVideoAgent"
set "PS_SCRIPT=%ROOT%\tools\generate_bg_effects_all.ps1"
set "LOG_DIR=%ROOT%\logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
set "LOG_FILE=%LOG_DIR%\bg_effects_%TS%.log"

start "" /b powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" > "%LOG_FILE%" 2>&1

echo Started in background.
echo Log: %LOG_FILE%
endlocal
