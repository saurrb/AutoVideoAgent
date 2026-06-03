@echo off
setlocal
set "ROOT_WSL=/mnt/c/Users/Saurabh/Documents/AutoVideoAgent"

wsl.exe bash -lc "cd '%ROOT_WSL%' && bash airflow/wsl/start_airflow_wsl.sh"

echo Waiting for Airflow UI to become ready...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$deadline=(Get-Date).AddSeconds(90); $ok=$false; while((Get-Date) -lt $deadline){ try { $health=Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 5; if($health.metadatabase.status -eq 'healthy' -and $health.scheduler.status -eq 'healthy'){ $ok=$true; break } } catch { }; Start-Sleep -Seconds 3 }; if(-not $ok){ Write-Host 'Airflow did not report healthy within 90 seconds. Check airflow\runtime_logs\wsl_webserver.err.log and wsl_scheduler.err.log'; exit 1 }"
if errorlevel 1 (
  echo Airflow start check failed.
  exit /b 1
)

start "" http://127.0.0.1:8080
echo Airflow UI: http://127.0.0.1:8080
echo Login: admin / admin
endlocal
