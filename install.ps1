Param(
    [switch]$Dev,
    [switch]$Full,
    [switch]$Yes,
    [switch]$CliOnly,
    [switch]$GuiOnly
)

$ErrorActionPreference = "Stop"

if ($CliOnly -and $GuiOnly) {
    throw "Cannot combine -CliOnly and -GuiOnly."
}

function Read-Approval {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt,
        [bool]$DefaultYes = $false
    )

    if ($Yes) {
        return $true
    }

    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    $response = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrWhiteSpace($response)) {
        return $DefaultYes
    }

    switch ($response.Trim().ToLowerInvariant()) {
        "y" { return $true }
        "yes" { return $true }
        "n" { return $false }
        "no" { return $false }
        default {
            Write-Host "Please answer y or n."
            return Read-Approval -Prompt $Prompt -DefaultYes:$DefaultYes
        }
    }
}

function Invoke-CliInstall {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe,
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir,
        [bool]$InstallDev,
        [bool]$FullStack
    )

    & $PythonExe -m pip install --no-cache-dir --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip."
    }

    & $PythonExe -m pip install --no-cache-dir -r (Join-Path $ProjectDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install runtime requirements."
    }

    if ($InstallDev) {
        & $PythonExe -m pip install --no-cache-dir -r (Join-Path $ProjectDir "requirements-dev.txt")
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install developer requirements."
        }
    }

    if ($FullStack) {
        Write-Host "Full-stack mode selected. Optional OCR tooling can be installed from the in-app setup wizard."
    }

    $verifyScript = @"
import sys
from install_support import collect_environment_report

report = collect_environment_report(r'''$ProjectDir''', include_dev=False)
print("Environment check: ready" if report.ready else "Environment check: missing requirements")
print("Missing files:", ", ".join(report.missing_files) if report.missing_files else "none")
print("Missing packages:", ", ".join(report.missing_packages) if report.missing_packages else "none")
sys.exit(0 if report.ready else 1)
"@

    & $PythonExe -c $verifyScript
    if ($LASTEXITCODE -ne 0) {
        throw "Environment verification failed after CLI install."
    }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found in PATH. Install Python 3.10+ and retry."
}

$v2Dir = $PSScriptRoot
$venvPath = Join-Path $v2Dir ".venv-v2"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Host "Creating virtual environment at $venvPath ..."
    python -m venv $venvPath
}

if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment python executable not found at $pythonExe"
}

$installDev = $Dev.IsPresent
$fullStack = $Full.IsPresent

if (-not $PSBoundParameters.ContainsKey("Dev") -and -not $Yes) {
    $installDev = Read-Approval -Prompt "Install developer dependencies (pytest/PyInstaller)?" -DefaultYes:$false
}

if (-not $PSBoundParameters.ContainsKey("Full") -and -not $Yes) {
    $fullStack = Read-Approval -Prompt "Enable optional full-stack setup guidance?" -DefaultYes:$false
}

if ($fullStack) {
    $installDev = $true
}

$mode = "auto"
if ($CliOnly) { $mode = "cli" }
if ($GuiOnly) { $mode = "gui" }

$useGui = $true
if ($mode -eq "cli") {
    $useGui = $false
} elseif ($mode -eq "auto" -and -not $Yes) {
    $useGui = Read-Approval -Prompt "Use visual installer first?" -DefaultYes:$true
}

Push-Location $v2Dir
try {
    $guiArgs = @("$v2Dir\installer_window.py")
    if ($installDev) { $guiArgs += "--dev" }
    if ($fullStack) { $guiArgs += "--full" }

    if ($useGui) {
        Write-Host "Launching visual installer..."
        & $pythonExe @guiArgs
        $guiExitCode = $LASTEXITCODE

        if ($guiExitCode -eq 0) {
            exit 0
        }

        Write-Warning "Visual installer exited with code $guiExitCode."
        if ($mode -eq "gui") {
            exit $guiExitCode
        }

        $runFallback = if ($Yes) { $true } else { Read-Approval -Prompt "Run CLI fallback installer now?" -DefaultYes:$true }
        if (-not $runFallback) {
            exit $guiExitCode
        }
    }

    Write-Host "Running CLI install/repair..."
    Invoke-CliInstall -PythonExe $pythonExe -ProjectDir $v2Dir -InstallDev:$installDev -FullStack:$fullStack
    Write-Host "CLI install/repair completed successfully."
    exit 0
}
finally {
    Pop-Location
}

