@echo off
rem Units Editor (Python + WinForms): double-click to run.
cd /d "%~dp0"
set "BUNDLED_PY=C:\Users\36349\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if exist "%BUNDLED_PY%" (
    start "" "%BUNDLED_PY%" "%~dp0units_editor.py"
) else (
    python "%~dp0units_editor.py"
)
