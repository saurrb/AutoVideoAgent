param(
  [Parameter(Mandatory=$true)][string]$PageKey,
  [string]$ProjectRoot = 'C:\Users\Saurabh\Documents\AutoVideoAgent'
)

$runsRoot = Join-Path $ProjectRoot 'runs\daily_batch'
Write-Host "Waiting for latest run events for page: $PageKey"

while ($true) {
  if (-not (Test-Path $runsRoot)) { Start-Sleep -Seconds 1; continue }

  $latest = Get-ChildItem -Path $runsRoot -Directory -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if ($null -eq $latest) { Start-Sleep -Seconds 1; continue }

  $events = Join-Path $latest.FullName 'events.jsonl'
  if (-not (Test-Path $events)) { Start-Sleep -Seconds 1; continue }

  Write-Host "Tailing: $events"
  Get-Content -Path $events -Wait -Tail 120 | ForEach-Object {
    $line = $_
    Write-Host $line
    try {
      $obj = $line | ConvertFrom-Json -ErrorAction Stop
      if ($null -ne $obj -and $obj.page -eq $PageKey -and $obj.step -eq 'run_summary' -and $obj.status -eq 'ok') {
        $failed = 0
        $pending = 999
        try { $failed = [int]$obj.failed } catch {}
        try { $pending = [int]$obj.pending } catch {}
        if ($failed -eq 0 -and $pending -eq 0) {
          Write-Host "Run completed cleanly for page=$PageKey. Closing watcher window."
          exit 0
        }
        Write-Host "Run summary found but not clean (failed=$failed pending=$pending). Keeping window open for debugging."
      }
    } catch {
      # Ignore non-JSON lines.
    }
  }

  break
}
