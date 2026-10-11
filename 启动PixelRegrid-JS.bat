@echo off
cd /d "%~dp0"
if not exist "%~dp0dist\PixelRegrid-JS\PixelRegrid-JS.exe" (
    echo JavaScript build missing: dist\PixelRegrid-JS\PixelRegrid-JS.exe
    echo Build it with scripts\build_javascript.ps1. See README.md.
    pause
    exit /b 1
)
start "" "%~dp0dist\PixelRegrid-JS\PixelRegrid-JS.exe"
