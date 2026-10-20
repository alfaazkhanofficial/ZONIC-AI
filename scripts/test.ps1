<# Run every automated test that works on a normal Windows machine (no display automation needed). #>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"
& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location "$root\apps\desktop"
npm run typecheck
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm test
exit $LASTEXITCODE
