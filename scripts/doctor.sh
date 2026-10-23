#!/bin/bash
# Read-only environment check for the K2 Claude Code companion. Never installs or
# starts anything -- just reports, so an installing agent (or a human) knows what's
# missing before running install-macos.sh. Safe to run any number of times.
set -u
ok=1
say() { printf '%-28s %s\n' "$1" "$2"; }

if [[ "$(uname -s)" != "Darwin" ]]; then
  say "OS:" "FAIL - macOS only (this uses AppKit/Cocoa directly, no Windows/Linux support)"
  ok=0
else
  say "OS:" "OK - macOS $(sw_vers -productVersion)"
fi

if command -v python3 >/dev/null 2>&1; then
  say "python3:" "OK - $(python3 --version 2>&1)"
else
  say "python3:" "FAIL - not found (install from python.org or 'brew install python3')"
  ok=0
fi

if command -v node >/dev/null 2>&1; then
  say "node:" "OK - $(node --version)"
else
  say "node:" "FAIL - not found (install from nodejs.org or 'brew install node')"
  ok=0
fi

if python3 -c "import webview" >/dev/null 2>&1; then
  say "pywebview:" "OK - already installed"
else
  say "pywebview:" "missing - install-macos.sh will install it"
fi

if python3 -c "import AppKit" >/dev/null 2>&1; then
  say "pyobjc (AppKit):" "OK - already installed"
else
  say "pyobjc (AppKit):" "missing - install-macos.sh will install it"
fi

PORT="${K2_PET_PORT:-3043}"
if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  say "port $PORT:" "in use - the pet's server may already be running (run.sh is idempotent, safe either way)"
else
  say "port $PORT:" "free"
fi

echo
if [[ "$ok" == "1" ]]; then
  echo "All required tools present. Next: bash scripts/install-macos.sh"
else
  echo "Missing required tools above (marked FAIL). Install those first, then re-run this script."
fi
