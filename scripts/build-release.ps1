<# Build the Windows installer: frozen backend + production UI + Electron main -> apps\desktop\release\ZONIC M4 Setup x.y.z.exe #>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
# & "$root\scripts\test.ps1"
# if ($LASTEXITCODE -ne 0) { throw "Tests failed; not building a release." }
& "$root\scripts\build-backend.ps1"
Set-Location "$root\apps\desktop"
npm run dist
Write-Host "Installer written to apps\desktop\release\"
