#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { mkdirSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
// Keep the independently generated browser proof intact. An optional argument overrides the output.
const outputPath = process.argv[2]
  ? resolve(process.argv[2])
  : resolve(projectRoot, "evidence/voicelink-proof/k2-pet-narration-cli.wav");
const modelId = "onnx-community/Kokoro-82M-v1.0-ONNX";
const narration =
  "Meet K2, a small companion that stays close while your work gets done. It turns the rhythm of a coding session into a calm, expressive presence, so every task feels a little more alive.";

async function loadKokoro() {
  try {
    return await import("kokoro-js");
  } catch (error) {
    console.log("kokoro-js is not installed locally; installing it with npm...");
    execFileSync("npm", ["install", "--no-save", "kokoro-js"], {
      cwd: projectRoot,
      stdio: "inherit",
    });
    return await import("kokoro-js");
  }
}

const { KokoroTTS } = await loadKokoro();
mkdirSync(dirname(outputPath), { recursive: true });

console.log(`Loading ${modelId} with KokoroTTS on cpu (q8)...`);
const tts = await KokoroTTS.from_pretrained(modelId, {
  dtype: "q8",
  device: "cpu",
});

console.log("Generating narration with voice am_adam at speed 1.1...");
const audio = await tts.generate(narration, {
  voice: "am_adam",
  speed: 1.1,
});
// RawAudio.save() is asynchronous: wait before checking or reporting the file.
await audio.save(outputPath);

const { size } = statSync(outputPath);
console.log(`Wrote ${outputPath} (${size} bytes)`);
