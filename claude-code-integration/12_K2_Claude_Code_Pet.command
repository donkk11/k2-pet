#!/bin/zsh
set -e
# Real fix (2026-10-11): self-locating, points at the canonical script (see
# git history for the full story on the stale-duplicate bug this replaced).
#
# Real fix (2026-10-14, KK caught this live): this had NO idempotency check
# at all -- running it a second time (e.g. from Launcher Hub while the
# SessionStart autostart copy was already up) started a real second floating
# window AND a real second server.mjs process. The server now fails loudly on
# a port conflict instead of silently doing something else (see server.mjs's
# own real error handler), but this script shouldn't even try in the first
# place if the real thing is already running -- same real check
# autostart.sh already used, just never applied here too.
SCRIPT_DIR="$(cd "$(dirname "${(%):-%x}")" && pwd)"
PET_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PORT=3043

if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "K2 Pet is already running on :$PORT (server + window). Not starting a second one."
  echo "If you want to restart it, stop the existing one first (Launcher Hub's Stop, or: kill \$(lsof -ti :$PORT))."
  exit 0
fi

echo "Starting K2 Claude Code Pet -- SSE server on :$PORT + floating companion window."
cd "$SCRIPT_DIR"
python3 -u k2-pet-floating-window.py "http://127.0.0.1:$PORT/companion.html" "K2 — Claude Code" &
cd "$PET_DIR"
PORT="$PORT" exec node src/server.mjs
