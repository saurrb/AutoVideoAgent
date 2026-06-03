@echo off
setlocal enabledelayedexpansion

set "ROOT=C:\Users\Saurabh\Documents\AutoVideoAgent\pages\page4_relationship"
set "PREP_CMD=%ROOT%\prepare_page4_narration_and_scenes.cmd"

for /f "usebackq delims=" %%L in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%PREP_CMD%'"`) do (
  echo %%L
  set "LINE=%%L"
  if /i "!LINE:~0,9!"=="MANIFEST=" set "MANIFEST=!LINE:~9!"
  if /i "!LINE:~0,16!"=="SCENE_PROMPT_TXT=" set "PROMPT_TXT=!LINE:~16!"
  if /i "!LINE:~0,16!"=="GROK_OUTPUT_DIR=" set "GROK_OUTPUT=!LINE:~16!"
)

if not defined MANIFEST (
  echo [page4] ERROR: MANIFEST not found from prepare output.
  exit /b 2
)
if not defined PROMPT_TXT (
  echo [page4] ERROR: SCENE_PROMPT_TXT not found from prepare output.
  exit /b 2
)
if not defined GROK_OUTPUT (
  echo [page4] ERROR: GROK_OUTPUT_DIR not found from prepare output.
  exit /b 2
)

echo [page4] manifest: %MANIFEST%
echo [page4] prompt:   %PROMPT_TXT%
echo [page4] out dir:  %GROK_OUTPUT%

python "C:\Users\Saurabh\Documents\AutoVideoAgent\pages\automation_tools\grok_image_cli\grok_cli_scene_images_generate.py" --prompt-file "%PROMPT_TXT%" --output-dir "%GROK_OUTPUT%"
if errorlevel 1 exit /b %errorlevel%

call "%ROOT%\scripts\render_page4_singlepass.cmd" "%MANIFEST%"
exit /b %errorlevel%
