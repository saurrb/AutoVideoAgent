$ErrorActionPreference = "Stop"

$python = "C:\Users\Saurabh\AppData\Local\Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) {
  throw "Python not found at $python"
}

& $python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

New-Item -ItemType Directory -Path .\data -Force | Out-Null
New-Item -ItemType Directory -Path .\config -Force | Out-Null
New-Item -ItemType Directory -Path .\assets\music -Force | Out-Null
New-Item -ItemType Directory -Path .\output -Force | Out-Null

if (-not (Test-Path .\.env) -and (Test-Path .\.env.example)) {
  Copy-Item .\.env.example .\.env
}

Write-Output "Setup complete. Edit .env and add data\lines.txt + assets\music\bg.mp3."
