param([switch]$UseRustMirror)
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot 'frontend')
try {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm dependency installation failed.' }
    if ($UseRustMirror) {
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
    $taskDestination = Join-Path $PSScriptRoot 'dist\PerfectPixel-JS'
    New-Item -ItemType Directory -Force -Path $taskDestination | Out-Null
    Copy-Item -LiteralPath 'src-tauri\target\release\perfect-pixel-js.exe' -Destination (Join-Path $taskDestination 'PerfectPixel-JS.exe')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'THIRD_PARTY_NOTICES.md') -Destination $taskDestination
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'JAVASCRIPT_PROTOTYPE.md') -Destination $taskDestination
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'JAVASCRIPT_EVALUATION.md') -Destination $taskDestination
    $taskNotices = "--output=$(Join-Path $taskDestination 'RUST_NOTICES.txt')"
    if ($UseRustMirror) { & node scripts/native-notices.mjs --mirror $taskNotices }
    else { & node scripts/native-notices.mjs $taskNotices }
    if ($LASTEXITCODE -ne 0) { throw 'Third-party notice generation failed.' }
    Write-Output "Build complete: $taskDestination\PerfectPixel-JS.exe"
} finally { Pop-Location }
