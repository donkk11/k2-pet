#!/bin/bash
# Emits Claude Code hook lifecycle events to the K2 pet companion server (port 3043)
# in the exact event vocabulary k2-extended-pet-states/src/state-mapper.mjs understands.
# Reads the hook's JSON payload from stdin (Claude Code hooks always provide this).
set -uo pipefail
PET_PORT="${K2_PET_PORT:-3043}"
ENDPOINT="http://127.0.0.1:$PET_PORT/ingest"
PAYLOAD="$(cat)"
# Real cleanup (2026-10-10): K2_PET_VOICE used to be read right here for a direct
# `say -v` call -- dead now that speak() (below) posts to the server instead.
# The Kokoro-down fallback voice is still real, just lives entirely in
# server.mjs's own speakWithSay() now (reads K2_PET_VOICE from ITS process env,
# which this script's own `export`/`:=` here never reached anyway -- separate
# processes). Set it where the server actually starts if you want to change it.

CWD="$(echo "$PAYLOAD" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null)"

# A curl failure here must never block or fail the real Claude Code hook it's attached to.
# KK's real complaint (2026-10-09): running two tasks at once (e.g. a video build in
# one window, Claude Code work in another) with nothing telling them apart -- every
# session's hooks were posting to the same global state, a real collision. `cwd` is a
# real base field every classic hook already receives (confirmed in the engine's own
# docs) -- tagging it here, in post() itself rather than at every call site, means
# every existing event (turn/started, item/started, result/text, all of them) gets
# tagged for free, server-side, without touching each one by hand.
post() {
  local tagged
  tagged="$(CWD="$CWD" RAW="$1" python3 -c '
import json, os
d = json.loads(os.environ["RAW"])
d["cwd"] = os.environ.get("CWD", "")
print(json.dumps(d))
' 2>/dev/null)"
  curl -s -m 2 -X POST "$ENDPOINT" -H "Content-Type: application/json" -d "${tagged:-$1}" >/dev/null 2>&1 || true
}

# Real fix (KK's ask, 2026-10-10): this used to shell out straight to the raw
# macOS `say -v Samantha` -- a totally separate, worse-sounding path from the
# real Kokoro pipeline every on-demand read (the speaker button, a task row)
# already goes through. Routed through the pet server's own /speak-announcement
# instead: same Kokoro voice KK actually picked in the voice picker, same
# pause/resume, same fallback-to-say if Kokoro's genuinely down -- AND it's the
# one real place "mute automatic announcements" (companion.js's new toggle) can
# actually gate, which a direct local `say` call never could. Same fail-open
# rule as post(): a curl failure here must never block the real Claude Code
# hook this is attached to -- it just means the pet stays silent that one time.
speak() {
  curl -s -m 3 -X POST "http://127.0.0.1:$PET_PORT/speak-announcement" \
    -H "Content-Type: application/json" \
    -d "$(TEXT="$1" python3 -c 'import json,os; print(json.dumps({"text": os.environ["TEXT"]}))' 2>/dev/null)" \
    >/dev/null 2>&1 || true
}

HOOK_EVENT="$(echo "$PAYLOAD" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('hook_event_name',''))" 2>/dev/null)"
TRANSCRIPT_PATH="$(echo "$PAYLOAD" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('transcript_path',''))" 2>/dev/null)"
TOOL_NAME="$(echo "$PAYLOAD" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null)"
TOOL_ID="$(echo "$PAYLOAD" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_use_id','item'))" 2>/dev/null)"
MATCHER="$(echo "$PAYLOAD" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('matcher',''))" 2>/dev/null)"
NOTIF_MESSAGE="$(echo "$PAYLOAD" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('message',''))" 2>/dev/null)"
# Real activity caption, sourced directly from the hook's own payload -- never
# fabricated. A Bash call's own description (the one Claude Code itself writes per
# tool call), or its command if no description; an Edit/Write's real file_path; a
# WebSearch/WebFetch's real query/url; a Grep's real pattern. Truncated to 60 chars,
# matching the real limit Codex's own caption generator uses.
CAPTION="$(echo "$PAYLOAD" | python3 -c "
import json, sys
d = json.load(sys.stdin)
ti = d.get('tool_input') or {}
c = ti.get('description') or ti.get('command') or ti.get('file_path') or ti.get('query') or ti.get('url') or ti.get('pattern') or ''
print(c[:60])
" 2>/dev/null)"

# The real last assistant message, read straight from the transcript JSONL Claude
# Code itself writes (transcript_path in the hook payload) -- never fabricated, empty
# string if the file is missing or unreadable rather than a placeholder. Lightly
# cleaned for speech (code fences and markdown emphasis stripped, not summarized).
# KK's ask (2026-10-09): "read everything" -- raised the cap 500 -> 20000 chars so a
# long, multi-section reply gets read in full, not just its first paragraph. Still
# the real text, not a generated summary; a genuinely huge reply will just take a
# genuinely long time to read out loud -- that's the real tradeoff, not a bug.
extract_last_result() {
  [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ] || return 0
  TPATH="$TRANSCRIPT_PATH" python3 -c "
import json, os, re
path = os.environ['TPATH']
text = ''
try:
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
except Exception:
    print('')
    raise SystemExit
for line in reversed(lines):
    line = line.strip()
    if not line:
        continue
    try:
        entry = json.loads(line)
    except Exception:
        continue
    msg = entry.get('message') or {}
    if msg.get('role') != 'assistant':
        continue
    parts = []
    for block in msg.get('content') or []:
        if isinstance(block, dict) and block.get('type') == 'text':
            parts.append(block.get('text') or '')
    text = '\n'.join(parts).strip()
    if text:
        break
text = re.sub(r'\`\`\`.*?\`\`\`', ' code block omitted ', text, flags=re.S)
text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
text = re.sub(r'[*_#\`]', '', text)
text = re.sub(r'\s+', ' ', text).strip()
print(text[:20000])
" 2>/dev/null
}

item_type_for_tool() {
  case "$1" in
    Bash) echo "commandExecution" ;;
    Edit|Write|NotebookEdit) echo "fileChange" ;;
    WebSearch|WebFetch) echo "webSearch" ;;
    Agent|Task) echo "mcpToolCall" ;;
    *) echo "" ;;
  esac
}

case "$HOOK_EVENT" in
  UserPromptSubmit)
    post '{"method":"turn/started"}'
    ;;
  PreToolUse)
    # Clear any stale pending permission/question the instant real work resumes.
    post '{"method":"serverRequest/resolved"}'
    ITEM_TYPE="$(item_type_for_tool "$TOOL_NAME")"
    if [ -n "$ITEM_TYPE" ]; then
      ITEM_JSON="$(ITYPE="$ITEM_TYPE" TID="$TOOL_ID" CAP="$CAPTION" python3 -c '
import json, os
print(json.dumps({"method": "item/started", "item": {"type": os.environ["ITYPE"], "id": os.environ["TID"], "caption": os.environ.get("CAP", "")}}))
')"
      post "$ITEM_JSON"
    else
      post '{"method":"turn/started"}'
    fi
    ;;
  PostToolUse)
    ITEM_TYPE="$(item_type_for_tool "$TOOL_NAME")"
    if [ -n "$ITEM_TYPE" ]; then
      post "{\"method\":\"item/completed\",\"item\":{\"type\":\"$ITEM_TYPE\",\"id\":\"$TOOL_ID\"}}"
    fi
    ;;
  PostToolUseFailure)
    post '{"method":"item/tool.failed","error":"tool_failed"}'
    ;;
  PermissionRequest)
    post '{"method":"item/permissions/requestApproval","id":"pending-approval"}'
    ;;
  Stop)
    RESULT_TEXT="$(extract_last_result)"
    if [ -n "$RESULT_TEXT" ]; then
      RESULT_JSON="$(RTEXT="$RESULT_TEXT" python3 -c 'import json,os; print(json.dumps({"method":"result/text","text":os.environ["RTEXT"]}))')"
      post "$RESULT_JSON"
    fi
    speak "Done."
    post '{"method":"turn/completed","params":{"turn":{"status":"completed"}}}'
    ;;
  StopFailure)
    speak "Hit a problem."
    post '{"method":"turn/completed","params":{"turn":{"status":"failed"}}}'
    ;;
  Notification)
    # Real fix per KK's feedback: was firing both a native macOS notification AND the
    # pet's own bubble -- one too many things competing for attention. The pet bubble
    # alone is the signal now; clicking it brings Claude Code forward (see companion.js).
    if [ -n "$NOTIF_MESSAGE" ]; then
      ALERT_JSON="$(MSG="$NOTIF_MESSAGE" python3 -c 'import json,os; print(json.dumps({"method":"pet/alert","message":os.environ["MSG"]}))')"
      post "$ALERT_JSON"
      # KK's own ask (2026-10-08): a notification should say what it actually is, not
      # the same generic "Done." every Stop fires. Capped, not summarized -- the real
      # notification text, trimmed to a sane spoken length.
      speak "${NOTIF_MESSAGE:0:300}"
    fi
    ;;
esac
