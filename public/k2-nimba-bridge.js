(() => {
  const endpoint = "http://127.0.0.1:3042/ingest";

  async function emit(type, detail = {}) {
    try {
      await fetch(endpoint, {
        method: "POST",
        mode: "no-cors",
        body: JSON.stringify({ type, source: "nimba", ...detail }),
      });
    } catch (error) {
      console.debug("[K2 Pet] overlay unavailable:", error?.message || error);
    }
  }

  window.K2Pet = Object.freeze({
    emit,
    listening(active) { return emit(active ? "input_audio_buffer.speech_started" : "input_audio_buffer.speech_stopped"); },
    working(active) { return emit(active ? "turn/started" : "turn/completed", active ? {} : { params: { turn: { status: "completed" } } }); },
    speaking(active) { return emit(active ? "response.output_audio.delta" : "response.output_audio.done"); },
    problem(error) { return emit("turn/completed", { params: { turn: { status: "failed" } }, error: String(error?.message || error || "unknown") }); },
  });
})();
