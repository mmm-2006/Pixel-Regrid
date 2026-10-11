param([switch]$UseRustMirror)
$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $taskProjectRoot 'frontend')
try {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm dependency installation failed.' }
    if ($UseRustMirror) {
        & npm.cmd run licenses -- --mirror
        if ($LASTEXITCODE -ne 0) { throw 'Embedded license generation failed.' }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
        Push-Location src-tauri
        try {
            & cargo --config 'source.crates-io.replace-with="rsproxy"' --config 'source.rsproxy.registry="sparse+https://rsproxy.cn/index/"' build --locked --release --features custom-protocol
            if ($LASTEXITCODE -ne 0) { throw 'Native build failed.' }
        } finally { Pop-Location }
    } else {
        & npm.cmd run desktop:build
        if ($LASTEXITCODE -ne 0) { throw 'Native build failed.' }
    }
    $taskDestination = Join-Path $taskProjectRoot 'dist\PixelRegrid-JS'
    New-Item -ItemType Directory -Force -Path $taskDestination | Out-Null
    Copy-Item -LiteralPath 'src-tauri\target\release\pixel-regrid.exe' -Destination (Join-Path $taskDestination 'PixelRegrid-JS.exe')
    & node scripts/verify-embedded-licenses.mjs (Join-Path $taskDestination 'PixelRegrid-JS.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Single-EXE license verification failed.' }
    Write-Output "Build complete: $taskDestination\PixelRegrid-JS.exe"
} finally { Pop-Location }
