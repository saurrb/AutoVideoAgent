param(
  [string]$ProjectRoot = 'C:\Users\Saurabh\Documents\AutoVideoAgent',
  [int]$MinAgeMinutes = 10
)

$cutoff = (Get-Date).AddMinutes(-$MinAgeMinutes)
$killed = 0

$procs = Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -in @('python.exe','ffmpeg.exe','grok.exe')) -and
  ($_.CreationDate -lt $cutoff) -and
  (
    ($_.CommandLine -like "*$ProjectRoot*") -or
    ($_.CommandLine -like '*daily_ui_batch_schedule.py*') -or
    ($_.CommandLine -like '*job_runner.py*') -or
    ($_.CommandLine -like '*create_and_post_reel.py*') -or
    ($_.CommandLine -like '*generate_dragon_chain_reel.py*') -or
    ($_.CommandLine -like '*autovideo.app.cli*')
  )
}

foreach($p in $procs){
  try {
    taskkill /PID $p.ProcessId /F | Out-Null
    $killed++
  } catch {}
}

Write-Output "STALE_KILLED=$killed"
