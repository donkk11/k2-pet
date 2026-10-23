#!/bin/bash
# Stops the running K2 companion (server + floating window). Does not uninstall
# any Python packages install-macos.sh installed -- just ends the two local
# processes run.sh starts. Safe to run even if nothing is currently running.
set -u
PORT="${K2_PET_PORT:-3043}"
lsof -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | xargs -r kill
pkill -f "k2-pet-floating-window.py.*:$PORT/" 2>/dev/null
echo "Stopped (if it was running)."
