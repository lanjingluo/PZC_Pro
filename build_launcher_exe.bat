@echo off
rem Rebuild the launcher exe from launcher.py (the exe name lives in the .py file).
rem NOTE: keep this file ASCII-only; cmd.exe reads .bat as GBK and mangles UTF-8 text.
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" "%~dp0build_launcher_exe.py"
) else (
    echo [WARN] .venv not found, falling back to the "python" on PATH.
    echo        Run setup_env.bat once to create it.
    python "%~dp0build_launcher_exe.py"
)
pause
