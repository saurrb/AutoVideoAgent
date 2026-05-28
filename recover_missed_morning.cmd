@echo off
setlocal
set ROOT=C:\Users\Saurabh\Documents\AutoVideoAgent
set LOG=%ROOT%\logs\recover_missed_morning.log

echo ==== RECOVER START %date% %time% ====>> "%LOG%"

echo [1/3] female_psychology>> "%LOG%"
python -u "%ROOT%\scripts\job_runner.py" --page female_psychology >> "%LOG%" 2>&1

echo [2/3] daily_desire_facts>> "%LOG%"
python -u "%ROOT%\scripts\job_runner.py" --page daily_desire_facts >> "%LOG%" 2>&1

echo [3/3] dragon_cinema>> "%LOG%"
python -u "%ROOT%\scripts\job_runner.py" --page dragon_cinema >> "%LOG%" 2>&1

echo ==== RECOVER END %date% %time% ====>> "%LOG%"
echo Done. Log: %LOG%
endlocal
