# Claude Code hook events — what's real, what's wired, what's available

Verified against Claude Code's actual current hook system (v2.1.233), not
guessed. There are **33 real hook events** total. `k2-pet-claude-code-emit.sh`
currently wires up **8** of them. The other 25 are real, available signals
nobody has connected to a pet animation yet — this file exists so choosing
which ones matter is a real decision, not a guess.

## Currently wired (8)

| Event | Fires when | What the pet does today |
|---|---|---|
| `UserPromptSubmit` | You submit a prompt | `turn/started` → working |
| `PreToolUse` | Before a tool call runs | `item/started` (typed: commandExecution/fileChange/webSearch/mcpToolCall) |
| `PostToolUse` | After a tool call succeeds | `item/completed` |
| `PostToolUseFailure` | After a tool call fails | generic `item/tool.failed` (no distinct animation yet) |
| `PermissionRequest` | About to ask you for approval | `item/permissions/requestApproval` → waiting |
| `Stop` | Claude finishes responding | `turn/completed` (status: completed) → finished |
| `StopFailure` | Turn ends on an API error (rate limit, overloaded, etc.) | `turn/completed` (status: failed) → failed |
| `Notification` | permission_prompt, idle_prompt, auth_success, etc. | `pet/alert` bubble (all notification types treated the same) |

## Real, available, NOT wired yet (25) — candidates if you want more stages

Grouped by whether they'd plausibly map to a distinct pet moment:

**Session lifecycle** — could drive a real greeting/goodbye instead of always
booting into plain idle:
- `SessionStart` (source: startup/resume/clear/compact/fork)
- `SessionEnd` (reason: clear/resume/logout/prompt_input_exit/other)

**Subagents** — you already have `working`; a subagent running is a genuinely
different real moment (delegating, not doing it yourself):
- `SubagentStart` (agentType: general-purpose/Explore/Plan/custom)
- `SubagentStop`

**Housekeeping** — real "tidying up" moments distinct from normal work:
- `PreCompact` / `PostCompact` (reason: manual/auto) — context compaction
- `ConfigChange` — settings changed mid-session
- `InstructionsLoaded` — a CLAUDE.md loaded

**Finer-grained notification types** (currently all collapsed into one generic
alert bubble — `Notification`'s own `notificationType` field already
distinguishes them for free, no new hook needed, just branch on the field):
- `permission_prompt`, `idle_prompt`, `auth_success`, `elicitation_dialog`,
  `elicitation_url_dialog`, `agent_needs_input`, `agent_completed`,
  `quota_auto_resume_fired`, `quota_auto_resume_stale`,
  `quota_auto_resume_disabled`

**Permission nuance** — right now PermissionRequest always shows the same
"waiting" pose; these could differentiate "auto-denied" from "waiting for you":
- `PermissionDenied` (auto mode denied a tool call)

**Model/environment changes** — real, but low-frequency; probably not worth a
dedicated animation unless you want one:
- `PreModelSwitch` / `PostModelSwitch`
- `CwdChanged`, `DirectoryAdded`, `WorktreeCreate`, `WorktreeRemove`
- `FileChanged`

**Rarely useful for a pet** — real events, but hard to picture as a visible
state (batch/internal bookkeeping):
- `PostToolBatch`, `MessageDisplay`, `TaskCreated`, `TaskCompleted`,
  `TeammateIdle`, `UserPromptExpansion`, `Elicitation`, `ElicitationResult`,
  `Setup`

## The real payload shape (every hook gets this on stdin)

```json
{
  "session_id": "...", "prompt_id": "...", "transcript_path": "...",
  "cwd": "...", "permission_mode": "default|acceptEdits|bypassPermissions|dontAsk",
  "hook_event_name": "PreToolUse|PostToolUse|...",
  "tool_name": "Bash|Edit|Write|...",       // PreToolUse/PostToolUse/PermissionRequest only
  "tool_input": { "command": "...", "file_path": "..." },
  "notificationType": "..."                 // Notification only
}
```

`k2-pet-claude-code-emit.sh` already reads `hook_event_name`, `tool_name`,
`tool_input`, and `message` — extending it to branch on `notificationType` or
add a new `case` for `SessionStart`/`SubagentStart`/etc. is the same pattern
already used for the 8 that exist today, not new plumbing.

Source: Claude Code's own current hook system, checked via a dedicated guide
agent against the real, documented event list — not assumed from this
project's own script.
