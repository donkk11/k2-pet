#!/bin/bash
# Starts the K2 companion (local server + floating window). Idempotent -- safe to
# run again if it's already running, does nothing in that case. This execs the
# same real script the Claude Code session-start hook calls, so there is exactly
# one launch path to test and trust, not two copies that could quietly drift
# apart from each other.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/../claude-code-integration/k2-pet-claude-code-autostart.sh"
