@echo off
setlocal

REM Stop all running AutoVideoAgent page pipelines (page 1/2/3/4/5)
REM Usage: double-click or run this .cmd

powershell -NoProfile -ExecutionPolicy Bypass -Command "
$patterns = @(
  '*airflow*page1_female_psychology_manual*',
  '*airflow*page2_daily_desire_facts_manual*',
  '*airflow*page3_dragon_cinema_manual*',
  '*airflow*page4_relationship_manual*',
  '*airflow*page5_health_meter_manual*',
  '*prepare_page4_narration_and_scenes.py*',
  '*render_page4_singlepass.py*',
  '*grok_health_video_generate.py*',
  '*validate_health_video.py*',
  '*dragon_step_scene_a.py*',
  '*dragon_step_scene_b.py*',
  '*dragon_step_finalize.py*',
  '*grok_cli_scene_images_generate.py*',
  '*speechma_run.ps1*',
  '*upload_schedule_ui.py*',
  '*tail_latest_events.ps1* -PageKey female_psychology*',
  '*tail_latest_events.ps1* -PageKey daily_desire_facts*',
  '*tail_latest_events.ps1* -PageKey dragon_cinema*',
  '*tail_latest_events.ps1* -PageKey page4_relationship*',
  '*tail_latest_events.ps1* -PageKey page5_health_meter*'
);
$targets = Get-CimInstance Win32_Process | Where-Object {
  $cmd = [string]$_.CommandLine;
  if([string]::IsNullOrWhiteSpace($cmd)){ return $false }
  foreach($p in $patterns){ if($cmd -like $p){ return $true } }
  return $false
};
if(-not $targets){ Write-Output 'No matching page processes found.'; exit 0 }
Write-Output ('Found ' + $targets.Count + ' process(es). Stopping...');
foreach($t in $targets){
  try {
    taskkill /PID $t.ProcessId /T /F | Out-Null;
    Write-Output ('Stopped PID=' + $t.ProcessId + ' Name=' + $t.Name)
  } catch {
    Write-Output ('Failed PID=' + $t.ProcessId + ' Name=' + $t.Name)
  }
}
Write-Output 'Done.'
"

echo.
echo stopAll completed.
endlocal
