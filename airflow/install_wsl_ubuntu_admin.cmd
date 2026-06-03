@echo off
echo This must be run from an Administrator Command Prompt or Administrator PowerShell.
echo It installs WSL2 + Ubuntu. Windows may ask for a restart.
echo.
wsl.exe --install -d Ubuntu
echo.
echo After Ubuntu finishes first-time setup, run:
echo C:\Users\Saurabh\Documents\AutoVideoAgent\airflow\setup_airflow_wsl.cmd
