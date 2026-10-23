import { createServer } from "node:http";
import { createReadStream, existsSync } from "node:fs";
import { extname, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFile } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AppServerRecorder } from "./app-server-recorder.mjs";
import { K2StateMapper } from "./state-mapper.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const mapper = new K2StateMapper();
const clients = new Set();
let current = mapper.last;
let terminalTimer = null;
// KK's real complaint (2026-10-09): running two tasks at once (a video build, Claude
// Code work) with the pet's single global state -- no way to tell which finished, no
// way to choose which to hear, a real collision. Tracked per real session cwd (now
// tagged on every event by the emit script's post(), see there). The MAIN pet's pose
// still reflects whichever task most recently sent an event -- a known, stated limit,
// not silently papered over: this registry fixes "which one finished / which do I
// hear", not "show me N pets at once", which is a bigger, separate rebuild.
const tasks = new Map(); // cwd -> { label, state, hasResult, resultText, updatedAt }

function taskLabel(cwd) {
  return cwd.split("/").filter(Boolean).pop() || cwd || "unknown";
}

function touchTask(cwd, patch) {
  if (!cwd) return; // an event with no cwd (e.g. a test curl) doesn't pollute the list
  const existing = tasks.get(cwd) || { label: taskLabel(cwd), state: "idle", hasResult: false, resultText: "" };
  tasks.set(cwd, { ...existing, ...patch, updatedAt: Date.now() });
}
// The real text of the last finished turn's final assistant message (plain-ish,
// cleaned of markdown, capped -- see k2-pet-claude-code-emit.sh's extract_last_result()),
// read aloud on demand by /speak-last. Not a summary: the model's own words, trimmed.
let lastResultText = "";
// Text typed into the pet's compose box, queued here until a Mod's poll loop picks
// it up and calls $.prompt.submit -- see k2-pet-mod/hooks/register.tsx. Pop semantics
// (GET clears it): a Mod polling every 700ms must never submit the same prompt twice.
let pendingPrompt = "";
// KK's real question (2026-10-09): if several Claude Code sessions are open and all
// have k2-pet-mod loaded, ALL of them poll the same /pending-prompt -- whichever
// one's 700ms tick lands first wins, genuinely a race, not solved by this alone. But
// at least this answers "which chat did it go to": the mod that wins reports back
// its real project directory (via $.session.cwd()), not a guess.
let lastDelivery = null; // { cwd, at } | null
// The real speech process currently reading -- `say` or `afplay`, both real child
// processes, so pause/resume is literal Unix job control (SIGSTOP/SIGCONT), not a
// simulated pause: audio genuinely stops writing frames and resumes where it left
// off, the same mechanism a shell's Ctrl-Z does. null when nothing is reading.
let activeSpeechProcess = null;
let isPaused = false;
// KK's real complaint (2026-10-10): the automatic "Done."/"Hit a problem."/
// notification announcements (k2-pet-claude-code-emit.sh's speak()) were shelling
// out to the raw macOS `say -v Samantha` directly -- a totally separate path from
// the real Kokoro pipeline every ON-DEMAND read already uses, which is why it
// sounded like a different, worse voice: it WAS a different, worse voice. Routed
// through /speak-announcement (below) instead, which reuses speakText() -- same
// Kokoro voice KK actually picked, same pause/resume, same fallback-to-say if
// Kokoro's down. isMuted gates exactly this automatic path, in the one real place
// all of it now funnels through -- "meeting mode" for announcements, not for a
// deliberate click on the speaker button, which stays unaffected either way.
let isMuted = false;
// Real bug KK's testing exposed (2026-10-09): activeSpeechProcess is only set AFTER
// Kokoro's fetch resolves and afplay actually starts -- a voice switch that lands
// WHILE still mid-synthesis (the fetch itself, which can take several seconds for
// long text) found nothing to kill, so nothing restarted. This generation counter
// covers BOTH phases: every speakText() call takes a ticket, and any older call's
// eventual completion (fetch resolving late, or its player's exit callback) is a
// no-op once a newer call has started -- so a switch mid-synthesis correctly drops
// the stale request instead of letting two overlapping reads fight.
let speechGeneration = 0;
// Nimba's own real Kokoro-82M server (nimba/kokoro_server.py, port 8880, MLX --
// Apple GPU, not CPU) -- KK's actual find (2026-10-09): real, measured fast, not
// assumed. Same two test sentences as the XTTS measurement below, same machine:
// 48 chars -> 0.76s, 250 chars -> 2.0s. XTTS: 50s and 30s for the same two. This is
// now the real default. There is still no "Claude voice" API in Mods (checked the
// full engine type declarations: $.audio.speak's `voice` option is explicitly the
// OS synthesizer's own name, e.g. "Samantha" -- nothing Anthropic-hosted) -- Kokoro
// is KK's own local model, not Anthropic's, same honest distinction as XTTS.
const KOKORO_URL = "http://127.0.0.1:8880/speak";
// "am_kk" is KK's own cloned-speed voice (KK's real goal, 2026-10-09): it already
// existed, baked, in prince-canuma/Kokoro-82M's own voices dir
// (am_kk.safetensors) -- voices.json even already listed it ("KK Kokoro-speed")
// -- it just wasn't in kokoro_server.py's ALLOWED_VOICES whitelist until now.
// Measured on the real warm server: 3.8s, ~10x faster than XTTS's 30-50s for
// comparable text, and it's actually his voice, not a stock one.
const KOKORO_VOICES = ["am_kk", "am_echo", "am_michael", "am_adam", "af_sarah",
  "af_bella", "af_nicole", "bf_emma", "bm_george", "ef_dora", "em_alex", "em_santa"];
// KK's explicit ask (2026-10-09): default to Emma (British F), not am_kk --
// am_kk's robotic sound (a real, flagged modeling limitation, not a bug) made him
// prefer a stock voice as the actual daily default.
let kokoroVoice = KOKORO_VOICES.includes(process.env.K2_PET_KOKORO_VOICE)
  ? process.env.K2_PET_KOKORO_VOICE : "bf_emma";

// Nimba's XTTS server (nimba/xtts_server.py, port 8883) -- KK's actual cloned voice.
// Kept as a THIRD option, not removed: Kokoro is faster, but XTTS is a real clone of
// KK's own voice specifically, which Kokoro's stock voices are not. Opt in with
// K2_PET_NATURAL_VOICE=xtts; still genuinely slow (measured: 30-50s), so it stays
// opt-in, not a default -- that finding didn't change just because Kokoro arrived.
const XTTS_URL = "http://127.0.0.1:8883/speak";
const XTTS_SPEAKER = process.env.K2_PET_XTTS_SPEAKER || "kk";
const VOICE_ENGINE = process.env.K2_PET_NATURAL_VOICE === "xtts" ? "xtts" : "kokoro";

async function playWav(res, doneMethod, myGen) {
  const bytes = Buffer.from(await res.arrayBuffer());
  if (myGen !== speechGeneration) return; // superseded while the fetch was in flight -- drop it
  const tmpFile = join(tmpdir(), `k2-pet-speech-${Date.now()}.wav`);
  await writeFile(tmpFile, bytes);
  activeSpeechProcess = execFile("afplay", [tmpFile], () => {
    if (myGen !== speechGeneration) return; // a newer read started and already owns activeSpeechProcess
    activeSpeechProcess = null;
    isPaused = false;
    publish(mapper.ingest({ method: doneMethod }));
  });
}

// Plays `text` out loud: Kokoro by default (real, measured fast: under 2s for a
// realistic result), `say` only as a last-resort fallback if Kokoro's unreachable --
// not the default anymore, Samantha's done her job. XTTS stays available but opt-in
// (see above) since the slowness finding is unchanged.
async function speakText(text, startMethod, doneMethod) {
  const myGen = ++speechGeneration;
  publish(mapper.ingest({ method: startMethod }));
  isPaused = false;
  if (VOICE_ENGINE === "xtts") {
    try {
      const res = await fetch(XTTS_URL, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, speaker: XTTS_SPEAKER }),
        signal: AbortSignal.timeout(8000),
      });
      if (!res.ok) throw new Error(`XTTS ${res.status}`);
      return await playWav(res, doneMethod, myGen);
    } catch (error) {
      console.error(`[speak] XTTS unavailable or too slow (${error.message}), falling back to say`);
      return speakWithSay(text, doneMethod, myGen);
    }
  }
  try {
    // KK's ask (2026-10-09, "read everything") raised the real text cap to 20000
    // chars -- the old flat 8s timeout here predates that and would wrongly abort
    // (then fall back to say) any request long enough to need more than 8s of real
    // synthesis time. Scaled instead: a generous per-character budget, floored at
    // 8s so short requests keep the same snappy cutoff as before.
    const res = await fetch(KOKORO_URL, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice: kokoroVoice }),
      signal: AbortSignal.timeout(Math.max(8000, text.length * 60)),
    });
    if (!res.ok) throw new Error(`Kokoro ${res.status}`);
    await playWav(res, doneMethod, myGen);
  } catch (error) {
    console.error(`[speak] Kokoro unavailable (${error.message}), falling back to say`);
    speakWithSay(text, doneMethod, myGen);
  }
}

function speakWithSay(text, doneMethod, myGen) {
  const voice = process.env.K2_PET_VOICE || "Samantha";
  activeSpeechProcess = execFile("say", ["-v", voice, text], () => {
    if (myGen !== speechGeneration) return; // superseded -- a newer read owns activeSpeechProcess now
    activeSpeechProcess = null;
    isPaused = false;
    publish(mapper.ingest({ method: doneMethod }));
  });
}

function allowLocalOrigin(req, res) {
  const origin = req.headers.origin || "";
  if (/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
  }
}

function publish(state, raw = null) {
  current = state;
  // hasResult was only ever in /state's one-off GET response -- the live SSE stream
  // (what companion.js actually renders from) never carried it, so the speaker
  // button's glow had nothing real to key off of. Real bug, not a hypothetical one.
  const packet = `data: ${JSON.stringify({ ...state, raw, hasResult: lastResultText.length > 0, isPaused, isMuted })}\n\n`;
  for (const client of clients) client.write(packet);
  if (terminalTimer) clearTimeout(terminalTimer);
  if (state.state === "finished") {
    terminalTimer = setTimeout(() => publish(mapper.snapshot("terminal-expired")), mapper.finishedMs + 25);
  } else if (["interrupted", "problem"].includes(state.state)) {
    terminalTimer = setTimeout(() => publish(mapper.snapshot("terminal-expired")), mapper.transientMs + 25);
  } else if (state.state === "attention") {
    terminalTimer = setTimeout(() => publish(mapper.snapshot("alert-expired")), mapper.alertMs + 25);
  }
}

const server = createServer((req, res) => {
  allowLocalOrigin(req, res);
  if (req.method === "OPTIONS" && req.url === "/ingest") {
    res.writeHead(204, {
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    });
    res.end();
    return;
  }
  if (req.url === "/events") {
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
    clients.add(res);
    // Real bug this exposed: this initial snapshot bypassed publish() entirely, so a
    // freshly-opened/reloaded companion window never got hasResult on first paint --
    // the speaker button would sit dark until the NEXT event happened to arrive, even
    // with a real result already cached. Same shape publish() sends, not a copy.
    res.write(`data: ${JSON.stringify({ ...current, hasResult: lastResultText.length > 0, isPaused, isMuted })}\n\n`);
    req.on("close", () => clients.delete(res));
    return;
  }
  if (req.method === "POST" && req.url === "/ingest") {
    let body = "";
    req.on("data", (chunk) => body += chunk);
    req.on("end", () => {
      try {
        const event = JSON.parse(body);
        // KK's ask (2026-10-09): "read everything" -- raised to match the emit
        // script's own 20000-char cap (was 4096, quietly truncating before the
        // script's limit even kicked in).
        if (event?.method === "result/text") lastResultText = String(event.text || "").slice(0, 20000);
        // Per-task tracking (KK's "collision" ask, 2026-10-09) -- cwd is now tagged
        // on every event by the emit script's post(). A simple status derived from
        // the same method names state-mapper.mjs already understands, kept
        // deliberately separate from it: this never touches the single shared
        // mapper the main pet pose reads from.
        if (event?.cwd) {
          if (event.method === "turn/started") touchTask(event.cwd, { state: "working" });
          else if (event.method === "turn/completed") {
            const status = event.params?.turn?.status || "completed";
            touchTask(event.cwd, { state: status === "failed" ? "problem" : status === "interrupted" ? "interrupted" : "finished" });
          } else if (event.method === "result/text") {
            touchTask(event.cwd, { hasResult: true, resultText: String(event.text || "").slice(0, 20000) });
          } else {
            touchTask(event.cwd, {}); // any other real event (tool activity, etc.) -- just marks it alive
          }
        }
        const state = mapper.ingest(event, event?.source || "external");
        publish(state, event);
        res.writeHead(202, { "Content-Type": "application/json" });
        res.end(JSON.stringify(state));
      } catch (error) {
        res.writeHead(400); res.end(error.message);
      }
    });
    return;
  }
  // Polling read for anything that isn't an SSE client (a Claude Code Mod's Pane,
  // which has no EventSource -- it fetches on a timer instead). Same snapshot shape
  // /events pushes, plus the cached result text so a Pane's button can show/hide.
  if (req.method === "GET" && req.url === "/state") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ...current, hasResult: lastResultText.length > 0, isPaused, isMuted }));
    return;
  }
  // Reads the cached last-result text out loud, server-side (real shell access here;
  // a Mod or the browser companion do not). Uses "reading", not "speaking" -- KK's
  // own ask (2026-10-08): this is a different thing from Nimba's realtime voice and
  // deserves its own state/art (gaze look-around), not a silent reuse of Nimba's
  // indicator. If something's already reading, this restarts from the top rather
  // than overlapping two speech processes.
  if (req.method === "POST" && req.url === "/speak-last") {
    if (activeSpeechProcess) activeSpeechProcess.kill();
    const text = lastResultText || "Nothing finished yet.";
    speakText(text, "pet/reading.start", "pet/reading.done");
    res.writeHead(202, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ speaking: true, chars: text.length }));
    return;
  }
  // Real gap K2 Voice Link exposed (KK's ask, 2026-10-11): the actual result
  // text was never sent to the browser -- only used server-side by
  // speakText()/the Python engine. K2 Voice Link runs client-side, so it
  // genuinely needs the real text to read, not just a "hasResult" boolean.
  // Read-only, GET, no side effect -- unlike /speak-last this doesn't start
  // any server-side speech.
  if (req.method === "GET" && req.url === "/last-result-text") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ text: lastResultText }));
    return;
  }
  if (req.method === "GET" && req.url.startsWith("/task-result-text")) {
    const cwd = new URL(req.url, "http://localhost").searchParams.get("cwd") || "";
    const task = tasks.get(cwd);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ text: task?.resultText || "" }));
    return;
  }
  // Real pause/resume, KK's ask (2026-10-08): SIGSTOP/SIGCONT on the actual child
  // process -- literal Unix job control, the same thing a shell's Ctrl-Z does, not a
  // simulated pause. No-ops (200, paused:false/true unchanged) when nothing is
  // reading, so a stray click can't throw.
  // Real bug KK caught live: K2 Voice Link (client-side) and the server voice
  // (Python/Kokoro, afplay) are two fully separate audio systems with zero
  // mutual awareness -- switching tasks and triggering a client-side read
  // while an old server-side read was still playing produced two real voices
  // overlapping. This stops the server side ONLY (no new speech started),
  // so the client can call it right before starting its own read.
  if (req.method === "POST" && req.url === "/speak-stop") {
    if (activeSpeechProcess) activeSpeechProcess.kill();
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ stopped: true }));
    return;
  }
  if (req.method === "POST" && req.url === "/speak-pause") {
    if (activeSpeechProcess && !isPaused) {
      activeSpeechProcess.kill("SIGSTOP");
      isPaused = true;
      publish(mapper.snapshot("pet/reading.paused"));
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ isPaused }));
    return;
  }
  if (req.method === "POST" && req.url === "/speak-resume") {
    if (activeSpeechProcess && isPaused) {
      activeSpeechProcess.kill("SIGCONT");
      isPaused = false;
      publish(mapper.snapshot("pet/reading.resumed"));
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ isPaused }));
    return;
  }
  // The real voice catalog, for the pet's picker -- KK's ask (2026-10-09). Labels
  // match Kokoro's own naming convention (prefix = accent+gender: am=American Male,
  // af=American Female, bf/bm=British, ef/em=Spanish), same list kokoro_server.py's
  // own ALLOWED_VOICES enforces server-side -- this endpoint doesn't invent one.
  if (req.method === "GET" && req.url === "/voices") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ voices: KOKORO_VOICES, current: kokoroVoice }));
    return;
  }
  if (req.method === "POST" && req.url === "/set-voice") {
    let body = "";
    req.on("data", (chunk) => body += chunk);
    req.on("end", () => {
      try {
        const { voice } = JSON.parse(body);
        if (!KOKORO_VOICES.includes(voice)) {
          res.writeHead(400); res.end(JSON.stringify({ error: "unknown voice" })); return;
        }
        kokoroVoice = voice;
        // KK's real complaint (2026-10-09): "switching while it's reading doesn't
        // work." Checking `activeSpeechProcess` alone (the first version of this
        // fix) missed it: that variable is only set AFTER Kokoro's fetch resolves
        // and afplay actually starts, so a switch landing during the synthesis
        // itself (which can take several real seconds, more now with the "read
        // everything" cap raised) found nothing to kill and silently did nothing
        // audible -- confirmed live, this exact sequence (switch 1s into a request
        // whose synthesis took 1.6s) reproduced it. Checking the real "reading"
        // state instead covers both phases; speechGeneration (see speakText)
        // makes the OLD in-flight request a safe no-op once it does resolve,
        // instead of two reads fighting over activeSpeechProcess.
        if (mapper.last.state === "reading") {
          if (activeSpeechProcess) activeSpeechProcess.kill();
          speakText(lastResultText || "Nothing finished yet.", "pet/reading.start", "pet/reading.done");
        }
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ current: kokoroVoice }));
      } catch (error) {
        res.writeHead(400); res.end(error.message);
      }
    });
    return;
  }
  // The compose box's real send path (KK's ask, 2026-10-08): queues typed text for
  // a Mod to pick up and actually submit to Claude Code via $.prompt.submit -- not
  // possible before Mods existed (see companion.js's own comment on why it fell back
  // to clipboard+focus). Only does anything while a Mod is actually polling.
  if (req.method === "POST" && req.url === "/submit-prompt") {
    let body = "";
    req.on("data", (chunk) => body += chunk);
    req.on("end", () => {
      try {
        const { text } = JSON.parse(body);
        pendingPrompt = String(text || "").slice(0, 8000);
        res.writeHead(202, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ queued: pendingPrompt.length > 0 }));
      } catch (error) {
        res.writeHead(400); res.end(error.message);
      }
    });
    return;
  }
  if (req.method === "GET" && req.url === "/pending-prompt") {
    const text = pendingPrompt;
    pendingPrompt = ""; // pop, not peek -- a Mod's next poll must not resubmit it
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ text }));
    return;
  }
  // The mod that actually won the race reports back here (real cwd, not a guess) --
  // KK's ask (2026-10-09): "how will I know which chat my pet is typing into."
  if (req.method === "POST" && req.url === "/prompt-delivered") {
    let body = "";
    req.on("data", (chunk) => body += chunk);
    req.on("end", () => {
      try {
        const { cwd } = JSON.parse(body);
        lastDelivery = { cwd: String(cwd || "").slice(0, 500), at: Date.now() };
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true }));
      } catch (error) {
        res.writeHead(400); res.end(error.message);
      }
    });
    return;
  }
  if (req.method === "GET" && req.url === "/last-delivery") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ delivery: lastDelivery }));
    return;
  }
  // KK's ask (2026-10-09): see which tasks are running/finished, not just the one
  // global "last result". Real per-cwd state, not guessed -- tagged by the emit
  // script's post() on every real hook event. Most recently active first.
  if (req.method === "GET" && req.url === "/tasks") {
    const list = [...tasks.entries()]
      .map(([cwd, t]) => ({ cwd, label: t.label, state: t.state, hasResult: t.hasResult, updatedAt: t.updatedAt }))
      .sort((a, b) => b.updatedAt - a.updatedAt);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ tasks: list }));
    return;
  }
  // Speaks ONE specific task's cached result, chosen by cwd -- not just "the last
  // one globally". Same engine as /speak-last (Kokoro default, say fallback, real
  // pause/resume via the same generation counter), just reading a different text.
  if (req.method === "POST" && req.url === "/speak-task") {
    let body = "";
    req.on("data", (chunk) => body += chunk);
    req.on("end", () => {
      try {
        const { cwd } = JSON.parse(body);
        const task = tasks.get(cwd);
        if (!task) { res.writeHead(404); res.end(JSON.stringify({ error: "unknown task" })); return; }
        if (activeSpeechProcess) activeSpeechProcess.kill();
        const text = task.resultText || `${task.label} has nothing finished yet.`;
        speakText(text, "pet/reading.start", "pet/reading.done");
        res.writeHead(202, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ speaking: true, label: task.label }));
      } catch (error) {
        res.writeHead(400); res.end(error.message);
      }
    });
    return;
  }
  // KK's ask (2026-10-10): the automatic "Done."/"Hit a problem."/notification
  // speech should sound as good as everything else (real Kokoro, the voice KK
  // actually picked) and should respect mute -- both solved by routing it through
  // the exact same engine as /speak-last instead of emit.sh's own raw `say` call.
  // Silent no-op while muted: no audio, no state change, nothing queued for later
  // -- "don't bother me" means exactly that, not "tell me when I unmute."
  if (req.method === "POST" && req.url === "/speak-announcement") {
    let body = "";
    req.on("data", (chunk) => body += chunk);
    req.on("end", () => {
      try {
        const { text } = JSON.parse(body);
        if (isMuted) { res.writeHead(200, { "Content-Type": "application/json" }); res.end(JSON.stringify({ skipped: "muted" })); return; }
        if (activeSpeechProcess) activeSpeechProcess.kill();
        speakText(String(text || "").slice(0, 2000), "pet/reading.start", "pet/reading.done");
        res.writeHead(202, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ speaking: true }));
      } catch (error) {
        res.writeHead(400); res.end(error.message);
      }
    });
    return;
  }
  if (req.method === "POST" && req.url === "/set-mute") {
    let body = "";
    req.on("data", (chunk) => body += chunk);
    req.on("end", () => {
      try {
        const { muted } = JSON.parse(body);
        isMuted = !!muted;
        publish(mapper.snapshot("pet/mute-changed"));
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ isMuted }));
      } catch (error) {
        res.writeHead(400); res.end(error.message);
      }
    });
    return;
  }
  // Real bug found from live testing: req.url includes the query string (e.g.
  // "/companion.html?dragtest=1"), and without stripping it the file lookup below
  // looked for a literal file named "companion.html?dragtest=1" -- always 404,
  // which is exactly the blank "Not found" window KK saw blocking his screen.
  const urlPath = req.url.split("?")[0];
  const path = urlPath === "/" ? "/index.html" : urlPath;
  const file = resolve(ROOT, path.startsWith("/assets/") ? `.${path}` : `public${path}`);
  if (!file.startsWith(ROOT) || !existsSync(file)) { res.writeHead(404); res.end("Not found"); return; }
  const mime = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".png": "image/png" }[extname(file)] || "application/octet-stream";
  res.writeHead(200, { "Content-Type": mime });
  createReadStream(file).pipe(res);
});

// Real bug KK caught live (2026-10-14): running the pet a second time left
// real orphan processes behind instead of failing loudly -- there was no
// error handler on this server at all, so a genuine port conflict (or a
// stray PORT=0 test env asking the OS for a random free port) never
// produced a clear failure, just a silent second process doing nothing
// useful. Now: a real EADDRINUSE says so plainly and exits, instead of
// leaving a zombie behind for someone to find later with `ps`.
const port = Number(process.env.PORT || 3042);
server.on("error", (err) => {
  if (err.code === "EADDRINUSE") {
    console.error(`K2 pet server: port ${port} is already in use -- a pet server is probably already running. Not starting a second one.`);
    process.exit(1);
  }
  console.error("K2 pet server: real startup error:", err);
  process.exit(1);
});
server.listen(port, "127.0.0.1", async () => {
  console.log(`K2 overlay: http://127.0.0.1:${port}`);
  if (process.argv.includes("--record")) {
    const recorder = new AppServerRecorder({ onState: publish });
    await recorder.start();
    const run = await recorder.runPrompt();
    console.log(`Recording ${run.tracePath}`);
  }
});
