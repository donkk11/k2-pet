#!/bin/bash
# Installs the Python dependencies the K2 companion needs (pywebview + pyobjc).
# Does not touch Node packages -- server.mjs only uses Node's built-in modules,
# there is nothing to npm install. Does not request, and the companion does not
# need, any macOS privacy permission (Accessibility / microphone / Screen
# Recording) -- it's a plain floating window, none of that is used to show it.
set -eu
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install it first (python.org or 'brew install python3'), then re-run this script." >&2
  exit 1
fi
if ! command -v node >/dev/null 2>&1; then
  echo "node not found. Install it first (nodejs.org or 'brew install node'), then re-run this script." >&2
  exit 1
fi

echo "Installing Python dependencies from requirements.txt (--user, no sudo, nothing system-wide)..."
python3 -m pip install --user -r "$ROOT_DIR/requirements.txt"

echo
echo "Done. Next: bash scripts/run.sh"
