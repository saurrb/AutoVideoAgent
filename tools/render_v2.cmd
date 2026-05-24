@echo off
setlocal
cd /d "%~dp0.."

set "PYTHONPATH=%CD%\\src"
set "PYTHON_EXE=C:\Users\Saurabh\AppData\Local\Programs\Python\Python312\python.exe"
"%PYTHON_EXE%" -m autovideo.app.cli render --page female_psychology %*

endlocal

