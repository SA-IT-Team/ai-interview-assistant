const wsUrl = (window.__APP_CONFIG__ && window.__APP_CONFIG__.WS_URL) || "ws://localhost:8000/ws/interview";
const apiUrl = (window.__APP_CONFIG__ && window.__APP_CONFIG__.API_URL) || "http://localhost:8000";

const startBtn = document.getElementById("start-btn");
const questionEl = document.getElementById("question-text");
const transcriptLog = document.getElementById("transcript-log");
const scoreLog = document.getElementById("score-log");
const connectionStatus = document.getElementById("connection-status");
const questionStatus = document.getElementById("question-status");
const audioPlayer = document.getElementById("audio-player");
const statusText = document.getElementById("status-text");
const resumeInput = document.getElementById("resume-file");
const uploadBtn = document.getElementById("upload-btn");
const summaryEl = document.getElementById("summary");
const jsonEl = document.getElementById("json-output");

let ws = null;
let mediaRecorder = null;
let audioChunks = [];
let resumeContext = null;
let audioContext, mediaStreamSource, processorNode;
let capturing = false;
let vadSilenceMs = 1200; // base silence window
let vadMinVoiceMs = 600; // min voiced audio to accept a turn
let vadMaxTurnMs = 12000; // cap a turn (will adjust based on speech)
let lastVoiceTime = 0;
let turnBuffer = [];
let turnBufferStart = null;

function logTranscript(text) {
  const div = document.createElement("div");
  div.textContent = text;
  transcriptLog.prepend(div);
}

function logScore(text) {
  const div = document.createElement("div");
  div.textContent = text;
  scoreLog.prepend(div);
}

async function startInterview() {
  const role = document.getElementById("role").value || "Backend Engineer";
  const level = document.getElementById("level").value || "Mid";
  const candidate = document.getElementById("candidate").value || "Candidate";

  ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    connectionStatus.textContent = "Connected";
    ws.send(
      JSON.stringify({
        type: "start",
        data: {
          role,
          level,
          candidate_name: candidate,
          resume_context: resumeContext,
          initial_question: "I will ask questions about your profile. Shall we start?",
        },
      })
    );
    setupMedia();
    questionStatus.textContent = "Waiting for question...";
    statusText.textContent = "Ready";
  };

  ws.onmessage = async (event) => {
    if (typeof event.data === "string") {
      const msg = JSON.parse(event.data);
      handleJson(msg);
    } else {
      // Binary audio chunk; append and update player
      const chunk = new Uint8Array(event.data);
      audioChunks.push(chunk);
      const blob = new Blob(audioChunks, { type: "audio/mpeg" });
      audioPlayer.src = URL.createObjectURL(blob);
      audioPlayer.play().catch(() => {});
    }
  };

  ws.onclose = () => {
    connectionStatus.textContent = "Disconnected";
    stopAudioProcessing();
  };

  ws.onerror = (err) => {
    console.error("WS error", err);
  };
}

function handleJson(msg) {
  switch (msg.type) {
    case "resume_summary":
      // Display resume summary before interview starts
      const summaryDiv = document.createElement("div");
      summaryDiv.className = "resume-summary";
      summaryDiv.style.cssText = "background: #f0f0f0; padding: 12px; margin: 12px 0; border-radius: 4px; font-style: italic;";
      summaryDiv.textContent = msg.text;
      questionEl.parentElement.insertBefore(summaryDiv, questionEl);
      break;
    case "question_text":
      questionEl.textContent = msg.text;
      questionStatus.textContent = "Listening...";
      audioChunks = []; // reset for new playback
      // Small delay to let TTS finish before starting capture
      setTimeout(() => {
        startAudioProcessing();
      }, 500);
      break;
    case "turn_result":
      logTranscript(`You: ${msg.transcript}`);
      logScore(
        `Score: ${msg.score} | Rationale: ${msg.rationale} | Flags: ${msg.red_flags?.join(", ") || "None"}`
      );
      if (msg.end_interview) {
        questionStatus.textContent = "Interview complete";
        stopAudioProcessing();
      }
      break;
    case "done":
      questionStatus.textContent = "Interview complete";
      stopAudioProcessing();
      break;
    case "summary":
      summaryEl.textContent = msg.text || "";
      break;
    case "json_report":
      jsonEl.textContent = JSON.stringify(msg.data, null, 2);
      break;
    case "error":
      logTranscript(`Error: ${msg.message}`);
      break;
    default:
      console.warn("Unknown message", msg);
  }
}

async function setupMedia() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioContext = new AudioContext({ sampleRate: 16000 });
    mediaStreamSource = audioContext.createMediaStreamSource(stream);
    processorNode = audioContext.createScriptProcessor(2048, 1, 1);
    processorNode.onaudioprocess = handleAudio;
    mediaStreamSource.connect(processorNode);
    processorNode.connect(audioContext.destination);
  } catch (e) {
    alert("Mic access denied");
  }
}

function handleAudio(event) {
  if (!capturing) return;
  const input = event.inputBuffer.getChannelData(0);
  const now = performance.now();
  // Simple energy VAD with adaptive thresholds
  let voiced = false;
  for (let i = 0; i < input.length; i++) {
    if (Math.abs(input[i]) > 0.02) { // energy threshold
      voiced = true;
      break;
    }
  }
  if (voiced) {
    lastVoiceTime = now;
  }
  turnBuffer.push(new Float32Array(input));

  const elapsed = now - (turnBufferStart || now);
  const silenceElapsed = now - lastVoiceTime;

  if (!turnBufferStart) {
    turnBufferStart = now;
  }

  // Adaptive timing based on voiced duration
  const voicedDuration = elapsed - silenceElapsed;
  let dynamicSilenceMs = vadSilenceMs;
  let dynamicMaxTurnMs = vadMaxTurnMs;

  if (voicedDuration < 2000) {
    dynamicSilenceMs = 600; // still move on fairly fast after short replies
    dynamicMaxTurnMs = 8000;
  } else if (voicedDuration > 6000) {
    dynamicSilenceMs = 1500; // give more room for long answers
    dynamicMaxTurnMs = 18000; // allow up to ~18s before force-stop
  }

  // Stop conditions: sustained silence or max turn length
  if (lastVoiceTime === 0) {
    lastVoiceTime = now;
  }
  if ((silenceElapsed > dynamicSilenceMs && elapsed > vadMinVoiceMs) || elapsed > dynamicMaxTurnMs) {
    finalizeTurn();
    turnBuffer = [];
    turnBufferStart = null;
    lastVoiceTime = 0;
  }
}

function startAudioProcessing() {
  capturing = true;
  turnBuffer = [];
  turnBufferStart = null;
  lastVoiceTime = 0;
  statusText.textContent = "Recording...";
}

function stopAudioProcessing() {
  capturing = false;
  statusText.textContent = "Idle";
}

function float32ToWavBase64(buffers, sampleRate = 16000) {
  // Concatenate
  const length = buffers.reduce((acc, b) => acc + b.length, 0);
  const pcm16 = new Int16Array(length);
  let offset = 0;
  buffers.forEach((b) => {
    for (let i = 0; i < b.length; i++) {
      let s = Math.max(-1, Math.min(1, b[i]));
      pcm16[offset++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
  });
  // WAV header
  const byteRate = sampleRate * 2;
  const blockAlign = 2;
  const buffer = new ArrayBuffer(44 + pcm16.length * 2);
  const view = new DataView(buffer);
  function writeStr(offset, str) {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  }
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + pcm16.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true); // PCM chunk size
  view.setUint16(20, 1, true); // PCM format
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true); // bits
  writeStr(36, "data");
  view.setUint32(40, pcm16.length * 2, true);
  const wavBytes = new Uint8Array(buffer);
  wavBytes.set(new Uint8Array(pcm16.buffer), 44);
  return btoa(String.fromCharCode.apply(null, wavBytes));
}

function finalizeTurn() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (!turnBuffer || turnBuffer.length === 0) return;
  statusText.textContent = "Processing answer...";
  const base64Audio = float32ToWavBase64(turnBuffer, 16000);
  ws.send(
    JSON.stringify({
      type: "answer",
      data: { audio_base64: base64Audio, mime_type: "audio/wav" },
    })
  );
}

startBtn.onclick = () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    return;
  }
  startInterview();
};

uploadBtn.onclick = async () => {
  if (!resumeInput.files || resumeInput.files.length === 0) {
    alert("Please choose a PDF resume to upload.");
    return;
  }
  const file = resumeInput.files[0];
  const form = new FormData();
  form.append("file", file);
  uploadBtn.disabled = true;
  uploadBtn.textContent = "Uploading...";
  try {
    const res = await fetch(`${apiUrl}/upload-resume`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      throw new Error(await res.text());
    }
    const data = await res.json();
    resumeContext = data.resume_context;
    summaryEl.textContent = resumeContext?.summary || "Resume parsed.";
    questionStatus.textContent = "Resume loaded. Ready to start.";
  } catch (err) {
    alert("Upload failed: " + err);
  } finally {
    uploadBtn.disabled = false;
    uploadBtn.textContent = "Upload Resume";
  }
};

