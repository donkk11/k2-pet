import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { PetSnapshot } from '../types'

const PANE = 'k2-pet'
const SERVER = 'http://127.0.0.1:3043'
const snapshot = atom(
  { plugin: 'k2-pet-mod', key: 'snapshot' } as const,
  {
    state: 'idle',
    caption: null,
    hasResult: false,
    isPaused: false,
    isMuted: false,
    connected: false,
    lastPollAt: null,
    history: [],
  } as PetSnapshot,
)

const MAX_HISTORY = 8

// Same semantic colors as companion.html's own .task-dot CSS (amber=working,
// green=finished, red=problem, gray=interrupted/idle) -- one real palette,
// not a second one invented for this pane.
const STATE_COLORS: Record<string, string> = {
  working: '#f5a623', executing: '#f5a623', editing: '#f5a623', 'tool-use': '#f5a623',
  checking: '#f5a623', searching: '#f5a623', reading: '#f5a623', speaking: '#f5a623',
  listening: '#f5a623', finished: '#3ddc84', problem: '#e5484d', interrupted: '#8a8580',
  idle: '#8a8580', permission: '#d97757', attention: '#d97757', question: '#d97757',
}

// Same art map companion.js already uses (public/companion.js's `art` const) --
// reused, not reinvented, so the Pane shows the same pose family the floating
// window would for the same state. "finished"/"permission" now have their own
// standalone static PNGs too (Codex extracted real frames -- jumping.png frame 3
// and permission-wait.png frame 2 -- from the existing animated strips, 2026-10-08;
// not generated art, not a fallback anymore).
const ART: Record<string, string> = {
  idle: 'idle', working: 'working', executing: 'working', editing: 'working',
  searching: 'checking', 'tool-use': 'working', checking: 'checking',
  permission: 'permission', question: 'waiting', finished: 'finished',
  interrupted: 'waiting', problem: 'problem', listening: 'waiting',
  speaking: 'working', attention: 'waiting',
  // "reading" is its own state now (a clicked task summary being read aloud),
  // distinct from Nimba's "speaking" -- reuses the waiting pose, same as the
  // external window's gaze look-around treatment for it.
  reading: 'waiting',
}

// Real fix (KK's ask, 2026-10-11): this used to be a hardcoded absolute path to
// KK's own machine -- the real, concrete blocker his own "turn this into a
// public installer" ask flagged first. $.plugin.root (confirmed real, read
// straight from the authoritative local .d.ts: "The plugin's directory (the
// one holding plugin.json), absolute") replaces it -- relative from there
// instead of an absolute personal path, so wherever the whole project gets
// installed, this resolves correctly without edits. Still assumes the sibling
// layout (k2-pet-mod/../../assets/states) holds, i.e. this mod ships alongside
// the rest of the k2-extended-pet-states project, not as a fully bundled
// standalone -- real next step for a truly standalone public package would be
// shipping the mod's own copy of the sprite assets under $.plugin.root itself.
const SPRITE_DIR_REL = '../../assets/states'

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'k2-pet',
      description: "Show KK's real K2 pet inside Claude Code",
    })
    void $.ui.open({ id: PANE, title: 'K2 Pet' })

    $.clock.every(700, async () => {
      const polledAt = new Date().toISOString()
      try {
        const res = await $.http.fetch(`${SERVER}/state`)
        if (!res.ok) {
          await update($, snapshot, current => ({
            ...current,
            connected: false,
            lastPollAt: polledAt,
          }))
          return
        }
        const data = JSON.parse(res.text)
        await update($, snapshot, current => {
          const previousHistory = Array.isArray(current.history) ? current.history : []
          const history = current.state !== data.state
            ? [
                ...previousHistory,
                {
                  timestamp: polledAt,
                  state: data.state,
                  caption: data.caption ?? null,
                },
              ].slice(-MAX_HISTORY)
            : previousHistory

          return {
            state: data.state,
            caption: data.caption ?? null,
            hasResult: !!data.hasResult,
            isPaused: !!data.isPaused,
            isMuted: !!data.isMuted,
            connected: true,
            lastPollAt: polledAt,
            history,
          }
        })
      } catch {
        await update($, snapshot, current => ({
          ...current,
          connected: false,
          lastPollAt: polledAt,
        }))
      }
    })

    // KK's ask (2026-10-08): typing into the pet's compose box should actually run
    // in Claude Code, not just copy to clipboard -- genuinely impossible before Mods
    // (classic hooks have no equivalent of $.prompt.submit). Pop semantics on the
    // server side mean this never submits the same text twice even if two polls
    // race; asUser makes it read as KK's own typed prompt, not a plugin message.
    $.clock.every(700, async () => {
      try {
        const res = await $.http.fetch(`${SERVER}/pending-prompt`)
        if (!res.ok) return
        const { text } = JSON.parse(res.text)
        if (!text) return
        await $.prompt.submit({ text, asUser: true })
        // KK's ask (2026-10-09): "how will I know which chat my pet is typing into."
        // If several sessions have this mod loaded, all of them poll the same
        // queue -- whichever wins reports its real project directory back, so the
        // compose box can show which one actually got it instead of a guess.
        const cwd = await $.session.cwd()
        await $.http.fetch(`${SERVER}/prompt-delivered`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cwd }),
        })
      } catch {
        // pet server not running -- nothing to submit
      }
    })

    return next(e)
  })

  // Originally: pre-rendered audio shipped inside the plugin (audio/done.aiff,
  // audio/problem.aiff -- both rendered once via `say -o` on KK's Mac), played
  // unconditionally via $.audio.play on every turn.complete, meant as a
  // cross-platform-safe fallback for an installer without KK's personal pet
  // server running.
  //
  // Real bug KK caught live (2026-10-10): "I hear 2 voices" -- on his own
  // machine the pet server IS always running, and the classic Stop hook
  // (k2-pet-claude-code-emit.sh's speak(), routed through /speak-announcement)
  // already announces the same real completion in the Kokoro voice he actually
  // picked, mute-aware. A first attempt at a smarter fix (ping the server, only
  // play this bundled clip if unreachable) still didn't clear it for him even
  // after confirming Mods do hot-reload this file on save -- rather than keep
  // guessing at why that conditional wasn't landing, this is the literal fix he
  // asked for: removed outright, not conditional. Real tradeoff, stated plainly:
  // an installer of this mod without KK's own pet server running now gets no
  // audio feedback on turn completion at all -- silence, not a worse voice.
  on('turn.complete', async ($, e, next) => {
    return next(e)
  })

  on('command.run', { command: 'k2-pet' }, async $ => {
    await $.ui.open({ id: PANE, title: 'K2 Pet' })
    return { text: 'K2 Pet pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Image } = $.ui.resolve(e)
    const snap = await read($, snapshot)
    const motion = ART[snap.state] || 'idle'
    const spriteDir = `${$.plugin.root}/${SPRITE_DIR_REL}`
    const formatPollTime = (timestamp: string | null) =>
      timestamp ? new Date(timestamp).toLocaleTimeString() : 'never'
    const formatHistoryTime = (timestamp: string) =>
      new Date(timestamp).toLocaleTimeString()
    const history = Array.isArray(snap.history) ? snap.history : []

    return (
      <Box flexDirection="column">
        {/* Real redesign toward the reference mockup (KK's ask, 2026-10-14).
            Honest limit, checked again just now: Box has no backgroundColor
            (only border props are real) and there's no ring/badge component
            -- a literal circular progress ring or filled pill isn't buildable
            here. This gets the real available pieces (Text backgroundColor,
            bold, color) as close as the real component set allows: a colored
            "LIVE" badge using Text's own fill, not a fake Box pill. */}
        <Box flexDirection="row">
          <Text bold color="#d97757">K² </Text>
          <Text dimColor>/ SI</Text>
        </Box>
        <Box flexDirection="row" marginBottom={1}>
          <Text bold color="#0a0a0a" backgroundColor="#3ddc84"> ● LIVE </Text>
        </Box>
        <Text bold color={STATE_COLORS[snap.state] || '#8a8580'}>{snap.state.toUpperCase()}</Text>
        {snap.caption && <Text dimColor>{snap.caption}</Text>}
        {snap.hasResult && (
          <Button
            key="hear"
            label="Hear last result"
            onPress={async () => {
              await $.http.fetch(`${SERVER}/speak-last`, { method: 'POST' })
            }}
          />
        )}
        <Box
          marginTop={1}
          paddingX={1}
          borderStyle="round"
          borderColor="#d97757"
          flexDirection="column"
        >
          <Text bold color="#d97757">◆ K2 LINK STATUS</Text>
          <Box flexDirection="row">
            <Text bold color={snap.connected ? '#3ddc84' : '#e5484d'}>
              {snap.connected ? '● CONNECTED' : '○ OFFLINE'}
            </Text>
          </Box>
          <Box flexDirection="row">
            <Text color={snap.isMuted ? '#f5a623' : '#8a8580'}>
              {snap.isMuted ? '🔇 MUTED' : '🔊 live'}
            </Text>
            <Text>{'   '}</Text>
            <Text color={snap.isPaused ? '#f5a623' : '#8a8580'}>
              {snap.isPaused ? '⏸ PAUSED' : '▶ running'}
            </Text>
          </Box>
          <Text dimColor>last poll {formatPollTime(snap.lastPollAt)}</Text>
          {/* Real bar/graph (KK's ask, 2026-10-11): the real confirmed Pane
              component set has no chart/bar component (checked the actual
              14973-line type file again -- Box/Text/Button/Image is genuinely
              it), so this is a REAL bar built from Unicode block characters +
              the already-confirmed real `color` prop, not a fake "we have
              charts now" claim. One solid block per observed state, same
              real per-state color already used below -- an honest at-a-glance
              density graph of actual recent activity, not invented data. */}
          {history.length > 0 && (
            <Box flexDirection="row" marginTop={1}>
              <Text dimColor>ACTIVITY  </Text>
              {history.map((entry, index) => (
                <Text key={`bar-${index}`} bold color={STATE_COLORS[entry.state] || '#8a8580'}>█</Text>
              ))}
            </Box>
          )}
          <Text bold color="#d97757">{'\n'}RECENT ACTIVITY</Text>
          {history.length === 0 && <Text dimColor>  (waiting for the first real event)</Text>}
          {history.slice().reverse().map((entry, index) => (
            <Text key={`history-${index}`} color={STATE_COLORS[entry.state] || '#8a8580'}>
              {`  ${formatHistoryTime(entry.timestamp)}  ${entry.state.toUpperCase()}${entry.caption ? ' — ' + entry.caption : ''}`}
            </Text>
          ))}
        </Box>
      </Box>
    )
  })
}
