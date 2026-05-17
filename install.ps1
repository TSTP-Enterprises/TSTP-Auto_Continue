Param(
    [switch]$Dev
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found in PATH. Install Python 3.10+ and retry."
}

$v2Dir = $PSScriptRoot
$repoRoot = Split-Path -Parent $v2Dir
$venvPath = Join-Path $repoRoot ".venv-v2"

if (-not (Test-Path $venvPath)) {
    python -m venv $venvPath
}

$pythonExe = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment python executable not found at $pythonExe"
}

$args = @("$v2Dir\installer_window.py")
if ($Dev) {
    $args += "--dev"
}

& $pythonExe @args
exit $LASTEXITCODE

