@echo off
rem Create the project virtual environment (.venv) and install requirements.txt.
rem Run this once after cloning, or after deleting .venv.
rem NOTE: keep this file ASCII-only; cmd.exe reads .bat as GBK and mangles UTF-8 text.
setlocal
cd /d "%~dp0"

if not exist "%~dp0requirements.txt" (
    echo [ERROR] requirements.txt not found next to this script.
    pause
    exit /b 1
)

set "VENV_DIR=%~dp0.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo Creating virtual environment in .venv ...
    py -3.13 -m venv "%VENV_DIR%" 2>nul
    if not exist "%VENV_PY%" py -3 -m venv "%VENV_DIR%" 2>nul
    if not exist "%VENV_PY%" python -m venv "%VENV_DIR%"
)

if not exist "%VENV_PY%" (
    echo [ERROR] Could not create the venv. Install Python 3.13 and try again.
    pause
    exit /b 1
)

echo Installing dependencies into .venv ...
"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo Done. You can now double-click run_launcher.bat, Units\run.bat, Hex_Editor\run.bat or setup\run_setup.bat.
pause
