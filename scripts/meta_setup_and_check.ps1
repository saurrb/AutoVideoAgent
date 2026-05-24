param(
  [string]$AppId = "",
  [string]$AppSecret = "",
  [string]$PageId = "61590452875190"
)

$ErrorActionPreference = "Stop"

$root = "C:\Users\Saurabh\Documents\AutoVideoAgent"
$py = "py -3"
$tokenOut = Join-Path $root "secrets\meta_token.json"
$configOut = Join-Path $root "secrets\meta_config.json"

if (-not $AppId) { $AppId = $env:META_APP_ID }
if (-not $AppSecret) { $AppSecret = $env:META_APP_SECRET }

if (-not $AppId -or -not $AppSecret) {
  throw "Provide AppId/AppSecret or set META_APP_ID and META_APP_SECRET environment variables."
}

Write-Host "[1/2] Running OAuth to generate token..." -ForegroundColor Cyan
Invoke-Expression "$py `"$root\scripts\meta_oauth.py`" --app-id `"$AppId`" --app-secret `"$AppSecret`" --token-out `"$tokenOut`""

Write-Host "[2/2] Checking page access + reel posting capability..." -ForegroundColor Cyan
Invoke-Expression "$py `"$root\scripts\meta_api_check.py`" --token `"$tokenOut`" --save-config `"$configOut`" --page-id `"$PageId`""

Write-Host "DONE" -ForegroundColor Green
Write-Host "Token:  $tokenOut"
Write-Host "Config: $configOut"
