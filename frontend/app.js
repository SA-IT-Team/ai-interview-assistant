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
const speakIndicator = document.getElementById("speak-indicator");

let ws = null;
let mediaRecorder = null;
let audioChunks = [];
let resumeContext = null;
let audioContext, mediaStreamSource, processorNode;
let capturing = false;
let vadSilenceMs = 1200;
let vadMinVoiceMs = 600;
let vadMaxTurnMs = 12000;
let lastVoiceTime = 0;
let turnBuffer = [];
let turnBufferStart = null;
let firstSpeechDetected = false;
let expectedResponseLength = "medium";
let audioEndHandlerSet = false;

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
      const chunk = new Uint8Array(event.data);
      audioChunks.push(chunk);
      const blob = new Blob(audioChunks, { type: "audio/mpeg" });
      audioPlayer.src = URL.createObjectURL(blob);
      
      if (!audioEndHandlerSet) {
        audioEndHandlerSet = true;
        audioPlayer.onended = () => {
          setTimeout(() => {
            startAudioProcessing();
            audioEndHandlerSet = false;
          }, 500);
        };
      }
      
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
    case "question_text":
      questionEl.textContent = msg.text;
      questionStatus.textContent = "Listening...";
      audioChunks = [];
      expectedResponseLength = msg.expected_length || "medium";
      audioEndHandlerSet = false;
      break;
    case "turn_result":
      logTranscript(`You: ${msg.transcript}`);
      logScore(
        `Score: ${msg.score} | Rationale: ${msg.rationale} | Flags: ${msg.red_flags?.join(", ") || "None"}`
      );
      if (msg.end_interview) {
        questionStatus.textContent = "Interview complete";
        answerBtn.disabled = true;
      }
      break;
    case "done":
      questionStatus.textContent = "Interview complete";
      stopAudioProcessing();
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
  
  let voiced = false;
  for (let i = 0; i < input.length; i++) {
    if (Math.abs(input[i]) > 0.04) {
      voiced = true;
      break;
    }
  }
  
  if (voiced) {
    lastVoiceTime = now;
    if (!firstSpeechDetected) {
      firstSpeechDetected = true;
      turnBufferStart = now;
    }
  }
  
  turnBuffer.push(new Float32Array(input));

  const elapsed = now - (turnBufferStart || now);
  const silenceElapsed = now - lastVoiceTime;

  if (!turnBufferStart) {
    turnBufferStart = now;
  }

  const voicedDuration = elapsed - silenceElapsed;
  let dynamicSilenceMs = vadSilenceMs;
  let dynamicMaxTurnMs = vadMaxTurnMs;

  if (expectedResponseLength === "short") {
    if (voicedDuration < 1000) {
      dynamicSilenceMs = 800;
      dynamicMaxTurnMs = 5000;
    } else if (voicedDuration < 3000) {
      dynamicSilenceMs = 1000;
      dynamicMaxTurnMs = 8000;
    } else {
      dynamicSilenceMs = 1200;
      dynamicMaxTurnMs = 10000;
    }
  } else if (expectedResponseLength === "long") {
    if (voicedDuration < 5000) {
      dynamicSilenceMs = 1500;
      dynamicMaxTurnMs = 15000;
    } else {
      dynamicSilenceMs = 2000;
      dynamicMaxTurnMs = 25000;
    }
  } else {
    if (voicedDuration < 1000) {
      dynamicSilenceMs = 800;
      dynamicMaxTurnMs = 8000;
    } else if (voicedDuration < 2000) {
      dynamicSilenceMs = 1000;
      dynamicMaxTurnMs = 10000;
    } else if (voicedDuration > 6000) {
      dynamicSilenceMs = 1500;
      dynamicMaxTurnMs = 18000;
    }
  }

  if (lastVoiceTime === 0) {
    lastVoiceTime = now;
  }
  
  if (firstSpeechDetected && ((silenceElapsed > dynamicSilenceMs && elapsed > vadMinVoiceMs) || elapsed > dynamicMaxTurnMs)) {
    finalizeTurn();
    turnBuffer = [];
    turnBufferStart = null;
    lastVoiceTime = 0;
    firstSpeechDetected = false;
  }
}

function startAudioProcessing() {
  capturing = true;
  turnBuffer = [];
  turnBufferStart = null;
  lastVoiceTime = 0;
  firstSpeechDetected = false;
  statusText.textContent = "Recording...";
  speakIndicator.classList.remove("hidden");
}

function stopAudioProcessing() {
  capturing = false;
  statusText.textContent = "Idle";
  speakIndicator.classList.add("hidden");
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
  speakIndicator.classList.add("hidden");
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