@echo off
setlocal
python "%~dp0prepare_page4_narration_and_scenes.py" %*
exit /b %ERRORLEVEL%
