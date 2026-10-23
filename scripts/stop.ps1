# Stops the running K2 companion (server + floating window) on Windows. Does not
# uninstall any Python packages install-windows.ps1 installed -- just ends the
# two local processes run.ps1 starts. Safe to run even if nothing is running.
#
# UNTESTED on a real Windows machine.

$Port = 3043

Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}

Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*k2-pet-floating-window.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "Stopped (if it was running)."
