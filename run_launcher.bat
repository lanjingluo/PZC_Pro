@echo off
rem 游戏启动器 (Python + WinForms)：双击运行
cd /d "%~dp0"
set "BUNDLED_PY=C:\Users\36349\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if exist "%BUNDLED_PY%" (
    start "" "%BUNDLED_PY%" "%~dp0launcher.py"
) else (
    python "%~dp0launcher.py"
)
