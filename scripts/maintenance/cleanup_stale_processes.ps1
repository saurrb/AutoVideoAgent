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
    ($_.CommandLine -like '*dragon_step_scene_a.py*') -or
    ($_.CommandLine -like '*dragon_step_scene_b.py*') -or
    ($_.CommandLine -like '*dragon_step_finalize.py*') -or
    ($_.CommandLine -like '*prepare_page4_narration_and_scenes.py*') -or
    ($_.CommandLine -like '*render_page4_singlepass.py*') -or
    ($_.CommandLine -like '*grok_cli_scene_images_generate.py*') -or
    ($_.CommandLine -like '*upload_schedule_ui.py*') -or
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
