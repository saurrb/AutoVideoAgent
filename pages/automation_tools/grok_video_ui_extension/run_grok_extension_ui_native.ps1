param(
  [Parameter(Mandatory = $true)][string]$PromptFile,
  [string]$WindowTitle = "BrowserOS",
  [int]$PromptX = 1435,
  [int]$PromptY = 792,
  [int]$ScrollX = 1525,
  [int]$ScrollY = 640,
  [int]$RunX = 1534,
  [int]$RunY = 793,
  [int]$PreScrollUpSeconds = 4,
  [int]$ScrollSeconds = 6,
  [int]$ScrollDelta = -120,
  [switch]$CaptureScreens,
  [string]$ScreensDir = "",
  [switch]$SkipActivate
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $PromptFile)) { throw "Prompt file not found: $PromptFile" }

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class NativeMouse {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, int dwData, UIntPtr dwExtraInfo);
  public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
  public const uint MOUSEEVENTF_LEFTUP = 0x0004;
  public const uint MOUSEEVENTF_WHEEL = 0x0800;
}
"@

function Save-Screen([string]$path) {
  $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
  $bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
  $gfx = [System.Drawing.Graphics]::FromImage($bmp)
  $gfx.CopyFromScreen($bounds.Left, $bounds.Top, 0, 0, $bmp.Size)
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $gfx.Dispose(); $bmp.Dispose()
}

function Shot([string]$name) {
  if (-not $CaptureScreens) { return }
  if (-not $ScreensDir) { return }
  New-Item -ItemType Directory -Path $ScreensDir -Force | Out-Null
  $p = Join-Path $ScreensDir ((Get-Date -Format "yyyyMMdd_HHmmss") + "_" + $name + ".png")
  try { Save-Screen $p; Write-Output "screenshot: $p" } catch { Write-Output "screenshot-failed: $name" }
}

function Click-At([int]$x, [int]$y) {
  [NativeMouse]::SetCursorPos($x, $y) | Out-Null
  Start-Sleep -Milliseconds 60
  [NativeMouse]::mouse_event([NativeMouse]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 35
  [NativeMouse]::mouse_event([NativeMouse]::MOUSEEVENTF_LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
}

function Scroll-ForSeconds([int]$x, [int]$y, [int]$seconds, [int]$delta) {
  [NativeMouse]::SetCursorPos($x, $y) | Out-Null
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  while ($sw.Elapsed.TotalSeconds -lt $seconds) {
    [NativeMouse]::mouse_event([NativeMouse]::MOUSEEVENTF_WHEEL, 0, 0, $delta, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 45
  }
}

if (-not $SkipActivate) {
  $wshell = New-Object -ComObject WScript.Shell
  $ok = $wshell.AppActivate($WindowTitle)
  if (-not $ok) { $ok = $wshell.AppActivate("Imagine") }
  if (-not $ok) { $ok = $wshell.AppActivate("Grok") }
  if (-not $ok) { throw "Could not activate BrowserOS/Grok window" }
  Start-Sleep -Milliseconds 250
}

$promptText = Get-Content -Raw -Path $PromptFile
Write-Output "prompt-chars: $($promptText.Length)"
Write-Output "prompt-click: ($PromptX,$PromptY)"
Write-Output "run-click: ($RunX,$RunY)"
Shot "01_before"

# On a fresh Imagine tab, first scroll the right extension panel UP for 4 seconds.
Scroll-ForSeconds -x $ScrollX -y $ScrollY -seconds $PreScrollUpSeconds -delta 120
Start-Sleep -Milliseconds 120
Shot "01b_after_prescroll_up"

# Click prompt area in extension panel and paste directly.
Set-Clipboard -Value $promptText
Click-At -x $PromptX -y $PromptY
Start-Sleep -Milliseconds 80
[System.Windows.Forms.SendKeys]::SendWait("^a")
Start-Sleep -Milliseconds 50
[System.Windows.Forms.SendKeys]::SendWait("{BACKSPACE}")
Start-Sleep -Milliseconds 50
[System.Windows.Forms.SendKeys]::SendWait("^v")
Start-Sleep -Milliseconds 220
Shot "02_after_paste"

# Scroll right section only for ~4-5s.
Scroll-ForSeconds -x $ScrollX -y $ScrollY -seconds $ScrollSeconds -delta $ScrollDelta
Start-Sleep -Milliseconds 120
Shot "03_after_scroll"

# Click Run in bottom-right extension panel.
Click-At -x $RunX -y $RunY
Start-Sleep -Milliseconds 120
Shot "04_after_run"

Write-Output "submitted"

