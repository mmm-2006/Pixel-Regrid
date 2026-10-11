param([string]$ExecutablePath, [switch]$Zip)
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
if ($taskExecutable.VersionInfo.ProductName -ne 'Pixel Regrid' -or $taskExecutable.VersionInfo.ProductVersion -ne $taskVersion) {
    throw "Executable product/version does not match Pixel Regrid $taskVersion. Build it first."
}
$taskName = "PixelRegrid-v$taskVersion-windows-x64-js"
$taskDestination = Join-Path $taskProjectRoot "dist\$taskName.exe"
$taskZip = Join-Path $taskProjectRoot "dist\$taskName.zip"
if ((Test-Path -LiteralPath $taskDestination) -or ($Zip -and (Test-Path -LiteralPath $taskZip))) {
    throw 'Release output already exists. Preserve it or choose a new version before packaging again.'
}
& node (Join-Path $taskProjectRoot 'frontend\scripts\verify-embedded-licenses.mjs') $taskExecutable.FullName
if ($LASTEXITCODE -ne 0) { throw 'Executable must contain complete licenses before publishing.' }
Copy-Item -LiteralPath $taskExecutable.FullName -Destination $taskDestination
$taskOutputs = @($taskDestination)
if ($Zip) {
    Compress-Archive -LiteralPath $taskDestination -DestinationPath $taskZip -CompressionLevel Optimal
    $taskOutputs += $taskZip
}
# Keep checksums for existing packages rather than overwriting their records.
$taskChecksum = Join-Path $taskProjectRoot 'dist\SHA256SUMS.txt'
foreach ($taskOutput in $taskOutputs) {
    $taskHash = (Get-FileHash -LiteralPath $taskOutput -Algorithm SHA256).Hash.ToLowerInvariant()
    "$taskHash  $(Split-Path -Leaf $taskOutput)" | Add-Content -LiteralPath $taskChecksum -Encoding ascii
    Write-Output "Package: $taskOutput ($((Get-Item -LiteralPath $taskOutput).Length) bytes)"
}
Write-Output "Checksum: $taskChecksum"
