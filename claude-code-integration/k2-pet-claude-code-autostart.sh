#!/bin/bash
# Auto-starts the K2 Claude Code pet (SSE server + floating window) on SessionStart,
# idempotently -- does nothing if either piece is already running. This is the real
# answer to "does it start automatically or do I have to run something": yes, it
# starts itself the moment a Claude Code session begins, no manual command needed.
set -u

# Real portability fix: this used to hardcode KK's own personal Nimba folder path to
# find k2-pet-floating-window.py -- for anyone else cloning this repo, that folder
# doesn't exist, so their pet would silently never launch. Self-locating instead: this
# script and k2-pet-floating-window.py live side by side in claude-code-integration/,
# and PET_DIR (k2-extended-pet-states/, one level up) is where server.mjs actually
# lives -- both derived from where THIS script actually is, not one machine's layout.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PET_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PORT="${K2_PET_PORT:-3043}"
# Per-user log dir: a fixed /tmp path is owned by whichever user ran first, so a second
# user on the same Mac got "Permission denied" and the pet never started.
LOG_DIR="$HOME/Library/Logs/K2Pet"
mkdir -p "$LOG_DIR"

if ! lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  (cd "$PET_DIR" && PORT="$PORT" nohup node src/server.mjs >"$LOG_DIR/server.log" 2>&1 &)
  sleep 1
fi

if ! pgrep -f "k2-pet-floating-window.py.*:$PORT" >/dev/null 2>&1; then
  (cd "$SCRIPT_DIR" && nohup python3 -u k2-pet-floating-window.py "http://127.0.0.1:$PORT/companion.html" "K2 — Claude Code" >"$LOG_DIR/window.log" 2>&1 &)
fi

exit 0
