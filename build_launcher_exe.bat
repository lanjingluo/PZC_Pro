@echo off
rem Rebuild the launcher exe from launcher.py (the exe name lives in the .py file).
rem NOTE: keep this file ASCII-only; cmd.exe reads .bat as GBK and mangles UTF-8 text.
cd /d "%~dp0"
set "BUNDLED_PY=C:\Users\36349\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED_PY%" (
    "%BUNDLED_PY%" "%~dp0build_launcher_exe.py"
) else (
    python "%~dp0build_launcher_exe.py"
)
pause
