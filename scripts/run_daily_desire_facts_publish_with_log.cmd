@echo off
cd /d "C:\Users\Saurabh\Documents\AutoVideoAgent"
call "C:\Users\Saurabh\Documents\AutoVideoAgent\reel_post.cmd" fb_api=true daily_desire_facts >> "C:\Users\Saurabh\Documents\AutoVideoAgent\logs\reel_scheduler_daily_desire.log" 2>>&1

