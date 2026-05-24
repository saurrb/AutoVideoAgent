param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$nodeDir = "C:\Program Files\nodejs"
$nodeExe = Join-Path $nodeDir "node.exe"
$projectCliJs = Join-Path $PSScriptRoot "..\tools\browseros-cli\bin\browseros-cli.js"

if (-not (Test-Path $nodeExe)) {
    Write-Error "Node.js not found at $nodeExe. Install Node LTS first."
    exit 1
}

# Prefer the standard Node install before the packaged Codex runtime on PATH.
$env:Path = "$nodeDir;$env:Path"

if (Test-Path $projectCliJs) {
    & $nodeExe $projectCliJs @Args
    exit $LASTEXITCODE
}

# Fallback: use npx package resolution.
& $nodeExe "$nodeDir\node_modules\npm\bin\npx-cli.js" -y browseros-cli @Args
exit $LASTEXITCODE
