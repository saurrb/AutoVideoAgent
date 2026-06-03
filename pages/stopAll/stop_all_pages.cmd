@echo off
setlocal

REM Stop all running AutoVideoAgent page pipelines (page 1/2/3/4)
REM Usage: double-click or run this .cmd

powershell -NoProfile -ExecutionPolicy Bypass -Command "
$patterns = @(
  '*daily_batch_page_female_psychology.cmd*',
  '*daily_batch_page_daily_desire_facts.cmd*',
  '*daily_batch_page_dragon_cinema.cmd*',
  '*daily_batch_page_page4_relationship.cmd*',
  '*run_task_page4_relationship.ps1*',
  '*job_runner.py*--page female_psychology*',
  '*job_runner.py*--page daily_desire_facts*',
  '*job_runner.py*--page dragon_cinema*',
  '*job_runner.py*--page page4_relationship*',
  '*generate_page4_reel.py*',
  '*prepare_page4_narration_and_scenes.py*',
  '*tail_latest_events.ps1* -PageKey female_psychology*',
  '*tail_latest_events.ps1* -PageKey daily_desire_facts*',
  '*tail_latest_events.ps1* -PageKey dragon_cinema*',
  '*tail_latest_events.ps1* -PageKey page4_relationship*'
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
