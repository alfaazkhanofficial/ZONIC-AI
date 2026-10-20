<# Start ZONIC M4 in development mode: Vite dev server + Electron (which launches and supervises the Python backend). #>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$root\backend\.venv\Scripts\python.exe")) { throw "Run scripts\setup.ps1 first." }
if (-not (Test-Path "$root\apps\desktop\node_modules")) { throw "Run scripts\setup.ps1 first." }
Set-Location "$root\apps\desktop"
npm run dev
