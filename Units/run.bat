@echo off
rem Units Editor (Python + WinForms): double-click to run.
cd /d "%~dp0"
set "VENV_PY=%~dp0..\.venv\Scripts\pythonw.exe"
if exist "%VENV_PY%" (
    start "" "%VENV_PY%" "%~dp0units_editor.py"
) else (
    echo [WARN] .venv not found, falling back to the "python" on PATH.
    echo        Run setup_env.bat in the project root once to create it.
    python "%~dp0units_editor.py"
)
