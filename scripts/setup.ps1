<#
  One-time setup for development on Windows 10/11.
  Prerequisites: Python 3.12 (python.org or `winget install Python.Python.3.12`) and Node.js 20+ (LTS).
  Usage (from the repo root):  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Need($cmd, $hint) { if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd was not found. $hint" } }
Need "node" "Install Node.js 20+ LTS from https://nodejs.org"
Need "npm" "Install Node.js 20+ LTS from https://nodejs.org"

# Prefer the py launcher so we get 3.12 even if another Python is first on PATH.
$pyExe = "python"; $pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
  & py -3.12 --version *> $null
  if ($LASTEXITCODE -eq 0) { $pyExe = "py"; $pyArgs = @("-3.12") }
}
if ($pyExe -eq "python") { Need "python" "Install Python 3.12 from https://www.python.org/downloads/" }
$ver = (& $pyExe @pyArgs --version) 2>&1
Write-Host "Using $ver"
if ($ver -notmatch "3\.1[2-9]") { throw "Python 3.12 or newer is required (found: $ver)." }

Write-Host "== Backend virtual environment =="
if (-not (Test-Path "backend\.venv\Scripts\python.exe")) { & $pyExe @pyArgs -m venv backend\.venv }
& backend\.venv\Scripts\python.exe -m pip install --upgrade pip
& backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt

Write-Host "== Desktop app dependencies =="
Set-Location apps\desktop
npm install --no-audit --no-fund

Write-Host ""
Write-Host "Setup complete. Start the app with:  powershell -File scripts\dev.ps1"
