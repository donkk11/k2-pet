// Minimal companion renderer -- reuses the real state-mapper's SSE stream and the
// same art mapping app.js already uses, stripped of the diagnostic-panel UI.
const art = { idle: "idle", working: "working", executing: "working", editing: "working",
  searching: "checking", "tool-use": "working", checking: "checking", permission: "permission",
  question: "waiting", finished: "finished", interrupted: "waiting", problem: "problem",
  // Real find (2026-10-08): companion.html already has full, correct CSS strip rules
  // for data-motion="listening" and ="speaking" (lines ~39-44 -- right aspect ratios,
  // right file, right frame count, matching assets/animations/listening.png and
  // speaking.png exactly) and both are already in hasStrip below. The ONLY thing
  // stopping them from ever showing was this map aliasing the states to "waiting"/
  // "working" instead of their own real motion name. One-line fix, no new art,
  // no new CSS -- real assets that were built and never wired, now wired.
  listening: "listening", speaking: "speaking", attention: "waiting",
  // KK's own ask (2026-10-08): reading a clicked task summary out loud should look
  // different from Nimba's realtime "speaking" (which gets its own real mouth-
  // animation strip now, see above) -- reuses the already-built 16-direction gaze
  // look-around instead (see startWaitingGlances() below), which "waiting" already
  // drives for every other state mapped to it. No new animation code needed.
  // Since 2026-10-10 this is only the fallback: Gentleman KK, while actually reading
  // (not paused), is switched to the "speaking" presenter in render() below.
  reading: "waiting" };
// "finished" was silently aliased to the static idle pose -- real, already-extracted
// jumping art (5 real frames, verified 173x198 each) existed but was never wired to
// anything. KK's own real observation: nothing moves when a task finishes. Same real
// gap for "permission": a real 6-frame thumbs-up/acknowledging strip existed in the
// atlas (row 6) but only a single static frame had ever been extracted from it --
// question/listening/interrupted keep that static pose, permission gets the real
// animated strip since KK specifically asked for its own distinct reaction.
const hasStrip = new Set(["working", "checking", "listening", "speaking", "finished", "permission"]);
// "idle" is deliberately NOT in hasStrip: Gentleman KK (the default character) hits
// this same check unconditionally (see the CHARACTER !== "gentleman-kk" gate below) and
// states.css has no #pet-sprite rule for data-motion="idle" for him -- adding it here
// would show an empty sprite div instead of his real static idle pose. Idle-as-a-strip
// is opt-in per character, gated on the manifest actually declaring one, handled below.

const petCard = document.getElementById("pet-card");
const petImg = document.getElementById("pet");
let lastRealMotion = "idle";
let dragging = false;
let gazing = false; // true while the compose box is focused and tracking the cursor
// True while hovering K2 during a working-family motion -- "acknowledge you without
// stopping." KK's own ask; no dedicated art exists yet (needs a real 6-frame "just
// wait" strip), so this borrows the waiting.png pose as an honest placeholder rather
// than the old jump-to-hover-wave, which made him drop everything to wave mid-task.
let workAttention = false;
const WORKING_FAMILY = new Set(["working", "checking"]);

const petSprite = document.getElementById("pet-sprite");
const chromeEl = document.getElementById("chrome");

// Real character selection, read once at load (the picker below writes this and
// reloads the page to apply it -- swapping mid-session would mean juggling two
// live animation timers/paths, reload is simpler and safer). "gentleman-kk" is the
// untouched default path: every hardcoded /assets/... reference elsewhere in this
// file and in companion.html's CSS keeps working exactly as before for it, zero
// risk of regressing the one character that's fully proven. Any OTHER character
// gets its static-state path rewritten to its own folder, and its animation strips
// injected as real CSS rules built from its own manifest.json (CSS url() can't take
// a variable, so this is the only way to actually swap which image an existing
// class-based rule points at).
let CHARACTER = "gentleman-kk";
try { CHARACTER = localStorage.getItem("k2-character") || "gentleman-kk"; } catch {}

// Real ask (KK, 2026-10-10): "let not do away [with] the old one, we can have
// them like skins" -- glass (the new default) and classic (the real original,
// restored byte-for-byte from git, see companion.html's body.skin-classic
// block) coexist as a pure CSS toggle, applied live -- no reload, unlike
// character swap, since nothing here touches sprite paths or JS state.
let SKIN = "glass";
try { SKIN = localStorage.getItem("k2-skin") || "glass"; } catch {}
function applySkin(skin) {
  document.body.classList.toggle("skin-classic", skin === "classic");
  document.body.classList.toggle("skin-glass", skin !== "classic");
}
applySkin(SKIN);
const STATE_BASE = CHARACTER === "gentleman-kk" ? "/assets/states" : `/assets/characters/${CHARACTER}/states`;

const ANIM_SELECTOR = {
  "running-right": '.pet-card[data-motion="running-right"] #pet-sprite',
  "running-left": '.pet-card[data-motion="running-left"] #pet-sprite',
  waving: ".pet-card.hover-wave #pet-sprite",
  working: '.pet-card[data-motion="working"] #pet-sprite',
  checking: '.pet-card[data-motion="checking"] #pet-sprite',
  jumping: '.pet-card[data-motion="finished"] #pet-sprite',
  "permission-wait": '.pet-card[data-motion="permission"] #pet-sprite',
  idle: '.pet-card[data-motion="idle"] #pet-sprite',
};
const ANIM_DURATIONS = {
  "running-right": "0.8s", "running-left": "0.8s", waving: "1.1s",
  working: "4.8s", checking: "4.5s", jumping: "0.6s", "permission-wait": "1.4s",
  idle: "3.6s", // calm pace by default -- a real idle loop, not a frantic one
};

// Real gap the character-generation adapter surfaced immediately: build_character.py can
// now produce a character missing an optional row (e.g. no dedicated "checking" animation
// for a loose, unstructured sheet like the Einstein one). Without this, that motion would
// silently fall through to states.css's own unconditional default rule -- which points at
// GENTLEMAN KK's art -- so a different character would flash into Gentleman KK's face for
// that one state. These two sets, populated from the real manifest, let paint() know
// exactly what this character actually has and fall back to a real pose of ITS OWN instead.
let characterAnimationKeys = null;
let characterStateKeys = null;
let characterHasGaze = CHARACTER === "gentleman-kk"; // only Gentleman KK is guaranteed to have real gaze frames until proven otherwise
const MOTION_TO_ANIM_KEY = { "running-right": "running-right", "running-left": "running-left", working: "working", checking: "checking", finished: "jumping", permission: "permission-wait", idle: "idle" };

function resolveStaticSrc(motion) {
  if (CHARACTER === "gentleman-kk") return `${STATE_BASE}/${motion}.png`;
  if (characterStateKeys && characterStateKeys.has(motion)) return `${STATE_BASE}/${motion}.png`;
  if (characterStateKeys && characterStateKeys.has("waiting")) return `${STATE_BASE}/waiting.png`;
  return `${STATE_BASE}/idle.png`; // the one row build_character.py always requires
}

async function applyCharacterOverrides() {
  if (CHARACTER === "gentleman-kk") return; // default path -- nothing to override
  try {
    const res = await fetch(`/assets/characters/${CHARACTER}/manifest.json`);
    const manifest = await res.json();
    characterAnimationKeys = new Set(Object.keys(manifest.animations || {}));
    characterStateKeys = new Set(Object.keys(manifest.states || {}));
    characterHasGaze = Object.keys(manifest.gaze || {}).length > 0;
    const rules = Object.entries(manifest.animations || {}).map(([key, info]) => {
      const selector = ANIM_SELECTOR[key];
      if (!selector) return "";
      const steps = Math.max(1, info.frames - 1);
      const duration = ANIM_DURATIONS[key] || "1s";
      return `${selector}{aspect-ratio:${info.aspectRatio};background-image:url('/assets/characters/${CHARACTER}/${info.file}');background-size:${info.frames * 100}% 100%;animation:k2-strip-eight ${duration} steps(${steps},end) infinite}`;
    });
    const style = document.createElement("style");
    style.id = "k2-character-overrides";
    style.textContent = rules.join("\n");
    document.head.appendChild(style);
  } catch (e) {
    characterAnimationKeys = new Set(); // fetch failed -- treat as "no strips available" rather than risk leaking the wrong character's art
    characterStateKeys = new Set();
    console.warn("[k2-pet] character override failed, staying on default art:", e);
  }
}
applyCharacterOverrides();
if (CHARACTER !== "gentleman-kk") petImg.src = `${STATE_BASE}/idle.png`; // avoid a flash of the wrong character before the first real state arrives

// Real fix for "click-through doesn't fit his body": a fixed percentage (78% width)
// can't work because every pose has a different real aspect ratio and rendered size --
// idle is narrow, waving is wider, running strips wider still. Instead of guessing,
// measure the ACTUAL on-screen box of whichever element is currently visible (the
// browser already computed this correctly for object-fit:contain / aspect-ratio), union
// it with the floor's box, and hand real window-local pixels to Python so the
// click-through hit-test can match his real silhouette instead of an approximation.
// KK's real complaint (2026-10-10), with a screenshot proving it: the bubble sat
// at a flat top:22px no matter what, and during the TED-presenter "speaking"
// animation specifically, his actual head sits higher in that strip's own frame
// than has-bubble's 66% shrink alone accounts for -- the card covered his face.
// Real fix, not a per-pose tuned number (which is exactly the kind of guess this
// project's own comments repeatedly warn against): measure the ACTUAL rendered
// top edge of whichever element is currently visible (the browser already lays
// this out correctly for both the static <img> and the animated #pet-sprite
// strip, same trick reportHotRect's own hot-zone math already relies on) and
// place the open bubble's bottom edge a small gap above THAT, every time,
// regardless of character, pose, or window size.
const HEAD_GAP = 12;
function positionOpenBubble() {
  const bubbles = [compose, alertBubble, statusCard, charPicker, voicePicker, taskPicker];
  const open = bubbles.find((el) => el && el.classList.contains("open"));
  if (!open) return;
  const stageRect = document.getElementById("stage").getBoundingClientRect();
  const visible = petCard.classList.contains("has-strip") ? petSprite : petImg;
  const headTop = visible.getBoundingClientRect().top - stageRect.top;
  const top = Math.max(10, headTop - HEAD_GAP - open.offsetHeight);
  open.style.top = `${top}px`;
}

function reportHotRect() {
  // Real fix: K2 used to always reserve headroom above his head for a bubble, even
  // fully idle with nothing showing -- a permanently empty gap for no reason. He now
  // only shrinks (see has-bubble in the CSS) while one of these is actually open. This
  // runs first and unconditionally (not gated on pywebview below) since it's a pure
  // layout concern, not part of the native click-through hot-zone reporting.
  const anyBubbleOpen = [compose, alertBubble, charPicker, voicePicker, taskPicker, statusCard].some(
    (el) => el && el.classList.contains("open")
  );
  document.body.classList.toggle("has-bubble", anyBubbleOpen);
  // Reposition BEFORE measuring the hot-zone below -- the hot-zone union needs
  // the bubble's real final position, not wherever CSS's flat top:22px left it.
  // Called twice: now (catches most real cases) and again after the has-bubble
  // shrink's own .2s CSS transition actually finishes, since measuring mid-
  // transition would otherwise catch his head at a still-moving height.
  positionOpenBubble();
  setTimeout(positionOpenBubble, 260);

  if (!window.pywebview?.api?.update_hot_rect) return;
  // Real bug found from live testing: when hidden, #pet-card/#chrome are display:none
  // (zero-size rects), collapsing the hot-zone to nothing -- so #peek, the one thing
  // still visible, fell outside it and stopped registering clicks entirely. Hidden
  // state needs its own rect, based on the element actually on screen.
  if (document.body.classList.contains("hidden")) {
    const p = peek.getBoundingClientRect();
    window.pywebview.api.update_hot_rect(p.left, p.top, p.width, p.height);
    return;
  }
  const visible = petCard.classList.contains("has-strip") ? petSprite : petImg;
  const a = visible.getBoundingClientRect();
  const b = chromeEl.getBoundingClientRect();
  let left = Math.min(a.left, b.left), top = Math.min(a.top, b.top);
  let right = Math.max(a.right, b.right), bottom = Math.max(a.bottom, b.bottom);
  // Real bug found live: compose, the alert bubble, and the new character picker all
  // sit ABOVE the character (top:22px), in space the character+chrome union never
  // reached -- a real click there passed straight through the window to whatever's
  // behind it on the desktop instead of ever reaching the DOM. Union in whichever of
  // these interactive overlays is actually open right now.
  for (const el of [compose, alertBubble, charPicker, voicePicker, taskPicker, statusCard]) {
    if (el && el.classList.contains("open")) {
      const r = el.getBoundingClientRect();
      left = Math.min(left, r.left); top = Math.min(top, r.top);
      right = Math.max(right, r.right); bottom = Math.max(bottom, r.bottom);
    }
  }
  window.pywebview.api.update_hot_rect(left, top, right - left, bottom - top);
}

// Real task-story intro for Gentleman KK's working state -- a genuine, evidence-verified
// 30-frame sequence (wave -> look -> run -> stop -> sit -> open laptop -> work) KK built
// via actual Codex CLI in a separate project (k2-story-update) and had never wired into
// this app until now. Its own real manifest declares frames 0-23 as a one-time intro and
// 24-29 as the persistent work loop -- CSS steps() can't express "play once then loop a
// different sub-range" on its own, so this steps through frames directly instead.
// Gentleman-kk only; K2 Nkama keeps its own simple working loop via the character-
// override system, since this specific asset was only ever built for Gentleman KK.
const TASK_STORY = { frames: 30, frameWidth: 158, frameHeight: 202, frameDurationMs: 150, loopStartIndex: 24 };
let taskStoryTimer = null;
let taskStoryActive = false;
function stopTaskStory() {
  clearTimeout(taskStoryTimer);
  taskStoryTimer = null;
  taskStoryActive = false;
}
function paintTaskStoryFrame(i) {
  petSprite.style.backgroundImage = "url('/assets/animations/task-story.png')";
  petSprite.style.backgroundSize = `${TASK_STORY.frames * 100}% 100%`;
  petSprite.style.backgroundPosition = `${(i / (TASK_STORY.frames - 1)) * 100}% 50%`;
  petSprite.style.aspectRatio = `${TASK_STORY.frameWidth}/${TASK_STORY.frameHeight}`;
  petSprite.style.animation = "none"; // frames are driven directly, not by a CSS steps() loop
}
function startTaskStory() {
  if (taskStoryActive) return; // already mid-intro or looping -- don't restart from frame 0
  taskStoryActive = true;
  let i = 0;
  (function tick() {
    if (!taskStoryActive) return;
    paintTaskStoryFrame(i);
    i = i < TASK_STORY.frames - 1 ? i + 1 : TASK_STORY.loopStartIndex;
    taskStoryTimer = setTimeout(tick, TASK_STORY.frameDurationMs);
  })();
}

// TED-style "speaking-presenter" for Gentleman KK (KK's ask, 2026-10-10): speaking is a
// performance, not a looped mouth. Real art: assets/animations/speaking-presenter.png,
// 8 frames, all one scale and ground line, head anchored so only the hands and feet move.
//   0 open hands (neutral)   1-3 walking, open hand out   4 stopped, open hands
//   5 pointing at the listener   6 wide open hands (emphasis)   7 hands together
// Each step is [frame, holdMs, dx]. dx is travel in percent of the sprite's own width
// while that frame is held, so the walk scales with whatever size the window is.
// Cycle: talk -> two slow steps -> stop (the pause before the point lands) -> key-point
// gesture -> settle -> repeat, walking back the other way, mirrored, on the next pass.
// The walk frames only face right, so the whole next pass is mirrored rather than
// splicing a mirrored walk between un-mirrored stand frames.
const PRESENTER = { frames: 8, frameWidth: 209, frameHeight: 300, startX: -8 };
const PRESENTER_SCRIPT = [
  [0, 600, 0], [4, 600, 0], [7, 600, 0], [4, 600, 0], [0, 600, 0], // speak, hands working
  [1, 420, 4], [2, 420, 4], [3, 420, 4], [2, 420, 4],              // two slow steps
  [4, 800, 0],                                                     // stop, beat of silence
  [5, 900, 0], [6, 800, 0],                                        // the key point
  [7, 600, 0],                                                     // settle, then continue
];
let presenterTimer = null;
let presenterActive = false;
function stopPresenter() {
  clearTimeout(presenterTimer);
  presenterTimer = null;
  presenterActive = false;
  // Only the presenter's own properties: another sequence (task story) may have just
  // painted its frame and must keep its background, size and ratio.
  petSprite.style.transform = "";
  petSprite.style.transition = "";
}
function paintPresenterFrame(i, x, facing, travelMs) {
  petSprite.style.backgroundImage = "url('/assets/animations/speaking-presenter.png')";
  petSprite.style.backgroundSize = `${PRESENTER.frames * 100}% 100%`;
  petSprite.style.backgroundPosition = `${(i / (PRESENTER.frames - 1)) * 100}% 50%`;
  petSprite.style.aspectRatio = `${PRESENTER.frameWidth}/${PRESENTER.frameHeight}`;
  petSprite.style.animation = "none";
  petSprite.style.transition = `transform ${travelMs}ms linear`;
  petSprite.style.transform = `translateX(${x}%) scaleX(${facing})`;
}
function startPresenter() {
  if (presenterActive) return; // repeated "speaking" events must not restart the sequence
  presenterActive = true;
  let step = 0, x = PRESENTER.startX, facing = 1;
  (function tick() {
    if (!presenterActive) return;
    const [frame, holdMs, dx] = PRESENTER_SCRIPT[step];
    x += dx * facing;
    paintPresenterFrame(frame, x, facing, dx ? holdMs : 0);
    if (dx) requestAnimationFrame(reportHotRect); // he moved: keep the click-through zone on him
    step += 1;
    if (step >= PRESENTER_SCRIPT.length) { step = 0; facing = -facing; }
    presenterTimer = setTimeout(tick, holdMs);
  })();
}

function paint(motion) {
  petCard.dataset.motion = motion;
  let strip = hasStrip.has(motion) || motion === "running-right" || motion === "running-left";
  if (strip && CHARACTER !== "gentleman-kk") {
    const animKey = MOTION_TO_ANIM_KEY[motion];
    if (!animKey || !characterAnimationKeys || !characterAnimationKeys.has(animKey)) strip = false;
  }
  // Real ask: an idle animation, not just a static pose -- opt-in per character (see
  // the hasStrip comment above for why this can't just live in hasStrip itself).
  if (motion === "idle" && CHARACTER !== "gentleman-kk" && characterAnimationKeys?.has("idle")) {
    strip = true;
  }
  petCard.classList.toggle("has-strip", strip && !workAttention);
  if (motion === "working" && CHARACTER === "gentleman-kk") {
    stopPresenter();
    startTaskStory();
  } else if (motion === "speaking" && CHARACTER === "gentleman-kk") {
    // Only his own art has the presenter frames; other characters keep the plain
    // speaking strip from their manifest. "reading" (a task summary read aloud) is a
    // different state and keeps its look-around, per KK's earlier ask.
    stopTaskStory();
    startPresenter();
  } else {
    stopTaskStory();
    stopPresenter();
    petSprite.style.cssText = ""; // release the inline overrides so CSS class rules resume for other motions
  }
  if (!strip && !gazing && !workAttention) petImg.src = resolveStaticSrc(motion);
  // Idle-glances swap the STATIC #pet image's src -- pointless (and invisible, since
  // .has-strip hides #pet) when idle is itself an animated strip for this character.
  if (motion === "idle" && !strip && !gazing && !dragging) startIdleGlances();
  else stopIdleGlances();
  if (motion === "waiting" && !gazing && !dragging) startWaitingGlances();
  else stopWaitingGlances();
  requestAnimationFrame(reportHotRect); // after layout/paint actually applies the new state
}
window.addEventListener("resize", reportHotRect);

// Real "looks around" idle behaviour -- KK's own complaint was that the pet just
// floats/bounces while Codex's character glances around while waiting. Reuses the
// same look-left/look-right art already extracted for typing-gaze, on a loose
// randomized timer so it doesn't look mechanically looped.
let idleGlanceTimer = null;
function stopIdleGlances() {
  clearTimeout(idleGlanceTimer);
  idleGlanceTimer = null;
}
function idleGlanceTick() {
  if (petCard.dataset.motion !== "idle" || gazing || dragging || petCard.classList.contains("hover-wave")) {
    idleGlanceTimer = null;
    return;
  }
  const roll = Math.random();
  const glance = roll < 0.38 ? "look-left" : roll < 0.76 ? "look-right" : null;
  if (glance) petImg.src = `/assets/states/${glance}.png`;
  idleGlanceTimer = setTimeout(() => {
    if (petCard.dataset.motion === "idle" && !gazing && !dragging) petImg.src = "/assets/states/idle.png";
    idleGlanceTimer = setTimeout(idleGlanceTick, 2200 + Math.random() * 2600);
  }, glance ? 750 + Math.random() * 400 : 200);
}
function startIdleGlances() {
  // Real limitation, stated plainly rather than 404ing: this reuses gentleman-kk's own
  // legacy look-left/look-right pair, which no other character has had extracted yet.
  // Idle-glancing simply doesn't fire for another character until that's done -- staying
  // still is honest; guessing at a path that doesn't exist isn't.
  if (CHARACTER !== "gentleman-kk") return;
  if (idleGlanceTimer) return;
  idleGlanceTimer = setTimeout(idleGlanceTick, 1800 + Math.random() * 2000);
}

// Real 16-direction gaze while waiting (question/interrupted/listening -- anything
// that paints the "waiting" motion). Same "looks around" idea as idle glances above,
// but drawing on the FULL real gaze set extracted from the atlas instead of just
// left/right -- these are the same 16 angles already validated in this project's own
// research (outputs/proofpaw-run/qa/direction-semantics.json: 14 pass, 2
// warning-but-readable at the 157.5/337.5 boundaries, none failed), just never wired
// into live behavior before now. "Waiting" is exactly the state where a character
// looking around in real directions reads as alive rather than stuck.
const GAZE_DEGREES = ["000", "022.5", "045", "067.5", "090", "112.5", "135", "157.5",
  "180", "202.5", "225", "247.5", "270", "292.5", "315", "337.5"];
let waitingGlanceTimer = null;
function stopWaitingGlances() {
  clearTimeout(waitingGlanceTimer);
  waitingGlanceTimer = null;
}
function waitingGlanceTick() {
  if (petCard.dataset.motion !== "waiting" || gazing || dragging || workAttention) {
    waitingGlanceTimer = null;
    return;
  }
  const glance = Math.random() < 0.7 ? GAZE_DEGREES[Math.floor(Math.random() * GAZE_DEGREES.length)] : null;
  if (glance) petImg.src = `${STATE_BASE}/gaze/look-${glance}.png`;
  waitingGlanceTimer = setTimeout(() => {
    if (petCard.dataset.motion === "waiting" && !gazing && !dragging) petImg.src = `${STATE_BASE}/waiting.png`;
    waitingGlanceTimer = setTimeout(waitingGlanceTick, 2000 + Math.random() * 2600);
  }, glance ? 700 + Math.random() * 500 : 200);
}
function startWaitingGlances() {
  // Same honest gap as idle-glancing: a character built without real gaze frames (e.g. a
  // loose, unstructured sheet with no dedicated head-turn poses) just holds still instead
  // of 404ing for images that were never extracted.
  if (!characterHasGaze) return;
  if (waitingGlanceTimer) return;
  waitingGlanceTimer = setTimeout(waitingGlanceTick, 1200 + Math.random() * 1800);
}

const alertBubble = document.getElementById("alert-bubble");
const alertText = document.getElementById("alert-text");
// Real, honest labels -- each one taken straight from state-mapper.mjs's own
// VERIFIED_STATES documentation of what that state actually means, not invented copy.
// idle and attention are deliberately absent: idle has nothing to report, attention
// already gets the alert bubble.
const STATE_LABELS = {
  working: "Working", executing: "Running command", editing: "Editing files",
  searching: "Searching", "tool-use": "Using tool", checking: "Reviewing",
  permission: "Needs permission", question: "Needs input", finished: "Finished",
  interrupted: "Interrupted", problem: "Problem", listening: "Listening", speaking: "Speaking",
  reading: "Reading",
};
const statusCard = document.getElementById("status-card");
const statusTitle = document.getElementById("status-title");
const statusCaption = document.getElementById("status-caption");

// Real ask: "let me hide it when it pops out, but when it changes state (e.g. working
// -> finished) let it pop back out." So the dismissal only suppresses the CURRENT
// state's card -- it's cleared the moment render() sees an actually different state,
// not on a timer and not permanently.
let statusDismissed = false;
statusCard.addEventListener("click", () => {
  statusDismissed = true;
  statusCard.classList.remove("open");
  requestAnimationFrame(reportHotRect); // shrink the native hot-zone back down, same fix as the picker's own close path
});

// KK's ask (2026-10-10): server is the source of truth (same pattern as
// isReading/isPetPaused below) -- never guessed client-side, so a toggle made
// from a different window or a page reload both stay honest.
let isMuted = false;
let lastRealState = "idle", lastAlertMessage = null, lastCaption = null;
// Real ask: clicking during the finish celebration should acknowledge it early
// (dismiss into a waiting pose) rather than making him dance for the full safety-net
// window. Guards against a stray unrelated event re-triggering the dance while the
// underlying state genuinely hasn't changed (still "finished").
let finishedAcknowledged = false;
function render(state, alertMessage, caption, hasResult, isPaused, muted) {
  if (finishedAcknowledged && state === lastRealState) return; // nothing real changed
  finishedAcknowledged = false;
  isMuted = !!muted;
  updateMuteRow();
  if (state !== lastRealState) statusDismissed = false; // a real state change pops it back out
  lastRealState = state; lastAlertMessage = alertMessage; lastCaption = caption;
  // Same icon, three real states -- KK's ask (2026-10-08): speaker while idle,
  // pause while actually reading, resume while paused. Driven by the server's own
  // state (state === "reading") and isPaused, never guessed client-side.
  isReading = state === "reading";
  isPetPaused = !!isPaused;
  // Real bug KK caught (2026-10-09, read as "it freezes" when switching voices
  // mid-read): the glow pulse was keyed on hasResult alone, so while isReading was
  // true the button showed the pause icon AND kept pulsing its "new result ready"
  // glow at the same time -- two states visually fighting, nothing server-side
  // actually stuck (confirmed live: /set-voice answered in 0.02s mid-playback).
  // Glow only means something while idle; reading/paused get their own icon instead.
  btnSpeak.classList.toggle("has-result", !!hasResult && !isReading);
  updateSpeakIcon();
  let motion = art[state] || "idle";
  // KK's ask (2026-10-10), superseding his 2026-10-08 look-around: reading a result
  // aloud gets the same TED-style presenter as speaking. Only Gentleman KK has those
  // frames, so every other character keeps the look-around via "waiting". While paused
  // he is silent, so he drops back to the calm waiting pose and resumes talking on resume.
  if (state === "reading" && CHARACTER === "gentleman-kk" && !isPaused) motion = "speaking";
  lastRealMotion = motion;
  if (!dragging && !gazing && !workAttention) paint(motion);
  // Real Notification hook fire -- Claude needs you while you're looking at something
  // else. Shows the actual summary text, not just a generic pose change, and hides
  // itself again once the alert naturally expires server-side.
  const showAlert = state === "attention" && !!alertMessage;
  alertBubble.classList.toggle("open", showAlert);
  document.body.classList.toggle("has-alert", showAlert);
  if (showAlert) alertText.textContent = alertMessage;

  // The live activity card -- real state label + the real caption from the actual
  // hook payload (a Bash tool's own description, a file path, a search query...),
  // never a placeholder. Mutually exclusive with the alert bubble and the compose box,
  // which occupy the same spot above his head.
  const label = STATE_LABELS[state];
  const showStatus = !!label && !showAlert && !statusDismissed && !compose.classList.contains("open") && !charPicker.classList.contains("open") && !voicePicker.classList.contains("open") && !taskPicker.classList.contains("open");
  statusCard.classList.toggle("open", showStatus);
  // KK's ask (2026-10-09): the card should read as alive while something's actually
  // in progress -- "finished"/"interrupted"/"problem" are over states (a done task
  // still breathing like it's running would be dishonest, not cool), everything
  // else mapped to a real label is genuinely ongoing.
  const OVER_STATES = new Set(["finished", "interrupted", "problem"]);
  statusCard.classList.toggle("live", showStatus && !OVER_STATES.has(state));
  if (showStatus) {
    statusTitle.textContent = label.toUpperCase();
    statusCaption.textContent = caption || "";
    statusCaption.style.display = caption ? "block" : "none";
  }
}

const source = new EventSource("/events");
source.onmessage = (e) => {
  try {
    const d = JSON.parse(e.data);
    render(d.state, d.alertMessage, d.caption, d.hasResult, d.isPaused, d.isMuted);
  } catch {}
};

const btnSpeak = document.getElementById("btn-speak");
const ICON_SPEAK = btnSpeak.innerHTML; // the static markup already in companion.html
const ICON_PAUSE = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor"/></svg>';
const ICON_RESUME = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M7 4l13 8-13 8V4z" fill="currentColor"/></svg>';
let isReading = false, isPetPaused = false;
// (updateSpeakIcon is defined once, below, after the K2 Voice Link state it
// also needs to read -- was two separate functions of the same name during
// editing; real bug, caught before shipping, not left as dead code.)
// KK's ask (2026-10-08): same icon, click toggles pause/resume while reading,
// starts reading when idle -- the real state (isReading/isPetPaused) decides which
// endpoint fires, not a locally-guessed toggle that could drift from the server.
// Real redesign (2026-10-10): starting a read now also checks selectedTaskCwd --
// if a task picker row is selected, this plays THAT task (/speak-task); otherwise
// it falls back to the previous behavior (/speak-last), so nothing selected means
// nothing changes. Pause/resume need no special-casing: /speak-pause and
// /speak-resume already act on whichever process is actually running server-side
// (activeSpeechProcess), regardless of which endpoint started it (confirmed in
// server.mjs -- /speak-task calls the exact same speakText()/generation-counter
// machinery as /speak-last).
// K2 Voice Link (KK's ask, 2026-10-11): a real, additional voice path -- the
// in-browser engine already proven in k2-pet-lite.html, now wired into the
// real pet too. Deliberately NOT a replacement for the server's /speak-last
// path (the real devil's-advocate review found genuine regressions in a full
// swap: SIGSTOP-based pause has no browser equivalent, the server tracks
// voice selection/task routing/mute as shared truth). This is a separate,
// clearly-labeled, fully isolated path with its OWN local state -- toggled
// per KK's choice in the voice picker, off by default, never silently
// replacing the proven server path. Pause/resume use real HTMLAudioElement
// pause()/play() (preserves position natively, confirmed -- no AudioContext
// complexity needed for a single already-generated clip, same conclusion
// KK's own research reached).
let useVoiceLink = false;
try { useVoiceLink = localStorage.getItem("k2-voice-link") === "1"; } catch {}
let vlEngine = null, vlLoading = null;
let vlReading = false, vlPaused = false;
window.__vl = () => ({ vlReading, vlPaused, useVoiceLink, src: vlAudio.src, audioPaused: vlAudio.paused, currentTime: vlAudio.currentTime }); // real debug hook, harmless
const vlAudio = new Audio();
vlAudio.addEventListener("ended", () => { vlReading = false; vlPaused = false; updateSpeakIcon(); });
function updateSpeakIcon() {
  const reading = useVoiceLink ? vlReading : isReading;
  const paused = useVoiceLink ? vlPaused : isPetPaused;
  btnSpeak.innerHTML = reading ? (paused ? ICON_RESUME : ICON_PAUSE) : ICON_SPEAK;
  btnSpeak.title = reading ? (paused ? "Resume reading" : "Pause reading")
    : useVoiceLink ? "Hear last result (K² Voice Link)" : "Hear last result";
}
async function loadVoiceLink() {
  if (vlEngine) return vlEngine;
  if (vlLoading) return vlLoading;
  vlLoading = (async () => {
    const { KokoroTTS: K2VoiceEngine } = await import("/vendor/kk2.js");
    vlEngine = await K2VoiceEngine.from_pretrained("onnx-community/Kokoro-82M-v1.0-ONNX", { dtype: "q8", device: "wasm" });
    return vlEngine;
  })();
  return vlLoading;
}
// Real bug caught live testing this (same real class of bug this project
// already solved once server-side for Kokoro voice-switching: a pause clicked
// WHILE still generating -- before vlAudio.src even exists -- used to call
// .pause() on an empty, sourceless element (a harmless no-op) while vlPaused
// was set true, then the generation finished moments later and autoplayed
// anyway, ignoring the stale pause intent. vlGeneration (same generation-
// counter pattern server.mjs already uses) drops a superseded generate() call
// as a no-op; checking vlPaused again right before the real play() call is
// what actually honors a pause requested during synthesis.
let vlGeneration = 0;
async function speakWithVoiceLink(text) {
  if (!text || !text.trim()) return;
  const myGen = ++vlGeneration;
  // Real fix (KK caught this live): stop BOTH possible sources before a new
  // read starts -- this element's own prior clip, and any server-side
  // (Python/Kokoro) speech that might still be running from before Voice
  // Link was toggled on. Two separate audio systems, no shared awareness
  // otherwise -- this is the actual mutual-exclusion point.
  vlAudio.pause();
  fetch("/speak-stop", { method: "POST" }).catch(() => {});
  vlReading = true; vlPaused = false; updateSpeakIcon();
  try {
    const engine = await loadVoiceLink();
    const audio = await engine.generate(text, { voice: "am_adam", speed: 1.1 });
    if (myGen !== vlGeneration) return; // superseded by a newer read while this one was generating
    vlAudio.src = URL.createObjectURL(audio.toBlob());
    if (vlPaused) { updateSpeakIcon(); return; } // paused during synthesis -- loaded, not auto-played
    await vlAudio.play();
  } catch (err) {
    vlReading = false; updateSpeakIcon();
    console.warn("[k2-voice-link] failed:", err);
  }
}

btnSpeak.addEventListener("click", () => {
  if (useVoiceLink) {
    if (vlReading) {
      if (vlPaused) { vlPaused = false; if (vlAudio.src) vlAudio.play(); }
      else { vlPaused = true; if (vlAudio.src) vlAudio.pause(); }
      updateSpeakIcon();
      return;
    }
    // Real fix: the actual result text was never sent to the browser before
    // (server-only). /last-result-text and /task-result-text are new, added
    // specifically because K2 Voice Link genuinely needs real text to read,
    // not a guess from the caption (which is often empty/unrelated -- it's a
    // live-activity caption, not the finished result).
    (async () => {
      const url = selectedTaskCwd ? `/task-result-text?cwd=${encodeURIComponent(selectedTaskCwd)}` : "/last-result-text";
      let textToRead = "";
      try { ({ text: textToRead } = await (await fetch(url)).json()); } catch {}
      speakWithVoiceLink(textToRead || "Nothing finished yet.");
    })();
    return;
  }
  // Symmetric fix: stop any still-playing Voice Link clip before a
  // server-side read starts, same reasoning as the other direction above.
  if (vlReading && !vlPaused) { vlAudio.pause(); vlReading = false; }
  if (isReading) {
    fetch(isPetPaused ? "/speak-resume" : "/speak-pause", { method: "POST" }).catch(() => {});
    return;
  }
  // Real fix (KK caught this live): the pause icon only appeared once the
  // real SSE round-trip came back (fetch -> server publishes "reading" ->
  // SSE push -> render()) -- a genuine, if usually small, real delay,
  // worse under real load with several tasks active. Optimistic update:
  // flip the icon the instant the click happens, same pattern already used
  // for mute. The next real SSE event still confirms/corrects it either way.
  isReading = true; isPetPaused = false; updateSpeakIcon();
  if (selectedTaskCwd) {
    fetch("/speak-task", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cwd: selectedTaskCwd }),
    }).catch(() => {});
    return;
  }
  fetch("/speak-last", { method: "POST" }).catch(() => {});
});

// Drag-to-run: click and drag the character horizontally, same as the real Codex pet.
// The actual window move is handled natively by pywebview's easy_drag -- this just
// plays the run animation in the direction of travel. (Full-screen-Space visibility
// was later solved for real via a true NSPanel + NSWindowStyleMaskNonactivatingPanel,
// which coexists fine with easy_drag -- see k2-pet-floating-window.py.)
let dragStartX = 0;
let clickMoved = false;
petCard.addEventListener("pointerdown", (e) => {
  dragging = true;
  dragStartX = e.clientX;
  clickMoved = false;
  petCard.setPointerCapture(e.pointerId);
  // Real fix: hover-wave's CSS rule has equal specificity to the running-direction
  // rules and comes later in the stylesheet, so it always won regardless of the real
  // drag state -- K2 kept waving mid-drag instead of running. Clearing it here means
  // the running rule actually gets to apply.
  petCard.classList.remove("hover-wave");
  if (workAttention) { workAttention = false; }
});
petCard.addEventListener("pointermove", (e) => {
  if (!dragging) return;
  const dx = e.clientX - dragStartX;
  if (Math.abs(dx) < 4) return; // ignore a plain click/jitter, only real drag movement
  clickMoved = true;
  paint(dx > 0 ? "running-right" : "running-left");
});
petCard.addEventListener("pointerup", () => {
  dragging = false;
  // Real ask (KK, 2026-10-08): clicking him during the finish celebration should
  // also read the real result out loud, not just dismiss the dance. /speak-last
  // runs `say` server-side on the actual last assistant message (cached by
  // k2-pet-claude-code-emit.sh's extract_last_result()) and republishes the
  // already-verified "speaking" state around it, so the SSE stream shows him
  // actually speaking a moment after this click -- the eager dismiss below is
  // just the immediate visual feedback, not the final word.
  if (!clickMoved && petCard.dataset.motion === "finished") {
    finishedAcknowledged = true;
    petCard.classList.remove("has-strip");
    petImg.src = `${STATE_BASE}/waiting.png`;
    fetch("/speak-last", { method: "POST" }).catch(() => {});
    return;
  }
  paint(lastRealMotion);
});
petCard.addEventListener("pointercancel", () => { dragging = false; paint(lastRealMotion); });

// Hover: a small "come click me" wave when idle. When he's mid-task, don't make him
// drop everything to wave -- acknowledge you without stopping (KK's own ask: "one hand
// keeps typing, the other says just wait"). No dedicated art exists for that yet, so
// this borrows the waiting.png pose; swap this for a real sidecar strip once it exists.
petCard.addEventListener("mouseenter", () => {
  if (dragging || gazing) return;
  // Same real leak this session's adapter surfaced for "checking": hover-wave is a
  // separate code path from paint(), so without this check a character missing a real
  // "waving" animation (e.g. no dedicated greeting pose in a loose sheet) would fall
  // through to states.css's unconditional default rule -- Gentleman KK's wave.
  const hasWave = CHARACTER === "gentleman-kk" || (characterAnimationKeys && characterAnimationKeys.has("waving"));
  if (lastRealMotion === "idle" && hasWave) { petCard.classList.add("hover-wave"); return; }
  if (WORKING_FAMILY.has(lastRealMotion)) {
    workAttention = true;
    petCard.classList.remove("has-strip");
    petImg.src = resolveStaticSrc("waiting");
  }
});
petCard.addEventListener("mouseleave", () => {
  petCard.classList.remove("hover-wave");
  if (workAttention) { workAttention = false; paint(lastRealMotion); }
});

// Accent color -- still tells the two pets apart by hue (gold vs orange-red) even
// without the "CODE/PET" text badge KK asked to remove; kept the class, dropped the label.
const isNimba = location.port === "3042";
document.body.classList.add(isNimba ? "is-nimba" : "is-code");

// Character picker -- KK's real ask: "how do i select in between my pets." Neither a
// live Claude Artifact nor a GitHub page can do this for real -- both run in a browser
// sandbox with no way to reach into this locally-running window and change what it
// renders. This is the real, local mechanism instead: a floor-bar button that lists
// whatever's in assets/characters.json and remembers the choice in localStorage.
// Only one character has a complete real asset set today (Gentleman KK) -- the picker
// is genuinely functional infrastructure, not a promise of characters that don't exist
// yet; adding a second real one later is just adding an entry to that manifest.
const btnCharacter = document.getElementById("btn-character");
const charPicker = document.getElementById("char-picker");
const charList = document.getElementById("char-list");
const CHAR_STORAGE_KEY = "k2-character";

async function loadCharacters() {
  try {
    const res = await fetch("/assets/characters.json");
    const data = await res.json();
    return Array.isArray(data.characters) ? data.characters : [];
  } catch {
    return [];
  }
}

async function renderCharPicker() {
  const characters = await loadCharacters();
  const readyCharacters = characters.filter((c) => c.ready);
  const savedId = localStorage.getItem(CHAR_STORAGE_KEY);
  const selected = readyCharacters.find((c) => c.id === savedId) || readyCharacters[0] || null;
  charList.innerHTML = "";
  for (const c of characters) {
    const row = document.createElement("div");
    const isSelected = !!selected && c.id === selected.id;
    row.className = "char-row" + (isSelected ? " selected" : "") + (c.ready ? "" : " disabled");
    const img = document.createElement("img");
    img.src = c.thumbnail || "";
    img.alt = "";
    const label = document.createElement("span");
    // Honest, not a fake option: only Gentleman KK has its full set of states (idle,
    // working, gaze, ...) extracted so far. K2 Nkama is a real, complete character
    // (../.codex/pets/k2-nkama) but selecting it wouldn't actually change anything yet,
    // so it's shown -- real art, real name -- but marked instead of silently doing
    // nothing if clicked.
    label.textContent = c.ready ? (c.label || c.id) : `${c.label || c.id} (coming soon)`;
    const check = document.createElement("span");
    check.className = "check";
    check.textContent = "✓";
    row.append(img, label, check);
    if (c.ready) {
      row.addEventListener("click", () => {
        if (c.id === CHARACTER) {
          // Real gap an independent review caught: closing the picker here skipped
          // reportHotRect(), leaving the native hot zone sized for the (now-closed)
          // picker instead of shrinking back down.
          charPicker.classList.remove("open");
          requestAnimationFrame(reportHotRect);
          return;
        }
        localStorage.setItem(CHAR_STORAGE_KEY, c.id);
        // CHARACTER and every path derived from it are read once at script startup --
        // reloading is the simplest safe way to actually apply a new one, rather than
        // juggling live animation timers and swapped asset paths mid-session.
        location.reload();
      });
    }
    charList.appendChild(row);
  }
}

// Skin picker -- same row pattern as character/voice, lives inside the same
// panel (no new deck button, no re-measuring the bar's min-width floor for an
// 9th icon -- that's been a real, documented 4-times-repeated bug). Applies
// live via applySkin() (pure CSS, no reload) and persists like character does.
const skinList = document.getElementById("skin-list");
const SKIN_OPTIONS = [
  { id: "glass", label: "Glass (new)" },
  { id: "classic", label: "Classic (original)" },
];
function renderSkinPicker() {
  skinList.innerHTML = "";
  for (const opt of SKIN_OPTIONS) {
    const row = document.createElement("div");
    row.className = "char-row" + (opt.id === SKIN ? " selected" : "");
    const label = document.createElement("span");
    label.textContent = opt.label;
    const check = document.createElement("span");
    check.className = "check";
    check.textContent = "✓";
    row.append(label, check);
    row.addEventListener("click", () => {
      if (opt.id === SKIN) return;
      SKIN = opt.id;
      try { localStorage.setItem("k2-skin", SKIN); } catch {}
      applySkin(SKIN);
      renderSkinPicker(); // re-check the new selection in place, panel stays open
      // Skin changes real geometry (classic's deck is smaller and hover-only vs.
      // glass's always-visible taller one) -- the native click-through hot-zone
      // needs to be re-measured against the new layout, same as every resize path.
      requestAnimationFrame(reportHotRect);
    });
    skinList.appendChild(row);
  }
}

btnCharacter.addEventListener("click", async () => {
  const opening = !charPicker.classList.contains("open");
  charPicker.classList.toggle("open", opening);
  if (opening) {
    statusCard.classList.remove("open");
    compose.classList.remove("open");
    voicePicker.classList.remove("open");
    taskPicker.classList.remove("open");
    document.body.classList.remove("composing");
    await renderCharPicker();
    renderSkinPicker();
  }
  // Real bug: opening/closing the picker changes how much of the window is actually
  // clickable, but nothing was telling the native click-through layer that -- a real
  // mouse click on the picker's rows was passing straight through the window.
  requestAnimationFrame(reportHotRect);
});

// Voice picker -- KK's ask (2026-10-09), same pattern as the character picker just
// above: real catalog from the server (GET /voices, kokoro_server.py's own
// ALLOWED_VOICES), server is the source of truth for the current selection (not
// localStorage) since the server is what actually calls Kokoro.
const btnVoiceSelect = document.getElementById("btn-voice-select");
const voicePicker = document.getElementById("voice-picker");
const voiceList = document.getElementById("voice-list");
// Honest labels, not invented: Kokoro's own naming convention is accent+gender
// prefix (am=American Male, af=American Female, bf/bm=British, ef/em=Spanish).
const VOICE_LABELS = {
  // KK's own cloned-speed voice (2026-10-09), now actually wired and the real
  // default. KK's rebrand (2026-10-11): the real engine underneath is Kokoro
  // (kept exactly as-is in code/comments -- that's accurate, technical, and
  // not user-facing), but this label IS user-facing, so it carries the K2
  // brand instead of a third-party engine name + an internal build tag that
  // meant nothing to him reading his own picker.
  am_kk: "KK (K² Voice Link)",
  am_echo: "Echo (Male)", am_michael: "Michael (Male)", am_adam: "Adam (Male)",
  af_sarah: "Sarah (Female)", af_bella: "Bella (Female)", af_nicole: "Nicole (Female)",
  bf_emma: "Emma (British F)", bm_george: "George (British M)",
  ef_dora: "Dora (Spanish F)", em_alex: "Alex (Spanish M)", em_santa: "Santa (Spanish M)",
};

// KK's ask (2026-10-10): "give me an option to mute it... maybe I'm in a
// meeting." Only gates automatic announcements (/speak-announcement, called by
// k2-pet-claude-code-emit.sh's Stop/StopFailure/Notification cases) -- a
// deliberate click on #btn-speak or a task row is never affected, muted or not.
const muteRow = document.getElementById("mute-row");
const muteCheck = document.getElementById("mute-check");
function updateMuteRow() {
  muteRow.classList.toggle("muted", isMuted);
  muteRow.title = isMuted ? "Automatic announcements are muted -- click to unmute" : "Click to mute automatic announcements (Done., alerts)";
}
muteRow.addEventListener("click", async () => {
  const next = !isMuted;
  isMuted = next; // optimistic -- the next real SSE event confirms it either way
  updateMuteRow();
  try {
    await fetch("/set-mute", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ muted: next }),
      signal: AbortSignal.timeout(3000),
    });
  } catch {} // server will still report the real state on its next event either way
});

// K2 Voice Link toggle -- purely local (no server round-trip, this is a
// client-side-only engine choice, unlike mute which is real shared server
// state across every window polling the same pet).
const voicelinkRow = document.getElementById("voicelink-row");
function updateVoicelinkRow() {
  voicelinkRow.classList.toggle("muted", useVoiceLink);
  voicelinkRow.title = useVoiceLink
    ? "Using K² Voice Link (in-browser, beta) -- click to switch back to the server voice"
    : "Click to use K² Voice Link (in-browser neural voice, beta -- first use downloads ~30MB once)";
}
voicelinkRow.addEventListener("click", () => {
  useVoiceLink = !useVoiceLink;
  try { localStorage.setItem("k2-voice-link", useVoiceLink ? "1" : "0"); } catch {}
  updateVoicelinkRow();
  updateSpeakIcon();
  if (useVoiceLink) loadVoiceLink().catch(() => {}); // warm it up now, not on first click-to-speak
});
updateVoicelinkRow();

async function renderVoicePicker() {
  let voices = [], current = null;
  try {
    // KK's report (2026-10-09): a freeze switching voices mid-read. Server-side
    // tested clean (set-voice answered in 0.02s during active playback), but this
    // timeout is real defense-in-depth regardless -- nothing in this picker should
    // ever be able to hang the UI waiting on a fetch that never resolves.
    const res = await fetch("/voices", { signal: AbortSignal.timeout(3000) });
    ({ voices, current } = await res.json());
  } catch { /* server not running or too slow -- empty list, not a frozen UI */ }
  voiceList.innerHTML = "";
  for (const id of voices) {
    const row = document.createElement("div");
    row.className = "char-row" + (id === current ? " selected" : "");
    const label = document.createElement("span");
    label.textContent = VOICE_LABELS[id] || id;
    const check = document.createElement("span");
    check.className = "check";
    check.textContent = "✓";
    row.append(label, check);
    row.addEventListener("click", async () => {
      if (id === current) { voicePicker.classList.remove("open"); requestAnimationFrame(reportHotRect); return; }
      await fetch("/set-voice", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voice: id }),
        signal: AbortSignal.timeout(3000),
      }).catch(() => {});
      voicePicker.classList.remove("open"); // closes regardless -- a slow/failed request never leaves the picker stuck open
      requestAnimationFrame(reportHotRect);
    });
    voiceList.appendChild(row);
  }
}

btnVoiceSelect.addEventListener("click", async () => {
  const opening = !voicePicker.classList.contains("open");
  voicePicker.classList.toggle("open", opening);
  if (opening) {
    statusCard.classList.remove("open");
    compose.classList.remove("open");
    charPicker.classList.remove("open");
    taskPicker.classList.remove("open");
    document.body.classList.remove("composing");
    await renderVoicePicker();
  }
  requestAnimationFrame(reportHotRect);
});

// KK's "collision" ask (2026-10-09): which task finished, which is still running,
// and a real way to switch which one to hear -- not just the single global
// /speak-last. Same picker pattern as voice/character, server is the source of
// truth (GET /tasks), never guessed client-side.
const btnTasks = document.getElementById("btn-tasks");
const taskPicker = document.getElementById("task-picker");
const taskList = document.getElementById("task-list");
const TASK_STATE_LABELS = { working: "running", finished: "finished", problem: "problem", interrupted: "interrupted", idle: "idle" };

// Real redesign (KK's ask, 2026-10-10): "when I click on the task, it should select
// it, then when I click the speaker icon, it plays that task" -- clicking a row no
// longer fires /speak-task immediately (the real complaint: it started speaking with
// no way to stop). It now only sets which task #btn-speak will act on next; null
// means "no explicit selection", and #btn-speak's own handler below falls back to
// /speak-last in that case, so behavior with nothing selected is unchanged.
let selectedTaskCwd = null;

// Real fix for "same start names but not all name" (KK's screenshot of Claude Code's
// own session list: two sessions under one project folder, same folder name shown).
// There's no session-title field available anywhere in this pipeline to match that --
// not invented here. What IS real and available is each task's full cwd (already in
// every /tasks row) -- so when two tracked tasks share the same folder-name label,
// each one gets real path context appended (the parent folder) instead of silently
// staying indistinguishable. Single, non-colliding labels are untouched.
function disambiguateLabels(list) {
  const counts = new Map();
  for (const t of list) counts.set(t.label, (counts.get(t.label) || 0) + 1);
  return list.map((t) => {
    if (counts.get(t.label) === 1) return { ...t, displayLabel: t.label };
    const parts = t.cwd.split("/").filter(Boolean);
    const parent = parts.length > 1 ? parts[parts.length - 2] : null;
    return { ...t, displayLabel: parent ? `${t.label} · ${parent}` : t.label };
  });
}

async function renderTaskPicker() {
  let list = [];
  try {
    const res = await fetch("/tasks", { signal: AbortSignal.timeout(3000) });
    ({ tasks: list } = await res.json());
  } catch { /* server not running -- empty list, not a crash */ }
  taskList.innerHTML = "";
  if (list.length === 0) {
    const empty = document.createElement("div");
    empty.className = "task-row disabled";
    const label = document.createElement("span");
    label.className = "task-label";
    label.textContent = "No tracked tasks yet";
    empty.appendChild(label);
    taskList.appendChild(empty);
    return;
  }
  for (const t of disambiguateLabels(list)) {
    const row = document.createElement("div");
    const isSelected = t.cwd === selectedTaskCwd;
    row.className = "task-row" + (t.hasResult ? "" : " disabled") + (isSelected ? " selected" : "");
    row.dataset.state = t.state; // real per-state gradient fill (CSS), same state the dot always keyed off
    const dot = document.createElement("span");
    dot.className = `task-dot ${t.state}`;
    const label = document.createElement("span");
    label.className = "task-label";
    label.textContent = `${t.displayLabel} — ${TASK_STATE_LABELS[t.state] || t.state}`;
    const check = document.createElement("span");
    check.className = "check";
    check.textContent = "✓";
    row.append(dot, label, check);
    if (t.hasResult) {
      row.addEventListener("click", () => {
        // Select only -- no fetch, no speaking. #btn-speak (already wired for
        // pause/resume) reads selectedTaskCwd on its own next click.
        selectedTaskCwd = isSelected ? null : t.cwd; // clicking the already-selected row clears the selection, back to "last result"
        taskPicker.classList.remove("open");
        requestAnimationFrame(reportHotRect);
      });
    }
    taskList.appendChild(row);
  }
}

btnTasks.addEventListener("click", async () => {
  const opening = !taskPicker.classList.contains("open");
  taskPicker.classList.toggle("open", opening);
  if (opening) {
    statusCard.classList.remove("open");
    compose.classList.remove("open");
    charPicker.classList.remove("open");
    voicePicker.classList.remove("open");
    document.body.classList.remove("composing");
    await renderTaskPicker();
  }
  requestAnimationFrame(reportHotRect);
});

// Glow only when there's genuinely something worth switching to -- 2+ tracked
// tasks, not just because the button exists. Polled separately from the SSE
// stream since task state isn't part of that payload (it's not the main pet's
// own pose, it's every task's).
setInterval(async () => {
  try {
    const res = await fetch("/tasks", { signal: AbortSignal.timeout(2000) });
    const { tasks: list } = await res.json();
    btnTasks.classList.toggle("has-other", list.length >= 2);
  } catch { /* server not running -- leave the glow as it was */ }
}, 3000);

// Hide/show. Real fix for a real bug: hiding used to hide its own toggle too, with
// no way back. Now the bar+pet hide together, but a separate, always-visible dot
// (#peek) is the only thing that stays on screen while hidden -- click it to return.
const btnHide = document.getElementById("btn-hide");
const peek = document.getElementById("peek");
btnHide.addEventListener("click", () => {
  document.body.classList.add("hidden");
  requestAnimationFrame(reportHotRect); // hidden state has its own hot-zone (just #peek)
});
peek.addEventListener("click", () => {
  document.body.classList.remove("hidden");
  requestAnimationFrame(reportHotRect);
});

// Resize -- real native window resize via pywebview's js_api bridge (only present
// inside the actual floating window, not in a plain browser tab).
// Real bug KK caught: shrinking (or growing) the window changes its real native
// frame, but nothing was telling the click-through layer -- unlike every other
// place that opens/closes something in this file, this never called
// reportHotRect() afterward. The native hot-zone kept the OLD size/position, so a
// button that was visually right there (the "+" to grow back, after shrinking)
// could sit outside the stale hot-zone and silently stop receiving clicks --
// present on screen, but not really clickable, hence "transparent" to a click.
// .then() waits for the actual native resize to finish before re-measuring;
// calling reportHotRect() synchronously right after the call would race it.
function resizeBy(delta) {
  if (window.pywebview?.api?.resize) {
    window.pywebview.api.resize(delta).then(() => requestAnimationFrame(reportHotRect));
  }
}
document.getElementById("btn-grow").addEventListener("click", () => resizeBy(40));
document.getElementById("btn-shrink").addEventListener("click", () => resizeBy(-40));
const compose = document.getElementById("compose");
const composeText = document.getElementById("compose-text");
const btnVoice = document.getElementById("btn-voice");

function openCompose() {
  compose.classList.add("open");
  document.body.classList.add("composing"); // hides the bottom bar while composing -- no reason
  composeText.focus();                      // to show both a speech bubble AND a full button row
  statusCard.classList.remove("open");       // same spot above his head -- compose wins
  charPicker.classList.remove("open");
  voicePicker.classList.remove("open");
  taskPicker.classList.remove("open");
  // Same real click-through bug as the character picker: opening compose grows the
  // clickable area upward to cover the text box, but nothing told the native layer.
  requestAnimationFrame(reportHotRect);
}
// KK's bug report (2026-10-09): switching Spaces away mid-type, then back, leaves
// compose open and showing what he'd typed but accepts no further input -- can't
// type, can't delete. Paired with a native-side fix (k2-pet-floating-window.py's
// windowDidBecomeKey_, same commit) that re-asserts the webview's first-responder
// status when the window regains key status; this is the DOM-layer half, re-running
// the exact same .focus() openCompose() already does, in case the box was open from
// before the switch rather than opened fresh. Neither half was independently
// reproduced (no second real macOS Space available to trigger an actual 3-finger
// swipe here) -- both reasoned from the real, documented NSPanel/WKWebView focus
// quirk, not verified end to end. Please test for real and say if it's not fixed.
window.addEventListener("focus", () => {
  if (compose.classList.contains("open")) composeText.focus();
});
// KK's own simplification (2026-10-09): "when I click back on the box, it should
// continue" -- anchor the fix to the actual click gesture itself, not just the
// window-level focus event, which may not fire distinctly from the click in every
// case. mousedown (fires before the browser's own default focus handling, so it
// can't lose a race with it) re-asserts DOM focus; the native windowDidBecomeKey_
// patch (k2-pet-floating-window.py, same commit) handles the OS-level half that a
// click on the panel triggers regardless of which element inside it was clicked.
composeText.addEventListener("mousedown", () => composeText.focus());
function closeCompose() {
  compose.classList.remove("open");
  document.body.classList.remove("composing");
  gazing = false;
  paint(lastRealMotion);
  render(lastRealState, lastAlertMessage, lastCaption); // re-evaluate whether the status card belongs back
}
document.getElementById("btn-text").addEventListener("click", () => {
  if (compose.classList.contains("open")) closeCompose();
  else openCompose();
});

// Real, simplified gaze tracking (2 directions, not the full 16 -- a real v1, not the
// full range yet): as you type, look toward wherever the cursor actually is in the box.
function updateGaze() {
  if (!composeText.value) { gazing = false; paint(lastRealMotion); return; }
  gazing = true;
  const pos = composeText.selectionStart / Math.max(composeText.value.length, 1);
  petCard.dataset.motion = "gaze";
  petCard.classList.remove("has-strip");
  // Same real limitation as idle-glancing: this reuses gentleman-kk's own legacy
  // look-left/look-right pair, not yet extracted for any other character. Other
  // characters just hold their current pose while typing rather than 404ing.
  if (CHARACTER !== "gentleman-kk") { petImg.src = `${STATE_BASE}/${lastRealMotion}.png`; return; }
  petImg.src = pos < 0.4 ? "/assets/states/look-left.png"
             : pos > 0.6 ? "/assets/states/look-right.png"
             : `/assets/states/${lastRealMotion}.png`;
}
composeText?.addEventListener("input", updateGaze);
composeText?.addEventListener("click", updateGaze);
composeText?.addEventListener("keyup", updateGaze);
// Real fix: KK couldn't find a way to dismiss an empty bubble he'd opened by mistake.
// Clicking away blurs the textarea -- if it's empty at that point, just close it instead
// of leaving an empty bubble stuck on screen with no visible way to remove it.
let sendingInProgress = false;
composeText?.addEventListener("blur", () => {
  // Disabling the textarea mid-send also blurs it -- don't let that be mistaken for
  // "user clicked away from an empty box" and cut the status message short.
  if (sendingInProgress) return;
  if (!composeText.value.trim()) { closeCompose(); return; }
  gazing = false; paint(lastRealMotion);
});
composeText?.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { composeText.value = ""; closeCompose(); }
});

// Real fix: the bubble used to close itself the instant Enter was pressed, before you
// could see whether anything had actually happened. Now it stays open long enough to
// show a status before closing.
function showComposeStatus(msg, ms) {
  composeText.disabled = true;
  composeText.placeholder = msg;
  return new Promise((r) => setTimeout(r, ms)).then(() => { composeText.disabled = false; });
}
// Real, reliable focus -- not text injection. KK's own call after live testing showed
// direct socket delivery into Claude Code doesn't reliably land: instead of fighting an
// internal, thinly-documented protocol, bring the real Claude Code window forward (a
// completely standard macOS operation) so he can paste/type there himself.
function focusClaudeCode() {
  if (window.pywebview?.api?.focus_claude_code) window.pywebview.api.focus_claude_code();
}
composeText?.addEventListener("keydown", async (e) => {
  if (e.key !== "Enter" || e.shiftKey) return;
  e.preventDefault();
  const text = composeText.value.trim();
  if (!text) { closeCompose(); return; }
  composeText.value = "";
  if (isNimba) {
    window.open(`http://127.0.0.1:7788/?focus=text&text=${encodeURIComponent(text)}`, "nimba_main");
    closeCompose();
    return;
  }
  sendingInProgress = true;
  try { await navigator.clipboard.writeText(text); } catch {} // fallback if no mod is loaded
  // Real send path, KK's ask (2026-10-08): Claude Code Mods can call $.prompt.submit,
  // something classic hooks genuinely could not do (see the comment above this
  // function -- that limitation is why this fell back to clipboard+focus before).
  // k2-pet-mod polls /pending-prompt and submits it for real; this can't confirm
  // that happened (the mod runs in a different process), so the clipboard copy stays
  // as a safety net and the status says what's actually guaranteed, not what's hoped.
  let queued = false;
  const sentAt = Date.now();
  try {
    const res = await fetch("/submit-prompt", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    queued = res.ok && (await res.json()).queued;
  } catch {}
  focusClaudeCode();
  // KK's ask (2026-10-09): "how will I know which chat my pet is typing into."
  // Poll for the real delivery confirmation (k2-pet-mod reports its actual project
  // cwd back once it wins the race and submits) for up to 2s -- long enough to
  // outlast the mod's own 700ms poll tick -- before falling back to the generic
  // "sent, unconfirmed" message. Never shows a project name it didn't actually see.
  let deliveredTo = null;
  if (queued) {
    for (let i = 0; i < 8; i++) {
      await new Promise((r) => setTimeout(r, 250));
      try {
        const d = await (await fetch("/last-delivery")).json();
        if (d.delivery && d.delivery.at >= sentAt) {
          deliveredTo = d.delivery.cwd.split("/").filter(Boolean).pop() || d.delivery.cwd;
          break;
        }
      } catch { break; }
    }
  }
  await showComposeStatus(
    deliveredTo ? `Sent to: ${deliveredTo}` :
    queued ? "Sent — Claude Code will run it if the K2 Pet mod is loaded" :
    "Copied — Claude Code is coming forward, paste it in",
    2200,
  );
  sendingInProgress = false;
  closeCompose();
});
// Double-click the character anywhere, any time -- not just during an alert -- to bring
// Claude Code forward. The general "get me back there" gesture KK asked for.
petCard.addEventListener("dblclick", focusClaudeCode);
// The alert bubble itself is also a button: click the actual notification to go see it.
alertBubble.addEventListener("click", focusClaudeCode);
btnVoice.addEventListener("click", () => {
  if (isNimba) window.open("http://127.0.0.1:7788/?focus=voice", "nimba_main");
  // No else branch needed -- the button itself is hidden for the Claude Code instance
  // (see body.is-code #btn-voice in companion.html) until real voice-to-text is wired.
});
