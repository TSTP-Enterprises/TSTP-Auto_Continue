@echo off
setlocal enabledelayedexpansion

set "INSTALL_DEV=0"
set "FULL_STACK=0"
set "AUTO_YES=0"
set "MODE=auto"
set "DEV_SET=0"
set "FULL_SET=0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--dev" (
  set "INSTALL_DEV=1"
  set "DEV_SET=1"
) else if /I "%~1"=="--full" (
  set "FULL_STACK=1"
  set "FULL_SET=1"
) else if /I "%~1"=="--yes" (
  set "AUTO_YES=1"
) else if /I "%~1"=="--cli-only" (
  if /I "!MODE!"=="gui" (
    echo Cannot combine --cli-only and --gui-only.
    exit /b 1
  )
  set "MODE=cli"
) else if /I "%~1"=="--gui-only" (
  if /I "!MODE!"=="cli" (
    echo Cannot combine --cli-only and --gui-only.
    exit /b 1
  )
  set "MODE=gui"
) else if /I "%~1"=="--help" (
  call :usage
  exit /b 0
) else (
  echo Unknown argument: %~1
  call :usage
  exit /b 1
)
shift
goto parse_args

:args_done
if "%FULL_STACK%"=="1" set "INSTALL_DEV=1"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found in PATH. Install Python 3.10+ and retry.
  exit /b 1
)

set "V2_DIR=%~dp0"
if "%V2_DIR:~-1%"=="\" set "V2_DIR=%V2_DIR:~0,-1%"
set "REPO_ROOT=%V2_DIR%"
set "VENV_PATH=%REPO_ROOT%\.venv-v2"
set "PYTHON_EXE=%VENV_PATH%\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
  echo Creating virtual environment at "%VENV_PATH%"...
  python -m venv "%VENV_PATH%"
  if errorlevel 1 exit /b 1
)

if not exist "%PYTHON_EXE%" (
  echo Virtual environment python executable not found: %PYTHON_EXE%
  exit /b 1
)

if "%AUTO_YES%"=="0" (
  if "%DEV_SET%"=="0" (
    set /p DEV_INPUT=Install developer dependencies ^(pytest/PyInstaller^)? [y/N]:
    if /I "!DEV_INPUT!"=="y" set "INSTALL_DEV=1"
    if /I "!DEV_INPUT!"=="yes" set "INSTALL_DEV=1"
  )
  if "%FULL_SET%"=="0" (
    set /p FULL_INPUT=Enable optional full-stack setup guidance? [y/N]:
    if /I "!FULL_INPUT!"=="y" set "FULL_STACK=1"
    if /I "!FULL_INPUT!"=="yes" set "FULL_STACK=1"
  )
)

if "%FULL_STACK%"=="1" set "INSTALL_DEV=1"

set "USE_GUI=1"
if /I "%MODE%"=="cli" set "USE_GUI=0"
if /I "%MODE%"=="gui" set "USE_GUI=1"
if /I "%MODE%"=="auto" if "%AUTO_YES%"=="0" (
  set /p GUI_INPUT=Use visual installer first? [Y/n]:
  if /I "!GUI_INPUT!"=="n" set "USE_GUI=0"
  if /I "!GUI_INPUT!"=="no" set "USE_GUI=0"
)

set "EXTRA_ARGS="
if "%INSTALL_DEV%"=="1" set "EXTRA_ARGS=!EXTRA_ARGS! --dev"
if "%FULL_STACK%"=="1" set "EXTRA_ARGS=!EXTRA_ARGS! --full"

pushd "%V2_DIR%"

if "%USE_GUI%"=="1" (
  echo Launching visual installer...
  "%PYTHON_EXE%" "%V2_DIR%\installer_window.py" !EXTRA_ARGS!
  set "GUI_CODE=%ERRORLEVEL%"
  if "!GUI_CODE!"=="0" (
    popd
    exit /b 0
  )
  echo Visual installer exited with code !GUI_CODE!.
  if /I "%MODE%"=="gui" (
    popd
    exit /b !GUI_CODE!
  )

  set "RUN_FALLBACK=1"
  if "%AUTO_YES%"=="0" (
    set /p FALLBACK_INPUT=Run CLI fallback installer now? [Y/n]:
    if /I "!FALLBACK_INPUT!"=="n" set "RUN_FALLBACK=0"
    if /I "!FALLBACK_INPUT!"=="no" set "RUN_FALLBACK=0"
  )
  if "!RUN_FALLBACK!"=="0" (
    popd
    exit /b !GUI_CODE!
  )
)

call :run_cli_install "%PYTHON_EXE%" "%V2_DIR%" "%INSTALL_DEV%" "%FULL_STACK%"
set "CLI_CODE=%ERRORLEVEL%"
popd
exit /b %CLI_CODE%

:run_cli_install
setlocal
set "PYTHON_EXE=%~1"
set "V2_DIR=%~2"
set "INSTALL_DEV=%~3"
set "FULL_STACK=%~4"

echo Running CLI install/repair...
"%PYTHON_EXE%" -m pip install --no-cache-dir --upgrade pip || (endlocal & exit /b 1)
"%PYTHON_EXE%" -m pip install --no-cache-dir -r "%V2_DIR%\requirements.txt" || (endlocal & exit /b 1)
if "%INSTALL_DEV%"=="1" (
  "%PYTHON_EXE%" -m pip install --no-cache-dir -r "%V2_DIR%\requirements-dev.txt" || (endlocal & exit /b 1)
)
if "%FULL_STACK%"=="1" (
  echo Full-stack mode selected. Optional OCR tooling can be installed from the in-app setup wizard.
)

"%PYTHON_EXE%" -c "import sys; from install_support import collect_environment_report; report = collect_environment_report(r'%V2_DIR%', include_dev=False); print('Environment check: ready' if report.ready else 'Environment check: missing requirements'); print('Missing files:', ', '.join(report.missing_files) if report.missing_files else 'none'); print('Missing packages:', ', '.join(report.missing_packages) if report.missing_packages else 'none'); sys.exit(0 if report.ready else 1)" || (endlocal & exit /b 1)
echo CLI install/repair completed successfully.
endlocal & exit /b 0

:usage
echo Usage: install.bat [--dev] [--full] [--yes] [--cli-only ^| --gui-only]
echo   --dev       Install developer requirements too.
echo   --full      Enable full-stack guidance ^(implies --dev^).
echo   --yes       Auto-approve prompts.
echo   --cli-only  Skip GUI installer and run CLI install only.
echo   --gui-only  Use GUI installer only ^(no CLI fallback^).
exit /b 0

