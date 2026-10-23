import test from "node:test";
import assert from "node:assert/strict";
import { K2StateMapper, VERIFIED_STATES } from "../src/state-mapper.mjs";

const event=(method,params={})=>({method,params});
test("every declared state has evidence semantics",()=>assert.equal(Object.keys(VERIFIED_STATES).length,16));
test("reading is its own state, distinct from Nimba's speaking",()=>{
  const m=new K2StateMapper();
  assert.equal(m.ingest(event("pet/reading.start")).state,"reading");
  assert.equal(m.ingest(event("pet/reading.done")).state,"idle");
});
test("attention maps a real pet alert and outranks active work",()=>{
  const m=new K2StateMapper();
  m.ingest(event("turn/started"));
  assert.equal(m.ingest(event("pet/alert",{message:"Claude needs your attention"})).state,"attention");
});
test("maps task lifecycle and item types",()=>{
  const m=new K2StateMapper();
  assert.equal(m.ingest(event("turn/started")).state,"working");
  for(const [type,state] of [["commandExecution","executing"],["fileChange","editing"],["webSearch","searching"],["mcpToolCall","tool-use"]]){
    assert.equal(m.ingest(event("item/started",{item:{id:type,type}})).state,state);
    m.ingest(event("item/completed",{item:{id:type,type}}));
  }
  assert.equal(m.ingest(event("turn/completed",{turn:{status:"completed"}})).state,"finished");
});
test("permission and question outrank active work and resolve",()=>{
  const m=new K2StateMapper();m.ingest(event("turn/started"));
  assert.equal(m.ingest({id:7,method:"item/tool/requestUserInput",params:{}}).state,"question");
  assert.equal(m.ingest(event("serverRequest/resolved",{requestId:7})).state,"working");
  assert.equal(m.ingest({id:8,method:"item/commandExecution/requestApproval",params:{}}).state,"permission");
});
test("voice states are deterministic and listening wins barge-in",()=>{
  const m=new K2StateMapper();
  assert.equal(m.ingest({type:"response.output_audio.delta"},"realtime").state,"speaking");
  assert.equal(m.ingest({type:"input_audio_buffer.speech_started"},"realtime").state,"listening");
  assert.equal(m.ingest({type:"input_audio_buffer.speech_stopped"},"realtime").state,"speaking");
  assert.equal(m.ingest({type:"response.output_audio.done"},"realtime").state,"idle");
});
test("failed and interrupted terminal states",()=>{
  const m=new K2StateMapper();
  assert.equal(m.ingest(event("turn/completed",{turn:{status:"failed"}})).state,"problem");
  assert.equal(new K2StateMapper().ingest(event("turn/completed",{turn:{status:"interrupted"}})).state,"interrupted");
});
test("retryable transport errors remain working",()=>{
  const m=new K2StateMapper();m.ingest(event("turn/started"));
  assert.equal(m.ingest(event("error",{willRetry:true})).state,"working");
  assert.equal(m.ingest(event("error",{willRetry:false})).state,"problem");
});
test("working persists until a real completion event",()=>{
  let time=Date.parse("2026-09-20T00:00:00Z");
  const m=new K2StateMapper({now:()=>time});
  assert.equal(m.ingest(event("turn/started")).state,"working");
  time+=60_000;
  assert.equal(m.snapshot("one-minute-later").state,"working");
  assert.equal(m.ingest(event("turn/completed",{turn:{status:"completed"}})).state,"finished");
});
test("Ollama and Nimba lifecycle aliases drive persistent live states",()=>{
  const m=new K2StateMapper();
  assert.equal(m.ingest({type:"nimba/listening.started"},"nimba").state,"listening");
  assert.equal(m.ingest({type:"nimba/listening.stopped"},"nimba").state,"idle");
  assert.equal(m.ingest({type:"ollama/request.started"},"nimba").state,"working");
  assert.equal(m.ingest({type:"ollama/stream.chunk"},"nimba").state,"working");
  assert.equal(m.ingest({type:"ollama/response.done"},"nimba").state,"finished");
  assert.equal(m.ingest({type:"nimba/tts.started"},"nimba").state,"speaking");
  assert.equal(m.ingest({type:"nimba/tts.ended"},"nimba").state,"finished");
});
test("Nimba failure ends working instead of returning to it",()=>{
  let time=Date.parse("2026-09-20T00:00:00Z");
  const m=new K2StateMapper({now:()=>time,transientMs:2200});
  m.ingest({type:"ollama/request.started"},"nimba");
  assert.equal(m.ingest({type:"nimba/generation.failed",error:"offline"},"nimba").state,"problem");
  time+=3000;
  assert.equal(m.snapshot().state,"idle");
});
