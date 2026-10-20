<#
  Freeze the Python backend into backend\dist\zonic-backend\ with PyInstaller (no Python needed on the target PC).
  The installer build (build-release.ps1) bundles this folder next to the app.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --quiet pyinstaller
& $py -m PyInstaller --noconfirm --clean --onedir --name zonic-backend `
  --collect-submodules uvicorn --collect-submodules keyring.backends --collect-all google.genai `
  --hidden-import websockets --hidden-import app.main `
  run_backend.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Write-Host "Built backend\dist\zonic-backend\zonic-backend.exe"
