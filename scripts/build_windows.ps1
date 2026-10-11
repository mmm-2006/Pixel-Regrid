$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $taskProjectRoot
try {
    $taskPython = Join-Path $taskProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $taskPython)) {
        throw 'Missing .venv. Follow README.md to install the Python dependencies first.'
    }
    & $taskPython -m PyInstaller --version
    if ($LASTEXITCODE -ne 0) { throw 'Install PyInstaller in .venv first.' }
    Push-Location (Join-Path $taskProjectRoot 'frontend')
    try {
        & npm.cmd ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
    & $taskPython -m PyInstaller --noconfirm --windowed --onedir --name PixelRegrid-Python `
        --collect-all webview --collect-all clr_loader `
        --add-data 'frontend/dist;frontend/dist' `
        --add-data 'THIRD_PARTY_NOTICES.md;.' `
        --add-data 'LICENSE;.' `
        --add-data 'docs/使用说明.txt;.' python/launch.py
    if ($LASTEXITCODE -ne 0) { throw 'Desktop packaging failed.' }
    Write-Output 'Build complete: dist\PixelRegrid-Python\PixelRegrid-Python.exe'
} finally { Pop-Location }
