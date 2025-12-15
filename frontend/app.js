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

// Adaptive silence detection config
const SILENCE_THRESHOLD_MS = 5000; // 5 seconds of silence = end of answer
const MIN_SPEECH_BEFORE_SILENCE = 500; // At least 500ms of speech before we consider silence
const VOICE_DETECTION_THRESHOLD = 0.02; // Audio amplitude threshold for voice detection

let lastVoiceTime = 0;
let turnBuffer = [];
let turnBufferStart = null;
let hasSpoken = false; // Track if candidate has started speaking
let totalVoicedTime = 0; // Track total time candidate has spoken
let silenceTimer = null; // Timer for silence detection UI feedback
let audioStreamComplete = false;
let audioFallbackTimer = null; // Fallback timer to ensure audio processing starts

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
  console.log("[AudioStateMachine] Received message:", msg.type, msg);
  
  switch (msg.type) {
    case "question_text":
      console.log("[AudioStateMachine] question_text received, stopping audio processing");
      questionEl.textContent = msg.text;
      questionStatus.textContent = "Listening...";
      audioChunks = [];
      audioStreamComplete = false;
      audioPlayer.onended = null;
      audioPlayer.onplaying = null;
      audioPlayer.oncanplaythrough = null;
      clearAudioFallbackTimer();
      stopAudioProcessing();
      break;
    case "audio_complete":
      console.log("[AudioStateMachine] audio_complete received, audioPlayer.ended:", audioPlayer.ended, "paused:", audioPlayer.paused);
      audioStreamComplete = true;
      
      // Clear any existing fallback timer
      clearAudioFallbackTimer();
      
      // Set up multiple event handlers for reliability
      audioPlayer.onended = () => {
        console.log("[AudioStateMachine] audioPlayer.onended fired");
        audioPlayer.onended = null;
        audioPlayer.onplaying = null;
        clearAudioFallbackTimer();
        setTimeout(() => {
          console.log("[AudioStateMachine] Starting audio processing after onended");
          startAudioProcessing();
        }, 500);
      };
      
      // Use canplaythrough to track when audio is ready
      audioPlayer.oncanplaythrough = () => {
        console.log("[AudioStateMachine] audioPlayer.oncanplaythrough fired, duration:", audioPlayer.duration);
      };
      
      // Use playing event to know audio started
      audioPlayer.onplaying = () => {
        console.log("[AudioStateMachine] audioPlayer.onplaying fired");
        // Set fallback timer based on expected duration + buffer
        const fallbackDelay = Math.max((audioPlayer.duration || 10) * 1000 + 2000, 5000);
        console.log("[AudioStateMachine] Setting fallback timer for", fallbackDelay, "ms");
        clearAudioFallbackTimer();
        audioFallbackTimer = setTimeout(() => {
          console.log("[AudioStateMachine] Fallback timer fired - forcing startAudioProcessing");
          if (audioStreamComplete && !capturing) {
            audioPlayer.onended = null;
            audioPlayer.onplaying = null;
            startAudioProcessing();
          }
        }, fallbackDelay);
      };
      
      // Check if audio already ended (race condition)
      if (audioPlayer.ended) {
        console.log("[AudioStateMachine] audioPlayer already ended, starting processing");
        setTimeout(() => {
          startAudioProcessing();
        }, 500);
      } else if (audioPlayer.paused && audioChunks.length > 0) {
        // Audio might have failed to play - set a shorter fallback
        console.log("[AudioStateMachine] Audio paused but chunks exist, setting short fallback");
        audioFallbackTimer = setTimeout(() => {
          console.log("[AudioStateMachine] Short fallback timer fired");
          if (audioStreamComplete && !capturing) {
            startAudioProcessing();
          }
        }, 3000);
      }
      break;
    case "processing":
      statusText.textContent = "Generating next question...";
      logTranscript(`You: ${msg.transcript}`);
      break;
    case "turn_result":
      logScore(
        `Score: ${msg.score} | Rationale: ${msg.rationale} | Flags: ${msg.red_flags?.join(", ") || "None"}`
      );
      if (msg.end_interview) {
        questionStatus.textContent = "Interview complete";
      }
      break;
    case "done":
      questionStatus.textContent = "Interview complete";
      clearAudioFallbackTimer();
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

function clearAudioFallbackTimer() {
  if (audioFallbackTimer) {
    console.log("[AudioStateMachine] Clearing fallback timer");
    clearTimeout(audioFallbackTimer);
    audioFallbackTimer = null;
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
  
  // Detect if there's voice activity based on amplitude
  let voiced = false;
  let maxAmplitude = 0;
  for (let i = 0; i < input.length; i++) {
    const amplitude = Math.abs(input[i]);
    if (amplitude > maxAmplitude) maxAmplitude = amplitude;
    if (amplitude > VOICE_DETECTION_THRESHOLD) {
      voiced = true;
    }
  }
  
  // Always add audio to buffer while capturing
  turnBuffer.push(new Float32Array(input));
  
  if (!turnBufferStart) {
    turnBufferStart = now;
  }
  
  if (voiced) {
    // Candidate is speaking
    lastVoiceTime = now;
    if (!hasSpoken) {
      hasSpoken = true;
      statusText.textContent = "Recording... (speak your answer)";
    }
    totalVoicedTime += (input.length / 16000) * 1000; // Add duration of this buffer
    
    // Update UI to show active speech
    statusText.textContent = `Recording... (${Math.floor(totalVoicedTime / 1000)}s spoken)`;
  }
  
  // Calculate how long since last voice activity
  const silenceDuration = now - lastVoiceTime;
  
  // Only check for silence timeout if candidate has spoken enough
  if (hasSpoken && totalVoicedTime >= MIN_SPEECH_BEFORE_SILENCE) {
    if (silenceDuration > 0 && silenceDuration < SILENCE_THRESHOLD_MS) {
      // Show countdown in status
      const remainingSilence = Math.ceil((SILENCE_THRESHOLD_MS - silenceDuration) / 1000);
      statusText.textContent = `Recording... (${remainingSilence}s silence remaining)`;
    }
    
    // If silence exceeds threshold, finalize the answer
    if (silenceDuration >= SILENCE_THRESHOLD_MS) {
      console.log(`Adaptive silence detection: ${silenceDuration}ms silence after ${totalVoicedTime}ms of speech. Finalizing turn.`);
      finalizeTurn();
      resetTurnState();
    }
  }
}

function resetTurnState() {
  turnBuffer = [];
  turnBufferStart = null;
  lastVoiceTime = 0;
  hasSpoken = false;
  totalVoicedTime = 0;
  if (silenceTimer) {
    clearTimeout(silenceTimer);
    silenceTimer = null;
  }
}

function startAudioProcessing() {
  capturing = true;
  resetTurnState();
  lastVoiceTime = performance.now(); // Initialize to current time
  statusText.textContent = "Recording... (waiting for you to speak)";
  speakIndicator.classList.remove("hidden");
}

function stopAudioProcessing() {
  capturing = false;
  resetTurnState();
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