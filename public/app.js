const ui={card:document.querySelector("#card"),pet:document.querySelector("#pet"),petSprite:document.querySelector("#pet-sprite"),state:document.querySelector("#state"),meaning:document.querySelector("#meaning"),source:document.querySelector("#source"),evidence:document.querySelector("#evidence"),voiceSensor:document.querySelector("#voice-sensor"),stateGrid:document.querySelector("#state-grid"),moveName:document.querySelector("#move-name"),moveDescription:document.querySelector("#move-description"),playAll:document.querySelector("#play-all"),liveEvents:document.querySelector("#live-events")};
const copy={idle:"Ready for what’s next",working:"Thinking and creating",executing:"Running a command",editing:"Changing files",searching:"Searching for evidence","tool-use":"Using a connected tool",checking:"Checking the details",permission:"Your approval is needed",question:"Your input is needed",finished:"We did it",interrupted:"Work was interrupted",problem:"Something needs attention",listening:"I’m listening",speaking:"Sharing the answer"};
const art={idle:"idle",working:"working",executing:"working",editing:"working",searching:"checking","tool-use":"working",checking:"checking",permission:"waiting",question:"waiting",finished:"idle",interrupted:"waiting",problem:"problem",listening:"waiting",speaking:"working"};
const moves={
  idle:"Slow breathing with a relaxed body float.",
  working:"Steady focused bob: active thought without directional travel.",
  executing:"A quick down-up command beat: decisive action in progress.",
  editing:"Precise left-right micro-shifts: making controlled changes.",
  searching:"A broad, slow scan from side to side.",
  "tool-use":"A reach-and-return rhythm: using an external capability.",
  checking:"Lean forward, hold, then scan: close inspection.",
  permission:"Step toward you and hold: approval is required.",
  question:"Alternating head tilt: waiting for your answer.",
  finished:"One clean victory jump followed by a grounded landing.",
  interrupted:"Abrupt stop, short recoil, then a frozen pause.",
  problem:"Body drop with a restrained shake, then recovery.",
  listening:"Lean in with an attentive two-sided pulse.",
  speaking:"A rhythmic delivery bob that reads like active speech."
};
const generatedStrips=new Set(["working","checking","listening","speaking"]);
let previewMode=false,tourTimer=null,lastLive={state:"idle",reason:"startup",source:"system"};

for(const state of Object.keys(moves)){
  const button=document.createElement("button");
  button.type="button";button.className="state-button";button.dataset.state=state;button.textContent=state.toUpperCase();button.setAttribute("aria-pressed",String(state==="idle"));
  button.addEventListener("click",()=>preview(state));
  ui.stateGrid.append(button);
}

const eventStream=new EventSource("/events");
eventStream.onmessage=({data})=>{lastLive=JSON.parse(data);if(!previewMode)render(lastLive);};
eventStream.onerror=()=>{if(!previewMode&&!voiceSensor){ui.source.textContent="LOCAL MODE";ui.evidence.textContent="server-disconnected";}};
ui.liveEvents.addEventListener("click",()=>{stopTour();previewMode=false;render(lastLive);ui.evidence.textContent="live-events";});
ui.playAll.addEventListener("click",()=>{if(tourTimer){stopTour();return;}previewMode=true;let index=0;const states=Object.keys(moves);ui.playAll.textContent="STOP TOUR";preview(states[index]);tourTimer=setInterval(()=>preview(states[++index%states.length]),2400);});

function preview(state){previewMode=true;render({state,reason:"motion-preview",source:"preview"});}
function stopTour(){if(tourTimer)clearInterval(tourTimer);tourTimer=null;ui.playAll.textContent="PLAY ALL";}
function render(s){
  const state=moves[s.state]?s.state:"idle";
  ui.card.classList.add("change");setTimeout(()=>ui.card.classList.remove("change"),180);
  ui.card.dataset.motion=state;ui.card.classList.toggle("has-strip",generatedStrips.has(state));ui.state.textContent=state.toUpperCase();ui.meaning.textContent=copy[state]||s.reason;
  ui.source.textContent=(s.source||"system").toUpperCase();ui.evidence.textContent=s.evidence?.method||s.reason;
  ui.pet.src=`/assets/states/${art[state]||"idle"}.png`;ui.moveName.textContent=state.toUpperCase();ui.moveDescription.textContent=moves[state];
  document.querySelectorAll(".state-button").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.state===state)));
}

let voiceSensor=null;
ui.voiceSensor.addEventListener("click",async()=>{
  if(voiceSensor){voiceSensor.stop();voiceSensor=null;setVoiceButton(false);showLocalVoice(false);await ingest("input_audio_buffer.speech_stopped");return;}
  try{
    voiceSensor=await startVoiceSensor((speaking)=>{
      showLocalVoice(speaking);
      ingest(speaking?"input_audio_buffer.speech_started":"input_audio_buffer.speech_stopped");
    });
    setVoiceButton(true);
  }catch(error){ui.meaning.textContent="Microphone permission is required";ui.evidence.textContent=error.name||"microphone-error";}
});

function setVoiceButton(active){ui.voiceSensor.setAttribute("aria-pressed",String(active));ui.voiceSensor.lastChild.textContent=active?"VOICE SENSING LIVE":"ENABLE VOICE SENSING";}
function showLocalVoice(active){
  if(previewMode)return;
  const type=active?"input_audio_buffer.speech_started":"input_audio_buffer.speech_stopped";
  const state=active?"listening":"idle";
  lastLive={state,reason:type,source:"local-mic",evidence:{method:type}};
  render(lastLive);
}
async function ingest(type){
  try{
    const response=await fetch("/ingest",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({type,source:"local-mic"})});
    return response.ok;
  }catch{
    ui.source.textContent="LOCAL MIC";
    ui.evidence.textContent=`${type} · local-only`;
    return false;
  }
}

async function startVoiceSensor(onChange){
  const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
  const context=new AudioContext();
  const analyser=context.createAnalyser();
  analyser.fftSize=1024;
  analyser.smoothingTimeConstant=.55;
  context.createMediaStreamSource(stream).connect(analyser);
  const samples=new Float32Array(analyser.fftSize);
  let baseline=.008,active=false,attack=0,release=0,frame=0;
  const tick=()=>{
    analyser.getFloatTimeDomainData(samples);
    let sum=0;
    for(const value of samples)sum+=value*value;
    const rms=Math.sqrt(sum/samples.length);
    if(!active)baseline=baseline*.985+rms*.015;
    const heard=rms>Math.max(.018,baseline*2.8);
    attack=heard?attack+1:0;
    release=heard?0:release+1;
    if(!active&&attack>=3){active=true;onChange(true);}
    if(active&&release>=14){active=false;onChange(false);}
    frame=requestAnimationFrame(tick);
  };
  tick();
  return{stop(){cancelAnimationFrame(frame);if(active)onChange(false);stream.getTracks().forEach(track=>track.stop());context.close();}};
}
