# Claude Code integration

Wires the same K2 companion (built for Codex in this repo) into the Claude Code
desktop app instead, driven by Claude Code's own real hooks rather than Codex's
app-server event stream.

## Setup

```bash
./install.sh
```

Checks for Node/Python, installs `pywebview`/`pyobjc` if missing, and wires the 9
required hooks into `~/.claude/settings.json` — merging in only K2's own entries,
never touching anything else already in that file. Safe to re-run: it won't duplicate
entries, and if it finds an older copy of a K2 script already wired in from a previous
install, it repoints that entry to this copy instead of leaving a stale duplicate that
would fire twice. macOS only for now. Restart Claude Code afterward.

- `k2-pet-claude-code-emit.sh` — a Claude Code hook script. Reads the hook's JSON
  payload from stdin and posts it to the SSE server (`../src/server.mjs`) in the
  same event vocabulary `state-mapper.mjs` understands. Wired to `UserPromptSubmit`,
  `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `Stop`,
  `StopFailure`, `Notification` in `~/.claude/settings.json`. Also extracts a real
  activity caption straight from the hook's own `tool_input` (a Bash call's real
  `description`, an Edit's real `file_path`, a search's real `query`) for the
  live-activity card in `companion.js` -- never fabricated, absent when the hook
  didn't supply one.
- `k2-pet-claude-code-autostart.sh` — a `SessionStart` hook. Starts the SSE server
  and the floating window on their own, idempotently, the moment a Claude Code
  session begins -- no manual command needed.
- `k2-pet-floating-window.py` — a small borderless, always-on-top, transparent
  pywebview window that loads `../public/companion.html`. Real, verified fixes in
  here, found through direct extraction and reading of the real installed Codex
  app's own Electron bundle:
  1. Re-asserts NSWindow transparency in case a reload resets it.
  2. `NSApplicationActivationPolicyAccessory` + `setCollectionBehavior_`
     (`CanJoinAllSpaces | FullScreenAuxiliary`) — this call reliably
     hard-crashed (SIGTRAP) when called synchronously inside the `events.shown`
     callback; dispatching it through `PyObjCTools.AppHelper.callAfter` (pywebview's
     own main-run-loop dispatcher) fixed it.
  3. **Real cross-full-screen-Space visibility** (the pet following you when you
     three-finger-swipe to another full-screen app): `collectionBehavior` alone
     was not enough, despite reading back as correctly applied. The actual fix is
     replacing pywebview's `WindowHost` (a plain `NSWindow`) with a custom
     `NSPanel` subclass carrying `NSWindowStyleMaskNonactivatingPanel` -- the same
     mechanism Spotlight uses, and what Codex's own Electron pet window relies on
     under the hood. A private `_setPreventsActivation` property was tried first
     and rejected: on a plain `NSWindow` it blocked mouse events outright (a
     poll-based drag never even started), which is why the real `NSPanel` rebuild
     was necessary instead of a one-line property tweak.
  4. **Drag** works via pywebview's native `easy_drag`, which needed the `NSPanel`
     rebuild above to coexist with the accessory/non-activating setup.
  5. **Click-through pass-through**: `NSWindow.ignoresMouseEvents`, toggled by
     polling `NSEvent.mouseLocation()` against a hot-zone rect that `companion.js`
     measures live (`Api.update_hot_rect`, real `getBoundingClientRect()` per pose,
     not a fixed percentage) — so clicks pass through empty space around him to
     whatever's underneath, and only register on his actual visible silhouette
     plus the floor's buttons.
  6. `Api.focus_claude_code()` — brings the real Claude Code app forward via a
     plain `osascript activate` call. This is the real send mechanism now (see
     below), not text/keystroke injection.
- `12_K2_Claude_Code_Pet.command` — manual launcher for KK's own Launcher Hub
  dashboard (a separate, already-existing local tool); not needed for normal use
  since the `SessionStart` hook starts everything on its own.

## How sending a message actually works (real, current, tested)

Text injection into Claude Code's own inbox socket was tried, verified end-to-end at
the protocol level (the exact documented auth-line + message format), and then
verified in real use to *not* reliably land as a visible message -- Claude Code's
"own-child" trust model is described for a hook script acting while genuinely live,
not a persistent relay process reusing a captured socket path later. Rather than keep
fighting an internal, thinly-documented protocol, the real, shipped mechanism is
simpler and fully reliable: compose text copies to the clipboard and
`focus_claude_code()` brings the real window forward, so you paste it in yourself.
Double-clicking the character, or clicking the alert bubble, do the same -- bring
Claude Code forward, nothing more exotic. No OS Accessibility APIs anywhere in this
project.
