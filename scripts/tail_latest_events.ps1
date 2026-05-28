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
  if (Test-Path $events) {
    Write-Host "Tailing: $events"
    Get-Content -Path $events -Wait -Tail 120
    break
  }

  Start-Sleep -Seconds 1
}
