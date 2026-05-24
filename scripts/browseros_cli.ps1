param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$nodeDir = "C:\Program Files\nodejs"
$nodeExe = Join-Path $nodeDir "node.exe"
$cliJs = Join-Path $PSScriptRoot "..\old_videoAgent\node_modules\browseros-cli\bin\browseros-cli.js"

if (-not (Test-Path $nodeExe)) {
    Write-Error "Node.js not found at $nodeExe. Install Node LTS first."
    exit 1
}

if (-not (Test-Path $cliJs)) {
    Write-Error "browseros-cli entrypoint not found at $cliJs."
    exit 1
}

# Prefer the standard Node install before the packaged Codex runtime on PATH.
$env:Path = "$nodeDir;$env:Path"

& $nodeExe $cliJs @Args
exit $LASTEXITCODE
