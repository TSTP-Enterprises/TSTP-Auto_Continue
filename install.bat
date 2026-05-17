@echo off
setlocal enabledelayedexpansion

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found in PATH. Install Python 3.10+ and retry.
  exit /b 1
)

set "V2_DIR=%~dp0"
for %%I in ("%V2_DIR%..") do set "REPO_ROOT=%%~fI"
set "VENV_PATH=%REPO_ROOT%\.venv-v2"

if not exist "%VENV_PATH%" (
  python -m venv "%VENV_PATH%"
)

set "PYTHON_EXE=%VENV_PATH%\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Virtual environment python executable not found: %PYTHON_EXE%
  exit /b 1
)

set "EXTRA_ARGS="
if /I "%1"=="--dev" set "EXTRA_ARGS=--dev"

"%PYTHON_EXE%" "%V2_DIR%installer_window.py" %EXTRA_ARGS%
exit /b %ERRORLEVEL%

