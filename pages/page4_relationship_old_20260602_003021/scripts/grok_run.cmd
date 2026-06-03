@echo off
setlocal
if "%~1"=="" goto usage
if "%~2"=="" goto usage
set "PROMPT_FILE=%~1"
set "OUT_DIR=%~2"
set "DL_DIR=C:\Users\Saurabh\Downloads\grok-folder-1"
if not "%~3"=="" set "DL_DIR=%~3"
echo [grok] prompt=%PROMPT_FILE%
echo [grok] out=%OUT_DIR%
echo [grok] downloads=%DL_DIR%
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0grok_run.ps1" -PromptFile "%PROMPT_FILE%" -OutputDir "%OUT_DIR%" -GrokDownloadDir "%DL_DIR%"
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" echo [grok] failed exit=%EC%
exit /b %EC%
:usage
echo Usage: %~nx0 ^<prompt_txt_file^> ^<output_folder^> [download_folder]
exit /b 2
