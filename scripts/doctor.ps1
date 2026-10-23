# Read-only environment check for the K2 companion on Windows. Never installs or
# starts anything -- just reports, so an installing agent (or a human) knows what's
# missing before running install-windows.ps1. Safe to run any number of times.
#
# UNTESTED: written from pywebview's documented Windows behavior, not verified on
# a real Windows machine by whoever wrote this. If something here is wrong (a
# wrong flag, a check that doesn't fire), that's real and worth reporting back --
# say so plainly rather than assuming it must be a local setup problem.

$ok = $true

function Say($label, $value) {
    Write-Host ("{0,-28} {1}" -f $label, $value)
}

Say "OS:" "$([System.Environment]::OSVersion.VersionString)"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if ($python) {
    $ver = & $python.Source --version 2>&1
    Say "python:" "OK - $ver"
} else {
    Say "python:" "FAIL - not found (install from python.org, check 'Add to PATH' during setup)"
    $ok = $false
}

$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $ver = & node --version
    Say "node:" "OK - $ver"
} else {
    Say "node:" "FAIL - not found (install from nodejs.org)"
    $ok = $false
}

if ($python) {
    & $python.Source -c "import webview" 2>$null
    if ($LASTEXITCODE -eq 0) { Say "pywebview:" "OK - already installed" }
    else { Say "pywebview:" "missing - install-windows.ps1 will install it" }
}

$portInUse = Get-NetTCPConnection -LocalPort 3043 -State Listen -ErrorAction SilentlyContinue
if ($portInUse) {
    Say "port 3043:" "in use - the pet's server may already be running (run.ps1 is idempotent, safe either way)"
} else {
    Say "port 3043:" "free"
}

Write-Host ""
if ($ok) {
    Write-Host "All required tools present. Next: powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1"
} else {
    Write-Host "Missing required tools above (marked FAIL). Install those first, then re-run this script."
}
