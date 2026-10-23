#!/bin/bash
# Kept for old instructions; the real installer is install.sh at the project root.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/install.sh" --with-claude "$@"
