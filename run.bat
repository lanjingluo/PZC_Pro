@echo off
rem Hex Editor launcher (Python + WinForms): double-click to run.
cd /d "%~dp0"
set "BUNDLED_PY=C:\Users\36349\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if exist "%BUNDLED_PY%" (
    start "" "%BUNDLED_PY%" "%~dp0main.py"
) else (
    python main.py
)
