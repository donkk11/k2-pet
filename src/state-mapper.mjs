const ITEM_STATES = {
  commandExecution: "executing",
  fileChange: "editing",
  webSearch: "searching",
  mcpToolCall: "tool-use",
  dynamicToolCall: "tool-use",
  enteredReviewMode: "checking",
};

const APPROVAL_METHODS = new Set([
  "item/commandExecution/requestApproval",
  "item/fileChange/requestApproval",
  "item/permissions/requestApproval",
  "mcpServer/elicitation/request",
]);

export class K2StateMapper {
  constructor({ now = () => Date.now(), transientMs = 2200 } = {}) {
    this.now = now;
    this.transientMs = transientMs;
    this.model = {
      turnActive: false,
      activeItems: new Map(),
      pending: new Map(),
      review: false,
      listening: false,
      speaking: false,
      reading: false,
      terminal: null,
      alert: null,
    };
    this.alertMs = 9000;
    // KK's own real ask: the finish celebration was ending too fast to actually see
    // and enjoy (2.2s, shared with problem/interrupted, which SHOULD stay quick --
    // you don't want an error looking like a party). Finished gets its own longer
    // window, dismissible early by clicking (see companion.js), with this as the
    // safety-net expiry if nobody clicks at all.
    this.finishedMs = 12000;
    this.last = this.snapshot("startup");
  }

  ingest(event, source = "app-server") {
    const method = event?.method || event?.type || "unknown";
    const params = event?.params || event;
    const item = params?.item || event?.item;
    const requestId = event?.id ?? params?.requestId ?? method;

    if (method === "pet/alert") {
      // A real Claude Code Notification hook fire -- "Claude needs your attention" while
      // you're looking at something else. Takes priority over everything else below
      // since it's specifically meant to interrupt and be noticed, then expires on its own.
      this.model.alert = { message: params?.message || event?.message || "", until: this.now() + this.alertMs };
    } else if (method === "turn/started" || method === "ollama/request.started" || method === "nimba/generation.started") {
      this.model.turnActive = true;
      this.model.terminal = null;
    } else if (method === "ollama/stream.chunk" || method === "nimba/generation.progress") {
      this.model.turnActive = true;
      this.model.terminal = null;
    } else if (method === "turn/completed" || method === "ollama/response.done" || method === "nimba/generation.completed") {
      this.model.turnActive = false;
      this.model.activeItems.clear();
      const status = params?.turn?.status || params?.status || "completed";
      const terminalState = status === "failed" ? "problem" : status === "interrupted" ? "interrupted" : "finished";
      this.model.terminal = {
        state: terminalState,
        until: this.now() + (terminalState === "finished" ? this.finishedMs : this.transientMs),
      };
    } else if (method === "ollama/request.failed" || method === "nimba/generation.failed") {
      this.model.turnActive = false;
      this.model.activeItems.clear();
      this.model.terminal = { state: "problem", until: this.now() + this.transientMs };
    } else if (method === "item/started" && item) {
      // caption is real data straight from the hook payload (a Bash tool's own
      // description, an Edit's file_path, a WebSearch's query, ...) -- see
      // k2-pet-claude-code-emit.sh. Never fabricated; absent when the hook didn't
      // supply one, rather than filled with a placeholder.
      this.model.activeItems.set(item.id || `${item.type}-${this.now()}`, { type: item.type, caption: item.caption || null });
      if (item.type === "enteredReviewMode") this.model.review = true;
      if (item.type === "exitedReviewMode") this.model.review = false;
    } else if (method === "item/completed" && item) {
      this.model.activeItems.delete(item.id);
      if (item.type === "enteredReviewMode") this.model.review = true;
      if (item.type === "exitedReviewMode") this.model.review = false;
    } else if (APPROVAL_METHODS.has(method)) {
      this.model.pending.set(String(requestId), "permission");
    } else if (method === "item/tool/requestUserInput") {
      this.model.pending.set(String(requestId), "question");
    } else if (method === "serverRequest/resolved") {
      const resolvedId = params?.requestId ?? params?.id ?? event?.id;
      if (resolvedId != null) this.model.pending.delete(String(resolvedId));
      else this.model.pending.clear();
    } else if (method === "input_audio_buffer.speech_started" || method === "nimba/listening.started") {
      this.model.listening = true;
    } else if (method === "input_audio_buffer.speech_stopped" || method === "nimba/listening.stopped") {
      this.model.listening = false;
    } else if (method === "response.output_audio.delta" || method === "nimba/tts.started") {
      this.model.speaking = true;
    } else if (method === "response.output_audio.done" || method === "response.done" || method === "nimba/tts.ended") {
      this.model.speaking = false;
    } else if (method === "pet/reading.start") {
      // KK's own ask (2026-10-08): /speak-last reading a clicked task summary out loud
      // is a DIFFERENT thing from Nimba's realtime voice ("speaking", mapped to the
      // working pose) -- its own state, on purpose, so it can get its own art (the
      // existing gaze/look-around strip, via "waiting" in companion.js's art map)
      // instead of silently reusing Nimba's.
      this.model.reading = true;
    } else if (method === "pet/reading.done") {
      this.model.reading = false;
    } else if ((/error|failed/i.test(method) || event?.error) && params?.willRetry !== true) {
      this.model.terminal = { state: "problem", until: this.now() + this.transientMs };
    }

    this.last = this.snapshot(method, source, event);
    return this.last;
  }

  snapshot(reason = "tick", source = "system", raw = null) {
    const m = this.model;
    let state = "idle";
    if (m.terminal && m.terminal.until <= this.now()) m.terminal = null;
    if (m.alert && m.alert.until <= this.now()) m.alert = null;

    const pending = [...m.pending.values()];
    const activeEntries = [...m.activeItems.values()];
    const activeTypes = activeEntries.map((e) => e.type);
    const activeCaptions = activeEntries.map((e) => e.caption).filter(Boolean);
    if (m.alert) state = "attention";
    else if (m.terminal?.state === "problem") state = "problem";
    else if (pending.includes("permission")) state = "permission";
    else if (pending.includes("question")) state = "question";
    else if (m.listening) state = "listening";
    else if (m.reading) state = "reading";
    else if (m.speaking) state = "speaking";
    else if (m.review || activeTypes.includes("enteredReviewMode")) state = "checking";
    else {
      const mapped = activeTypes.map((type) => ITEM_STATES[type]).filter(Boolean);
      state = mapped.at(-1) || m.terminal?.state || (m.turnActive ? "working" : "idle");
    }

    return {
      state,
      reason,
      source,
      at: new Date(this.now()).toISOString(),
      evidence: raw ? summarize(raw) : null,
      activeItemTypes: activeTypes,
      pending: pending.length,
      alertMessage: m.alert?.message || null,
      caption: activeCaptions.at(-1) || null,
    };
  }
}

function summarize(event) {
  const item = event?.params?.item || event?.item;
  return {
    method: event?.method || event?.type || "unknown",
    itemType: item?.type || null,
    itemId: item?.id || null,
  };
}

export const VERIFIED_STATES = Object.freeze({
  attention: "A real Claude Code Notification hook fired (needs your input) -- transient, expires on its own",
  idle: "No active turn or voice activity",
  working: "turn/started without a more specific active item",
  executing: "commandExecution item active",
  editing: "fileChange item active",
  searching: "webSearch item active",
  "tool-use": "MCP or dynamic tool call active",
  checking: "review mode active",
  permission: "approval request unresolved",
  question: "requestUserInput unresolved",
  finished: "turn/completed with completed status",
  interrupted: "turn/completed with interrupted status",
  problem: "failed turn or non-retryable protocol error",
  listening: "Realtime speech_started until speech_stopped",
  speaking: "Realtime output_audio delta until audio/response done",
  reading: "/speak-last reading a clicked task summary out loud -- distinct from Nimba's realtime 'speaking'",
});
