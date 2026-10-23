#!/bin/bash
# K2 Pet installer (macOS). Installs the Claude-agnostic core, and -- only if asked --
# the Claude Code connector (hooks + Mods plugin) merged into ~/.claude/settings.json.
#
#   bash install.sh                 interactive: asks whether to add the Claude connector
#   bash install.sh --core-only     core app only, never touches ~/.claude
#   bash install.sh --with-claude   core + Claude connector
#   bash install.sh --uninstall     remove K2's entries from ~/.claude/settings.json
#   bash install.sh --dry-run       show what would change, change nothing
#
# The project is used in place (the Claude Mods plugin resolves sprites relative to
# this checkout), so keep the folder where you want it before installing; if you move
# it, re-run this script and it repoints everything.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE=""            # core | claude
ACTION="install"   # install | uninstall
DRY=0

for arg in "$@"; do
  case "$arg" in
    --core-only)   MODE=core ;;
    --with-claude) MODE=claude ;;
    --uninstall)   ACTION=uninstall ;;
    --dry-run)     DRY=1 ;;
    -h|--help)     sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
step() { printf '\n-> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

connect_claude() {  # $1 = install|uninstall ; returns python's exit code
  ROOT="$ROOT" ACTION="$1" DRY="$DRY" python3 - <<'PYEOF'
import json, os, pathlib, shlex, shutil, sys, tempfile, time

root = os.environ["ROOT"]
action = os.environ["ACTION"]
dry = os.environ["DRY"] == "1"
integ = f"{root}/claude-code-integration"
autostart = f"{integ}/k2-pet-claude-code-autostart.sh"
emit = f"{integ}/k2-pet-claude-code-emit.sh"
plugin_dir = f"{integ}/k2-pet-mod"
OURS = {os.path.basename(autostart), os.path.basename(emit)}

path = pathlib.Path.home() / ".claude" / "settings.json"
raw = path.read_text() if path.exists() else ""
if raw.strip():
    try:
        settings = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"   {path} is not valid JSON ({e}). Not touching it -- fix or move it, then re-run.")
        sys.exit(3)
    if not isinstance(settings, dict):
        print(f"   {path} is not a JSON object. Not touching it.")
        sys.exit(3)
else:
    settings = {}

def exe(cmd):
    try:
        return shlex.split(cmd)[0]
    except Exception:
        return cmd

wiring = {"SessionStart": autostart}
for ev in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
           "PermissionRequest", "Stop", "StopFailure", "Notification"):
    wiring[ev] = emit

log = []
hooks = settings.get("hooks")
if hooks is not None and not isinstance(hooks, dict):
    print("   'hooks' in settings.json is not an object. Not touching it.")
    sys.exit(3)

if action == "install":
    hooks = settings.setdefault("hooks", {})
    for event, script in wiring.items():
        groups = hooks.setdefault(event, [])
        exact = False
        repointed = False
        for g in groups:
            for h in g.get("hooks", []):
                cmd = h.get("command", "")
                if exe(cmd) == script:
                    exact = True
                elif os.path.basename(exe(cmd)) == os.path.basename(script):
                    h["command"] = shlex.quote(script)  # same K2 script from an old location
                    repointed = True
        if exact:
            log.append(f"   hook {event}: already correct")
        elif repointed:
            log.append(f"   hook {event}: repointed from an old K2 copy")
        else:
            groups.append({"hooks": [{"type": "command", "command": shlex.quote(script), "async": True}]})
            log.append(f"   hook {event}: added")

    env = settings.setdefault("env", {})
    cur = env.get("CLAUDE_CODE_PLUGIN_DIRS")
    if cur is None:
        env["CLAUDE_CODE_PLUGIN_DIRS"] = plugin_dir
        log.append("   env CLAUDE_CODE_PLUGIN_DIRS: set to K2 Mods plugin")
    elif cur == plugin_dir:
        log.append("   env CLAUDE_CODE_PLUGIN_DIRS: already correct")
    else:
        log.append(f"   env CLAUDE_CODE_PLUGIN_DIRS: already set to {cur!r} -- NOT changed")
        log.append(f"      to add the in-Claude pane too, add {plugin_dir} to that value yourself")
else:
    if hooks:
        for event in list(hooks):
            kept = []
            for g in hooks[event]:
                hs = [h for h in g.get("hooks", []) if exe(h.get("command", "")) not in {autostart, emit}]
                if len(hs) != len(g.get("hooks", [])):
                    log.append(f"   hook {event}: removed K2 entry")
                if hs:
                    g["hooks"] = hs
                    kept.append(g)
                elif not g.get("hooks"):
                    kept.append(g)
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
        if not hooks:
            del settings["hooks"]
    env = settings.get("env")
    if isinstance(env, dict) and env.get("CLAUDE_CODE_PLUGIN_DIRS") == plugin_dir:
        del env["CLAUDE_CODE_PLUGIN_DIRS"]
        log.append("   env CLAUDE_CODE_PLUGIN_DIRS: removed")
        if not env:
            del settings["env"]
    if not log:
        log.append("   nothing of K2's found in settings.json")

print("\n".join(log))
new = json.dumps(settings, indent=2) + "\n"
if new == raw:
    print("   settings.json unchanged")
elif dry:
    print(f"   (dry run) would write {path}")
else:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(f"settings.json.k2-backup-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
        print(f"   backup: {backup}")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings.k2-", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(new)
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)
    json.loads(path.read_text())  # verify what we wrote parses
    print(f"   wrote {path}")
PYEOF
}

# ---------------------------------------------------------------- uninstall
if [[ "$ACTION" == "uninstall" ]]; then
  step "Removing K2's entries from ~/.claude/settings.json (everything else is left alone)"
  command -v python3 >/dev/null 2>&1 || fail "python3 not found"
  connect_claude uninstall
  bash "$ROOT/scripts/stop.sh" >/dev/null 2>&1 || true
  say ""
  say "Done. K2 is stopped and unhooked. The Python packages (pywebview, pyobjc) were left"
  say "installed; remove them with: python3 -m pip uninstall pywebview pyobjc-core pyobjc-framework-Cocoa"
  exit 0
fi

# ---------------------------------------------------------------- preflight
say "K2 Pet installer"
say "================"
step "Checking your Mac"
[[ "$(uname -s)" == "Darwin" ]] || fail "macOS only (the floating window uses AppKit). Windows has scripts/*.ps1 (untested)."
say "   macOS $(sw_vers -productVersion), $(uname -m)"

command -v node >/dev/null 2>&1 || fail "node not found. Install Node.js 18+ (https://nodejs.org or 'brew install node'), then re-run."
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[[ "$NODE_MAJOR" -ge 18 ]] || fail "node $(node --version) is too old; need 18+."
say "   node $(node --version)"

command -v python3 >/dev/null 2>&1 || fail "python3 not found. Install Python 3.9+ (https://python.org or 'brew install python3'), then re-run."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || fail "$(python3 --version) is too old; need 3.9+."
say "   $(python3 --version)"

[[ -f "$ROOT/src/server.mjs" && -f "$ROOT/claude-code-integration/k2-pet-floating-window.py" ]] \
  || fail "run this from inside the K2 project folder (src/server.mjs not found next to install.sh)"
[[ -f "$ROOT/public/vendor/kk2.js" ]] || say "   note: public/vendor/ (K2 Voice Link engine) is missing from this checkout; the pet will use the 'say' voice only."

# ---------------------------------------------------------------- core deps
step "Python dependencies (pywebview, pyobjc)"
if python3 -c 'import webview, AppKit' >/dev/null 2>&1; then
  say "   already installed"
elif [[ "$DRY" == "1" ]]; then
  say "   (dry run) would run: python3 -m pip install --user -r requirements.txt"
else
  # Measured on a clean machine 2026-10-23: pyobjc-core has no prebuilt wheel for
  # every Python/arch combination and compiles from source when it has to, which
  # took several minutes. Saying "a minute" makes a working install look hung.
  say "   installing pywebview + pyobjc. This can take several minutes the first"
  say "   time (pyobjc may compile from source). pip warnings below are normal."
  if ! python3 -m pip install --user -r "$ROOT/requirements.txt"; then
    fail "pip install failed. If you see 'externally-managed-environment', use a venv:
  python3 -m venv ~/.k2-pet-venv && ~/.k2-pet-venv/bin/pip install -r requirements.txt
  then run this installer with ~/.k2-pet-venv/bin first on PATH."
  fi
  python3 -c 'import webview, AppKit' || fail "installed, but 'import webview, AppKit' still fails -- check the pip output above."
  say "   installed"
fi

chmod +x "$ROOT"/scripts/*.sh "$ROOT"/claude-code-integration/*.sh "$ROOT"/claude-code-integration/*.py "$ROOT"/claude-code-integration/*.command 2>/dev/null || true

# ---------------------------------------------------------------- voice
step "Voice"
say "   macOS 'say' fallback: $(command -v say >/dev/null 2>&1 && echo available || echo MISSING)"
if [[ "$(uname -m)" == "arm64" ]]; then
  say "   Apple Silicon: Kokoro (MLX) is possible, but its server is not part of this project;"
  say "   if you already run one on :8880 the pet will use it automatically."
else
  say "   Intel Mac: Kokoro (needs Apple Silicon/MLX) is not available; the pet uses K2 Voice Link / 'say'."
fi
for p in 8880 8883; do
  lsof -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 && say "   detected a voice server already listening on :$p"
done

# ---------------------------------------------------------------- smoke test
step "Smoke test (temporary server on a spare port, nothing left running)"
if [[ "$DRY" == "1" ]]; then
  say "   (dry run) skipped"
else
  TEST_PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
  LOG="$(mktemp -t k2-install-smoke)"
  (cd "$ROOT" && PORT="$TEST_PORT" exec node src/server.mjs >"$LOG" 2>&1) &
  SRV=$!
  trap 'kill $SRV 2>/dev/null || true' EXIT
  ok=0
  for _ in $(seq 1 20); do
    if curl -fs -m 1 "http://127.0.0.1:$TEST_PORT/state" >/dev/null 2>&1; then ok=1; break; fi
    sleep 0.25
  done
  [[ "$ok" == "1" ]] || { cat "$LOG" >&2; fail "server did not start; log above."; }
  curl -fs -m 2 -X POST "http://127.0.0.1:$TEST_PORT/ingest" -H 'Content-Type: application/json' \
    -d '{"method":"turn/started","cwd":"/tmp/k2-install-smoke"}' >/dev/null || fail "/ingest rejected an event"
  STATE="$(curl -fs -m 2 "http://127.0.0.1:$TEST_PORT/state")"
  say "   server up; sent a test event; /state -> ${STATE:0:120}"
  curl -fs -m 2 -o /dev/null "http://127.0.0.1:$TEST_PORT/companion.html" || fail "companion.html not served"
  say "   companion.html served"
  kill $SRV 2>/dev/null || true; wait $SRV 2>/dev/null || true; trap - EXIT
fi

# ---------------------------------------------------------------- claude connector
if [[ -z "$MODE" ]]; then
  if [[ -t 0 && "$DRY" == "0" ]]; then
    printf '\nAlso connect this to Claude Code (edits ~/.claude/settings.json, with a backup)? [y/N] '
    read -r reply || reply=""
    [[ "$reply" =~ ^[Yy] ]] && MODE=claude || MODE=core
  else
    MODE=core
    say ""
    say "(no terminal to ask on; installing core only. Add --with-claude to connect Claude Code.)"
  fi
fi

CLAUDE_RC=0
if [[ "$MODE" == "claude" ]]; then
  step "Claude Code connector"
  connect_claude install || CLAUDE_RC=$?
fi

# ---------------------------------------------------------------- done
say ""
[[ "$DRY" == "1" ]] || say "Core install complete."
if [[ "$MODE" == "claude" && "$CLAUDE_RC" == "0" && "$DRY" == "1" ]]; then
  say "(dry run: nothing was changed)"
elif [[ "$MODE" == "claude" && "$CLAUDE_RC" == "0" ]]; then
  say "Claude connector installed. Open or restart Claude Code; K2 starts itself with each session."
elif [[ "$MODE" == "claude" ]]; then
  say "Claude connector NOT installed (see above). Core still works."
else
  say "Claude connector not installed. Add it any time: bash install.sh --with-claude"
fi
say "Start the pet now:  bash scripts/run.sh     Stop it:  bash scripts/stop.sh"
say "Any tool can drive it by POSTing JSON events to http://127.0.0.1:3043/ingest"
say "First launch may show a macOS prompt from pywebview/PyObjC; K2 itself needs no Accessibility,"
say "Screen Recording, or microphone permission."
exit "$CLAUDE_RC"
