import { spawn } from "node:child_process";
import { createWriteStream, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";
import { K2StateMapper } from "./state-mapper.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export class AppServerRecorder {
  constructor({ onState = () => {}, tracePath, cwd = resolve(ROOT, "evidence/sandbox") } = {}) {
    mkdirSync(resolve(ROOT, "evidence/traces"), { recursive: true });
    mkdirSync(cwd, { recursive: true });
    this.tracePath = tracePath || resolve(ROOT, "evidence/traces", `app-server-${stamp()}.jsonl`);
    this.trace = createWriteStream(this.tracePath, { flags: "a" });
    this.cwd = cwd;
    this.mapper = new K2StateMapper();
    this.onState = onState;
    this.pending = new Map();
    this.nextId = 1;
  }

  async start() {
    const env = { ...process.env };
    if (!env.SSL_CERT_FILE && existsSync("/etc/ssl/cert.pem")) env.SSL_CERT_FILE = "/etc/ssl/cert.pem";
    this.child = spawn("codex", ["app-server", "--listen", "stdio://"], {
      cwd: this.cwd,
      stdio: ["pipe", "pipe", "pipe"],
      env,
    });
    this.child.stderr.on("data", (chunk) => this.writeTrace("stderr", { text: chunk.toString() }));
    readline.createInterface({ input: this.child.stdout }).on("line", (line) => this.handleLine(line));
    await this.request("initialize", { clientInfo: { name: "k2-state-recorder", title: "K2 State Recorder", version: "0.1.0" } });
    this.notify("initialized", {});
    return this;
  }

  request(method, params = {}) {
    const id = this.nextId++;
    this.send({ method, id, params });
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject, method }));
  }

  notify(method, params = {}) { this.send({ method, params }); }

  send(message) {
    this.writeTrace("client", message);
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
  }

  handleLine(line) {
    let message;
    try { message = JSON.parse(line); }
    catch { this.writeTrace("stdout-unparsed", { text: line }); return; }
    this.writeTrace("server", message);
    if (message.id != null && (message.result !== undefined || message.error)) {
      const pending = this.pending.get(message.id);
      if (pending) {
        this.pending.delete(message.id);
        message.error ? pending.reject(new Error(JSON.stringify(message.error))) : pending.resolve(message.result);
      }
      return;
    }
    if (message.method) this.onState(this.mapper.ingest(message), message);
  }

  writeTrace(direction, payload) {
    this.trace.write(`${JSON.stringify({ capturedAt: new Date().toISOString(), direction, payload })}\n`);
  }

  async runPrompt(prompt = "Reply with exactly K2_RECORDER_READY. Do not use tools.") {
    const started = await this.request("thread/start", {
      cwd: this.cwd,
      approvalPolicy: "never",
      sandbox: "workspace-write",
    });
    const threadId = started?.thread?.id;
    if (!threadId) throw new Error("thread/start did not return thread.id");
    const turn = await this.request("turn/start", {
      threadId,
      input: [{ type: "text", text: prompt }],
    });
    return { threadId, turnId: turn?.turn?.id, tracePath: this.tracePath };
  }

  close() {
    this.child?.kill("SIGTERM");
    this.trace.end();
  }
}

function stamp() { return new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-"); }

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const recorder = new AppServerRecorder({ onState: (state) => console.log(JSON.stringify(state)) });
  const timeout = setTimeout(() => { recorder.close(); process.exitCode = 1; }, 120000);
  try {
    await recorder.start();
    const run = await recorder.runPrompt(process.argv.slice(2).join(" ") || undefined);
    console.error(`K2 trace: ${run.tracePath}`);
    await new Promise((resolve) => {
      const poll = setInterval(() => {
        if (["finished", "problem", "interrupted"].includes(recorder.mapper.last.state)) {
          clearInterval(poll); resolve();
        }
      }, 100);
    });
  } finally {
    clearTimeout(timeout);
    recorder.close();
  }
}
