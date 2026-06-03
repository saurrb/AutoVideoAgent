param(
  [Parameter(Mandatory=$true)][string]$PromptFile,
  [Parameter(Mandatory=$true)][string]$OutputDir,
  [int]$PollSeconds = 5,
  [int]$MaxWaitSeconds = 900,
  [switch]$TryCliFirst = $true,
  [switch]$CaptureScreens,
  [string]$WindowTitle = "BrowserOS",
  [string]$GrokDownloadDir = "C:\Users\Saurabh\Downloads\grok-folder-1"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

if (-not (Test-Path -LiteralPath $PromptFile)) { throw "Prompt file not found: $PromptFile" }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$eventPath = Join-Path $OutputDir "grok_outputs.done.json"
if (Test-Path -LiteralPath $eventPath) { Remove-Item -LiteralPath $eventPath -Force -ErrorAction SilentlyContinue }
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Focus-BrowserWindow {
  $wshell = New-Object -ComObject WScript.Shell
  $ok = $wshell.AppActivate($WindowTitle)
  if (-not $ok) { $ok = $wshell.AppActivate("Grok") }
  if (-not $ok) { $ok = $wshell.AppActivate("Imagine") }
  if (-not $ok) { throw "Could not activate BrowserOS/Grok window" }
  Start-Sleep -Milliseconds 250
}

function Get-ActiveTabUrl {
  [System.Windows.Forms.SendKeys]::SendWait("^l")
  Start-Sleep -Milliseconds 120
  [System.Windows.Forms.SendKeys]::SendWait("^c")
  Start-Sleep -Milliseconds 120
  try { return (Get-Clipboard -Raw).Trim() } catch { return "" }
}

function Close-GrokImagineTabs {
  [System.Windows.Forms.SendKeys]::SendWait("^9")
  Start-Sleep -Milliseconds 160

  $maxTabs = 25
  for ($i=0; $i -lt $maxTabs; $i++) {
    $u = Get-ActiveTabUrl
    if ($u -like "*grok.com/imagine*") {
      Write-Host "[grok] closing imagine tab: $u"
      [System.Windows.Forms.SendKeys]::SendWait("^w")
      Start-Sleep -Milliseconds 220
      continue
    }
    [System.Windows.Forms.SendKeys]::SendWait("^+{TAB}")
    Start-Sleep -Milliseconds 120
  }
}

$since = Get-Date
Write-Host "[grok] start: $($since.ToString('s'))"
Write-Host "[grok] prompt: $PromptFile"
Write-Host "[grok] output: $OutputDir"
Write-Host "[grok] source-download-dir: $GrokDownloadDir"

$promptTextForCount = Get-Content -Raw -LiteralPath $PromptFile
$sceneMatches = [regex]::Matches($promptTextForCount, '(?im)^\s*Scene\s+\d+\s*:')
$expectedCount = 1
if ($sceneMatches.Count -gt 0) {
  $expectedCount = $sceneMatches.Count
} else {
  # New format support: scenes are blocks separated by exactly one blank line.
  $blocks = @(
    [regex]::Split($promptTextForCount.Trim(), '\r?\n\s*\r?\n') |
      ForEach-Object { $_.Trim() } |
      Where-Object { $_ -ne "" }
  )
  if ($blocks.Count -gt 0) { $expectedCount = $blocks.Count }
}
Write-Host "[grok] expected scene files: $expectedCount"

if ($TryCliFirst) {
  $cliScript = Join-Path $PSScriptRoot "grok_cli_scene_generate.py"
  if (Test-Path -LiteralPath $cliScript) {
    Write-Host "[grok] trying CLI-first scene generation..."
    $sceneTimeout = [Math]::Max(180, [int]($MaxWaitSeconds / [Math]::Max(1, $expectedCount)))
    & python $cliScript --prompt-file $PromptFile --output-dir $OutputDir --max-scene-seconds $sceneTimeout | Out-Host
    if ($LASTEXITCODE -eq 0) {
      Write-Host "[grok] CLI-first generation succeeded."
      exit 0
    }
    Write-Host "[grok] CLI-first failed, falling back to extension UI..."
  } else {
    Write-Host "[grok] CLI script missing, falling back to extension UI..."
  }
}

Focus-BrowserWindow
Write-Host "[grok] browser window focused"

Close-GrokImagineTabs
Write-Host "[grok] grok imagine tabs cleanup done"

[System.Windows.Forms.SendKeys]::SendWait("^l")
Start-Sleep -Milliseconds 120
Set-Clipboard -Value "https://grok.com/imagine"
[System.Windows.Forms.SendKeys]::SendWait("^v")
Start-Sleep -Milliseconds 80
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
Write-Host "[grok] opened fresh imagine"
Start-Sleep -Seconds 2

$native = Join-Path $PSScriptRoot "run_grok_extension_ui_native.ps1"
Write-Host "[grok] submit via extension panel"
$args = @(
  "-NoProfile","-ExecutionPolicy","Bypass","-File",$native,
  "-PromptFile",$PromptFile,
  "-WindowTitle",$WindowTitle,
  "-ScreensDir",$logDir
)
if ($CaptureScreens) { $args += "-CaptureScreens" }
& powershell @args | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Submit failed (exit=$LASTEXITCODE)" }

$downloads = $GrokDownloadDir
$seenBefore = @{}
if (Test-Path -LiteralPath $downloads) {
  Get-ChildItem -Path $downloads -File -ErrorAction SilentlyContinue | ForEach-Object { $seenBefore[$_.FullName] = $true }
}
$elapsed = 0
Write-Host "[grok] waiting for new scene files..."
while ($elapsed -lt $MaxWaitSeconds) {
  $allNow = @()
  if (Test-Path -LiteralPath $downloads) {
    $allNow = Get-ChildItem -Path $downloads -File -ErrorAction SilentlyContinue |
      Where-Object { $_.Extension -in @(".mp4", ".mov", ".mkv", ".webm") } |
      Sort-Object LastWriteTime
  }
  $newFiles = @(
    $allNow | Where-Object {
      (-not $seenBefore.ContainsKey($_.FullName)) -and
      (($_.CreationTime -ge $since) -or ($_.LastWriteTime -ge $since))
    }
  )

  if ($newFiles.Count -ge $expectedCount) {
    $picked = @($newFiles | Select-Object -First $expectedCount)
    $moved = @()
    $i = 1
    foreach ($f in $picked) {
      $dest = Join-Path $OutputDir ("grok_scene_{0}_{1}{2}" -f (Get-Date -Format "yyyyMMdd_HHmmss"), $i, $f.Extension)
      Move-Item -LiteralPath $f.FullName -Destination $dest -Force
      $moved += $dest
      $i += 1
    }
    Write-Host "[grok] DONE moved files:"
    $moved | ForEach-Object { Write-Host ("  - " + $_) }
    $event = [ordered]@{
      status = "ok"
      created_at = (Get-Date).ToString("o")
      expected_count = $expectedCount
      moved_count = $moved.Count
      files = $moved
      output_dir = $OutputDir
      source_download_dir = $downloads
    }
    $event | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $eventPath -Encoding UTF8
    Write-Host "[grok] event file: $eventPath"
    Write-Output ($moved -join "`n")
    exit 0
  }

  Start-Sleep -Seconds $PollSeconds
  $elapsed += $PollSeconds
  if (($elapsed % 20) -eq 0) { Write-Host "[grok] waiting... ${elapsed}s (found $($newFiles.Count)/$expectedCount new files)" }
}

throw "Timed out after $MaxWaitSeconds seconds waiting for $expectedCount new scene files in $downloads"
