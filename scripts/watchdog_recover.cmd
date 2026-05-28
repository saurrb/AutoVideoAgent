@echo off
cd /d "C:\Users\Saurabh\Documents\AutoVideoAgent"
python "C:\Users\Saurabh\Documents\AutoVideoAgent\scripts\watchdog_recover.py" --max-age-min 20 --page daily_desire_facts >> "C:\Users\Saurabh\Documents\AutoVideoAgent\logs\watchdog_recover.log" 2>&1

