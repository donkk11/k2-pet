# Install K2 Pet (macOS)

K2 is a small floating companion that sits on top of your windows. This installs the
real native app: a local server, the floating window, the sprites and the voice.
Connecting it to Claude Code is optional.

## Before you start

You need a Mac with **Node.js 18+** and **Python 3.9+** already installed.
Check in Terminal:

    node --version
    python3 --version

If either is missing, install it first (https://nodejs.org, https://python.org, or
`brew install node python3`). The installer will stop and tell you if something is missing.

## Install

Open Terminal, then paste these one line at a time (do not add comments):

    cd /Users/Shared/k2-pet
    bash install.sh --core-only

It checks your Mac, installs two Python packages (pywebview, pyobjc) for your user only
(no sudo), and does a quick self-test. It does not touch any Claude settings.

## Start and stop

    bash scripts/run.sh

The floating window should appear on screen. To stop it:

    bash scripts/stop.sh

If a macOS permission prompt appears on first launch, allow it. K2 itself does not need
Accessibility, Screen Recording or microphone access.

## Port already in use? Pick another

K2 uses port 3043 by default. If something else (for example another user's K2 on the
same Mac) already has it, set `K2_PET_PORT` to any free port, in the same Terminal, before
starting and stopping:

    export K2_PET_PORT=3053
    bash scripts/run.sh

Later, in that same Terminal, `bash scripts/stop.sh` stops only that one.

## Check it is alive

    curl http://127.0.0.1:${K2_PET_PORT:-3043}/state

You should get a line of JSON starting with `{"state":`.

## Optional: connect Claude Code

Only if Claude Code is installed on this account:

    bash install.sh --with-claude

This adds K2's hooks to `~/.claude/settings.json`. It keeps everything already in that
file and saves a backup next to it first. Restart Claude Code afterwards.

To preview without changing anything: add `--dry-run`.

## Remove

    bash install.sh --uninstall

This stops K2 and removes only K2's entries from `~/.claude/settings.json`. The Python
packages stay; the command to remove them is printed at the end.

## If something goes wrong

- Copy the exact error text; do not paraphrase it.
- Logs: `~/Library/Logs/K2Pet/server.log` and `~/Library/Logs/K2Pet/window.log`.
- `error: externally-managed-environment` means your Python is managed by Homebrew; the
  installer prints the venv commands to use instead.
- Voice: K2 speaks with the built-in macOS `say` voice by default. Better voices
  (Kokoro on Apple Silicon) are only used if you already run their server on this Mac.
