# Installs the Python dependencies the K2 companion needs on Windows (pywebview
# only -- the pyobjc packages in requirements.txt are macOS-only and are skipped
# automatically via their environment marker). Does not touch Node packages --
# server.mjs only uses Node's built-in modules. Does not request any Windows
# permission prompt.
#
# UNTESTED on a real Windows machine -- report back exactly what happens if this
# doesn't work as described.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) {
    Write-Error "python not found. Install it from python.org first, then re-run this script."
    exit 1
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "node not found. Install it from nodejs.org first, then re-run this script."
    exit 1
}

Write-Host "Installing Python dependencies from requirements.txt (--user, nothing system-wide)..."
& $python.Source -m pip install --user -r "$RootDir\requirements.txt"

Write-Host ""
Write-Host "Done. Next: powershell -ExecutionPolicy Bypass -File scripts\run.ps1"
