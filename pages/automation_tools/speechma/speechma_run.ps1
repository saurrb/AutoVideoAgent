param(
  [Parameter(Mandatory=$true)][string]$TextFile,
  [Parameter(Mandatory=$true)][string]$VoiceJson,
  [Parameter(Mandatory=$true)][string]$OutMp3
)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
$server=Join-Path $root 'speechma_api_server.mjs'
if(!(Test-Path $TextFile)){ throw "Missing text file: $TextFile" }
if(!(Test-Path $VoiceJson)){ throw "Missing voice json: $VoiceJson" }
$v=Get-Content -Raw $VoiceJson | ConvertFrom-Json
$voiceLabel=[string]$v.voice_label; if([string]::IsNullOrWhiteSpace($voiceLabel)){ $voiceLabel='Ava' }
$pitch=[int]$v.pitch; $speed=[int]$v.speed; $volume=[int]$v.volume

try { $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8787/health' -Method Get -TimeoutSec 2 } catch {
  Start-Process -WindowStyle Hidden -FilePath 'node.exe' -ArgumentList @($server) -WorkingDirectory $root | Out-Null
  Start-Sleep -Seconds 2
}

$outDir = Split-Path $OutMp3 -Parent
if([string]::IsNullOrWhiteSpace($outDir)){ $outDir = $root }
$ws=Join-Path $outDir ('speechma_ws_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Force -Path $ws,(Join-Path $ws 'script'),(Join-Path $ws 'voice'),(Join-Path $ws 'analysis'),(Join-Path $ws 'meta') | Out-Null
$script=Join-Path $ws 'script\script_v1.txt'
Copy-Item $TextFile $script -Force
$body=@{
  workspacePath=$ws
  scriptPath=$script
  voiceLabel=$voiceLabel
  pitch=$pitch
  speed=$speed
  volume=$volume
  outputVoicePath=(Join-Path $ws 'voice\voice_v1.mp3')
}|ConvertTo-Json -Depth 6

Write-Host "[speechma] start voice=$voiceLabel pitch=$pitch speed=$speed volume=$volume"
$res=Invoke-RestMethod -Uri 'http://127.0.0.1:8787/speechma/run' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 1200
if(-not $res.ok){ throw "Speechma failed: $($res|ConvertTo-Json -Compress)" }
New-Item -ItemType Directory -Force -Path (Split-Path $OutMp3 -Parent) | Out-Null
Copy-Item -LiteralPath $res.outputVoicePath -Destination $OutMp3 -Force
Write-Host "DONE: $OutMp3"
Write-Host "WORKSPACE: $ws"
