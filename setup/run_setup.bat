@echo off
rem Setup window (Python + WinForms) - double-click to run.
rem NOTE: keep this file ASCII-only; cmd.exe reads .bat as GBK and mangles UTF-8 text.
cd /d "%~dp0"
set "VENV_PY=%~dp0..\.venv\Scripts\pythonw.exe"
if exist "%VENV_PY%" (
    start "" "%VENV_PY%" "%~dp0setup.py"
) else (
    echo [WARN] .venv not found, falling back to the "python" on PATH.
    echo        Run setup_env.bat in the project root once to create it.
    python "%~dp0setup.py"
)
