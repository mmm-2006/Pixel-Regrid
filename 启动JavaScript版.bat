@echo off
cd /d "%~dp0"
if not exist "%~dp0dist\PerfectPixel-JS\PerfectPixel-JS.exe" (
    echo JavaScript build missing: dist\PerfectPixel-JS\PerfectPixel-JS.exe
    echo Build it with scripts\build_javascript.ps1. See README.md.
    pause
    exit /b 1
)
start "" "%~dp0dist\PerfectPixel-JS\PerfectPixel-JS.exe"
