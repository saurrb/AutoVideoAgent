@echo off
setlocal

cd /d "%~dp0"

set "PYTHON=python"
set "XLSX=.\pages\female_psychology\content\reel_content_bank.xlsx"
set "STYLE_JSON=.\output\exact_clone\reel_female_psychology_v2.json"
set "OUT_DIR=.\output\exact_clone"
set "AUDIO=.\pages\female_psychology\assets\music\bg.mp3"
set "FALLBACK_LOGO=C:\Users\Saurabh\Documents\AutoVideoAgent\pages\female_psychology\assets\logo\logo1.png"

if not exist "%XLSX%" (
  echo [INFO] Content bank not found. Creating: %XLSX%
  %PYTHON% .\scripts\create_reel_content_excel.py --out "%XLSX%"
  if errorlevel 1 (
    echo [ERROR] Failed to create content bank.
    exit /b 1
  )
)

echo [INFO] Rendering 3-second reel from next 5 unused rows...
%PYTHON% .\scripts\render_reel_from_excel.py --xlsx "%XLSX%" --style-json "%STYLE_JSON%" --out-dir "%OUT_DIR%" --audio "%AUDIO%"
if errorlevel 1 (
  echo [WARN] First attempt failed. Trying fallback logo path...
  %PYTHON% -c "import json, pathlib; p=pathlib.Path(r'%STYLE_JSON%'); d=json.loads(p.read_text(encoding='utf-8-sig')); d.setdefault('assets',{})['logo_path']=str(pathlib.Path(r'%FALLBACK_LOGO%').resolve()).replace('\\\\','/'); p.write_text(json.dumps(d, indent=2), encoding='utf-8')"
  %PYTHON% .\scripts\render_reel_from_excel.py --xlsx "%XLSX%" --style-json "%STYLE_JSON%" --out-dir "%OUT_DIR%" --audio "%AUDIO%"
)
if errorlevel 1 (
  echo [ERROR] Reel generation failed.
  exit /b 1
)

echo [OK] Reel generation complete.
exit /b 0

