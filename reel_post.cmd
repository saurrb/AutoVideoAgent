@echo off
setlocal

if "%~1"=="" goto :usage
if "%~2"=="" goto :usage

set "MODE="
set "PAGE="

if /I "%~1"=="fb_api=true" (
  set "MODE=true"
  set "PAGE=%~2"
  goto :run
)
if /I "%~1"=="fb_api=false" (
  set "MODE=false"
  set "PAGE=%~2"
  goto :run
)
if /I "%~1"=="fb_api" (
  if /I "%~2"=="true" (
    set "MODE=true"
    set "PAGE=%~3"
    goto :run
  )
  if /I "%~2"=="false" (
    set "MODE=false"
    set "PAGE=%~3"
    goto :run
  )
)

goto :usage

:run
if "%PAGE%"=="" goto :usage
cd /d "%~dp0"

if /I "%MODE%"=="false" (
  python .\scripts\create_and_post_reel.py --page "%PAGE%" --dry-run
) else (
  python .\scripts\create_and_post_reel.py --page "%PAGE%"
)
if errorlevel 1 goto :fail

if /I "%MODE%"=="false" (
  echo [OK] Reel created (not posted) for page: %PAGE%
) else (
  echo [OK] Reel created and posted for page: %PAGE%
)
exit /b 0

:fail
echo [ERROR] Reel command failed for page: %PAGE%
exit /b 1

:usage
echo Usage:
echo   reel_post.cmd fb_api=true ^<page_name^>
echo   reel_post.cmd fb_api=false ^<page_name^>
echo   reel_post.cmd fb_api true ^<page_name^>
echo   reel_post.cmd fb_api false ^<page_name^>
exit /b 1
