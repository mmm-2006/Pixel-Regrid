param([string]$ExecutablePath)
$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskConfig = Get-Content -LiteralPath (Join-Path $taskProjectRoot 'frontend\src-tauri\tauri.conf.json') -Raw | ConvertFrom-Json
$taskPackage = Get-Content -LiteralPath (Join-Path $taskProjectRoot 'frontend\package.json') -Raw | ConvertFrom-Json
$taskVersion = $taskConfig.version
if ($taskVersion -notmatch '^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?$' -or $taskPackage.version -ne $taskVersion) {
    throw 'Frontend and desktop versions must agree.'
}
if (-not $ExecutablePath) { $ExecutablePath = Join-Path $taskProjectRoot 'dist\PixelRegrid-JS\PixelRegrid-JS.exe' }
$taskExecutable = Get-Item -LiteralPath $ExecutablePath
if ($taskExecutable.VersionInfo.ProductName -ne 'Pixel Regrid' -or
    $taskExecutable.VersionInfo.ProductVersion -ne $taskVersion) {
    throw "Executable product/version does not match Pixel Regrid $taskVersion. Build it first."
}
$taskName = "PixelRegrid-v$taskVersion-windows-x64-js"
$taskDestination = Join-Path $taskProjectRoot "dist\$taskName"
$taskZip = "$taskDestination.zip"
if ((Test-Path -LiteralPath $taskDestination) -or (Test-Path -LiteralPath $taskZip)) {
    throw 'Release output already exists. Preserve it or choose a new version before packaging again.'
}
$taskNotices = Join-Path $taskProjectRoot 'dist\PixelRegrid-JS\RUST_NOTICES.txt'
$taskReleaseNotes = Join-Path $taskProjectRoot "docs\releases\v$taskVersion.md"
$taskValidation = Join-Path $taskProjectRoot 'docs\RELEASE_VALIDATION.md'
foreach ($taskRequired in @($taskNotices, $taskReleaseNotes, $taskValidation)) {
    if (-not (Test-Path -LiteralPath $taskRequired -PathType Leaf)) { throw "Missing release material: $taskRequired" }
}
New-Item -ItemType Directory -Path (Join-Path $taskDestination 'docs\releases') -Force | Out-Null
Copy-Item -LiteralPath $taskExecutable.FullName -Destination (Join-Path $taskDestination 'PixelRegrid-JS.exe')
foreach ($taskFile in @('LICENSE', 'THIRD_PARTY_NOTICES.md')) {
    Copy-Item -LiteralPath (Join-Path $taskProjectRoot $taskFile) -Destination $taskDestination
}
Copy-Item -LiteralPath $taskNotices -Destination $taskDestination
foreach ($taskFile in @('使用说明.txt', 'JAVASCRIPT_PROTOTYPE.md', 'JAVASCRIPT_EVALUATION.md', 'RELEASE_VALIDATION.md')) {
    Copy-Item -LiteralPath (Join-Path $taskProjectRoot "docs\$taskFile") -Destination (Join-Path $taskDestination 'docs')
}
Copy-Item -LiteralPath $taskReleaseNotes -Destination (Join-Path $taskDestination 'docs\releases')
$taskReadme = @"
Pixel Regrid v$taskVersion (Windows x64 / JavaScript)

解压后双击 PixelRegrid-JS.exe。需要 Microsoft Edge WebView2 Runtime。
无需安装 Python 或 Node.js。Python 版本仍保留在项目源码中。

使用说明：docs/使用说明.txt
版本说明：docs/releases/v$taskVersion.md
测试记录：docs/RELEASE_VALIDATION.md
源代码：https://github.com/mmm-2006/Pixel-Regrid
许可证：LICENSE、THIRD_PARTY_NOTICES.md、RUST_NOTICES.txt
"@
$taskReadme | Set-Content -LiteralPath (Join-Path $taskDestination 'README.txt') -Encoding utf8
Compress-Archive -Path (Join-Path $taskDestination '*') -DestinationPath $taskZip -CompressionLevel Optimal
$taskHash = (Get-FileHash -LiteralPath $taskZip -Algorithm SHA256).Hash.ToLowerInvariant()
$taskChecksum = Join-Path $taskProjectRoot 'dist\SHA256SUMS.txt'
"$taskHash  $taskName.zip" | Set-Content -LiteralPath $taskChecksum -Encoding ascii
Write-Output "Package: $taskZip"
Write-Output "Checksum: $taskChecksum"
Write-Output "ZIP size: $((Get-Item -LiteralPath $taskZip).Length) bytes"
