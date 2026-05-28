@echo off
cd /d "C:\Users\Saurabh\Documents\AutoVideoAgent"
python "C:\Users\Saurabh\Documents\AutoVideoAgent\scripts\sync_automation_control.py" >> "C:\Users\Saurabh\Documents\AutoVideoAgent\logs\daily_ui_batch.log" 2>>&1
python "C:\Users\Saurabh\Documents\AutoVideoAgent\scripts\daily_ui_batch_schedule.py" >> "C:\Users\Saurabh\Documents\AutoVideoAgent\logs\daily_ui_batch.log" 2>>&1
