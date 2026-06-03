param(
  [int]$PageId = 1,
  [Parameter(Mandatory = $true)][string]$OutDir,
  [int]$Pitch = 0,
  [int]$Speed = 25,
  [int]$Volume = 200
)

$ErrorActionPreference = "Stop"

function Require-Cmd([string]$name) {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if (-not $cmd) { throw "Missing required command on PATH: $name" }
}

Require-Cmd "browseros-cli"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# Ensure we're near the input area so the textbox is visible in the screenshot.
browseros-cli eval --page $PageId "window.scrollTo(0, 0)" | Out-Null
Start-Sleep -Milliseconds 250

browseros-cli ss --page $PageId -o (Join-Path $OutDir "01_speechma_input_after_write.png") | Out-Host

# Re-apply defaults so the Voice Effects screenshot always reflects the intended settings
# and "Remember settings" remains enabled.
powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "speechma_apply_defaults.ps1") `
  -PageId $PageId -Pitch $Pitch -Speed $Speed -Volume $Volume | Out-Null

# Open the Voice Effects modal/panel (button text is stable; snapshot IDs are not).
# Use JS template literals to avoid transport escaping issues.
$openEffects = @'
(() => {
  const nodes = Array.from(document.querySelectorAll(`button, [role=button], a, div, span`));
  const btn = nodes.find(n => (n.textContent || ``).trim().toLowerCase() === `voice effects`);
  if (btn) { btn.click(); return { ok: true }; }
  return { ok: false };
})()
'@

browseros-cli eval --page $PageId ($openEffects -replace "(\r\n|\n|\r)", " ") | Out-Null
Start-Sleep -Milliseconds 500

browseros-cli ss --page $PageId -o (Join-Path $OutDir "02_voice_effects.png") | Out-Host
