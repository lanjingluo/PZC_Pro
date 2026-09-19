@echo off
rem Setup window (Python + WinForms) - double-click to run.
rem NOTE: keep this file ASCII-only; cmd.exe reads .bat as GBK and mangles UTF-8 text.
cd /d "%~dp0"
set "BUNDLED_PY=C:\Users\36349\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if exist "%BUNDLED_PY%" (
    start "" "%BUNDLED_PY%" "%~dp0setup.py"
) else (
    python "%~dp0setup.py"
)
