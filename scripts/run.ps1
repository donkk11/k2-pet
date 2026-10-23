# Starts the K2 companion (local server + floating window) on Windows. Idempotent
# -- safe to run again if it's already running, does nothing in that case. This
# is the Windows counterpart to claude-code-integration/k2-pet-claude-code-autostart.sh
# (that script is bash-only and won't run natively on Windows).
#
# UNTESTED on a real Windows machine. In particular: pywebview's Windows backend
# (EdgeChromium) has not been confirmed here to actually honor frameless/on_top/
# transparent/easy_drag the same way the macOS Cocoa backend does -- the base
# window may appear, but with rougher edges (a visible background box, chrome
# that doesn't fully hide, etc.) than the polished macOS version. That's expected
# to need a real follow-up pass once someone reports what it actually looks like.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$Port = 3043

$portInUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $portInUse) {
    Push-Location $RootDir
    $env:PORT = "$Port"
    Start-Process -FilePath "node" -ArgumentList "src\server.mjs" -WindowStyle Hidden `
        -RedirectStandardOutput "$env:TEMP\k2-pet-server-code.log" `
        -RedirectStandardError "$env:TEMP\k2-pet-server-code.err.log"
    Pop-Location
    Start-Sleep -Seconds 1
}

$running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*k2-pet-floating-window.py*$Port*" }
if (-not $running) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
    Push-Location $ScriptDir\..\claude-code-integration
    Start-Process -FilePath $python.Source `
        -ArgumentList "-u", "k2-pet-floating-window.py", "http://127.0.0.1:$Port/companion.html", "K2 - Claude Code" `
        -WindowStyle Hidden `
        -RedirectStandardOutput "$env:TEMP\k2-pet-code.log" `
        -RedirectStandardError "$env:TEMP\k2-pet-code.err.log"
    Pop-Location
}

Write-Host "Started (or already running). Logs: `$env:TEMP\k2-pet-server-code.log and k2-pet-code.log"
