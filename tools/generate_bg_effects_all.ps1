$ErrorActionPreference = "Stop"

$root = "C:\Users\Saurabh\Documents\AutoVideoAgent"
$imagesDir = Join-Path $root "pages\female_psychology\assets\backgrounds\images"
$videosDir = Join-Path $root "pages\female_psychology\assets\backgrounds\video"
$logDir = Join-Path $root "logs"

New-Item -ItemType Directory -Force -Path $videosDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$images = Get-ChildItem -Path $imagesDir -Filter "bg*.png" | Sort-Object Name
if (-not $images) {
  throw "No bg*.png files found in $imagesDir"
}

$effects = @(
  @{ Name = "boxblur"; Filter = "boxblur=10:1" },
  @{ Name = "geq";     Filter = "geq=r='r(X,Y)':g='g(X+5*sin(T*2),Y)':b='b(X,Y+5*cos(T*2))'" },
  @{ Name = "hflip";   Filter = "hflip" },
  @{ Name = "hue";     Filter = "hue='H=2*t:s=1.15'" },
  @{ Name = "lutrgb";  Filter = "lutrgb=r='val*1.05':g='val*0.98':b='val*1.12'" },
  @{ Name = "scale";   Filter = "scale=iw*1.06:ih*1.06,crop=iw/1.06:ih/1.06" },
  @{ Name = "unsharp"; Filter = "unsharp=7:7:1.2:7:7:0.0" }
)

foreach ($img in $images) {
  $base = [System.IO.Path]::GetFileNameWithoutExtension($img.Name)
  foreach ($e in $effects) {
    $outFile = Join-Path $videosDir ("{0}_{1}_okay.mp4" -f $base, $e.Name)
    if (Test-Path $outFile) {
      Write-Host "SKIP: $outFile"
      continue
    }

    $vf = "scale=696:1280:force_original_aspect_ratio=increase,crop=696:1280,{0},format=yuv420p" -f $e.Filter
    $args = @(
      "-y",
      "-loop", "1",
      "-i", $img.FullName,
      "-t", "10",
      "-r", "30",
      "-vf", $vf,
      "-c:v", "libx264",
      "-pix_fmt", "yuv420p",
      $outFile
    )

    Write-Host ("RUN: {0} -> {1}" -f $img.Name, [System.IO.Path]::GetFileName($outFile))
    & ffmpeg @args | Out-Null
  }
}

Write-Host "DONE"

