@echo off
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Python environment missing: .venv\Scripts\pythonw.exe
    echo Please restore the .venv folder. See requirements.txt for dependencies.
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0launch.py"
