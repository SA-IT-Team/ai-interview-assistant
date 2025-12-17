const wsUrl = (window.__APP_CONFIG__ && window.__APP_CONFIG__.WS_URL) || "ws://localhost:8000/ws/interview";
const apiUrl = (window.__APP_CONFIG__ && window.__APP_CONFIG__.API_URL) || "http://localhost:8000";

// DOM Elements
const uploadScreen = document.getElementById("uploadScreen");
const loadingScreen = document.getElementById("loadingScreen");
const interviewScreen = document.getElementById("interviewScreen");
const fileUploadArea = document.getElementById("fileUploadArea");
const resumeFileInput = document.getElementById("resumeFile");
const uploadError = document.getElementById("uploadError");
const questionText = document.getElementById("questionText");
const transcriptLog = document.getElementById("transcriptLog");
const timerDisplay = document.getElementById("timerDisplay");
const progressDisplay = document.getElementById("progressDisplay");
const progressBar = document.getElementById("progressBar");
const progressPercent = document.getElementById("progressPercent");
const conversationIndicator = document.getElementById("conversationIndicator");
const conversationStatus = document.getElementById("conversationStatus");
const indicatorDot = document.getElementById("indicatorDot");
const audioPlayer = document.getElementById("audioPlayer");

// State
let ws = null;
let resumeContext = null;
let audioContext, mediaStreamSource, analyserNode;
let audioPlaybackContext = null;
let capturing = false;
let vadSilenceMs = 1200;
let vadMinVoiceMs = 600;
let vadMaxTurnMs = 12000;
let lastVoiceTime = 0;
let turnBuffer = [];
let turnBufferStart = null;
let animationFrameId = null;
let audioDataArray = null;
let audioChunks = [];
let interviewStartTime = null;
let timerInterval = null;
let questionCount = 0;
let maxQuestions = 8;

// File upload handlers
fileUploadArea.addEventListener("click", () => resumeFileInput.click());
fileUploadArea.addEventListener("dragover", (e) => {
    e.preventDefault();
    fileUploadArea.classList.add("dragover");
});
fileUploadArea.addEventListener("dragleave", () => {
    fileUploadArea.classList.remove("dragover");
});
fileUploadArea.addEventListener("drop", (e) => {
    e.preventDefault();
    fileUploadArea.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
        resumeFileInput.files = e.dataTransfer.files;
        handleResumeUpload();
    }
});

resumeFileInput.addEventListener("change", handleResumeUpload);

async function handleResumeUpload() {
    if (!resumeFileInput.files || resumeFileInput.files.length === 0) {
        return;
    }

    const file = resumeFileInput.files[0];
    if (file.size > 10 * 1024 * 1024) {
        showError("File size must be less than 10MB");
        return;
    }

    if (!file.name.toLowerCase().endsWith(".pdf")) {
        showError("Please upload a PDF file");
        return;
    }

    // Show loading screen
    uploadScreen.classList.add("hidden");
    loadingScreen.classList.add("active");
    uploadError.classList.add("hidden");

    const form = new FormData();
    form.append("file", file);

    try {
        const res = await fetch(`${apiUrl}/upload-resume`, {
            method: "POST",
            body: form,
        });

        if (!res.ok) {
            const errorText = await res.text();
            throw new Error(errorText || "Upload failed");
        }

        const data = await res.json();
        resumeContext = data.resume_context;

        // Transition to interview screen
        setTimeout(() => {
            loadingScreen.classList.remove("active");
            interviewScreen.classList.add("active");
            
            // Audio will be unlocked when first real audio plays (user interaction already happened via file upload)
            
            startInterview();
        }, 1000);
    } catch (err) {
        showError("Upload failed: " + err.message);
        loadingScreen.classList.remove("active");
        uploadScreen.classList.remove("hidden");
    }
}

function showError(message) {
    uploadError.textContent = message;
    uploadError.classList.remove("hidden");
}

function updateConversationState(state) {
    indicatorDot.className = "indicator-dot " + state;
    const states = {
        ready: { text: "Ready", color: "#888" },
        listening: { text: "Listening...", color: "#10b981" },
        speaking: { text: "Speaking...", color: "#7c3aed" },
        processing: { text: "Processing...", color: "#00d4ff" }
    };
    const stateInfo = states[state] || states.ready;
    conversationStatus.textContent = stateInfo.text;
}

function updateProgress() {
    questionCount++;
    const percent = Math.min((questionCount / maxQuestions) * 100, 100);
    progressBar.style.width = percent + "%";
    progressPercent.textContent = Math.round(percent) + "%";
    progressDisplay.textContent = `Question ${questionCount} of ${maxQuestions}`;
}

function startTimer() {
    interviewStartTime = Date.now();
    timerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - interviewStartTime) / 1000);
        const minutes = Math.floor(elapsed / 60);
        const seconds = elapsed % 60;
        timerDisplay.textContent = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }, 1000);
}

function stopTimer() {
    if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
    }
}

function addTranscriptEntry(speaker, text) {
    const item = document.createElement("div");
    item.className = `transcript-item ${speaker}`;
    item.textContent = `${speaker === "assistant" ? "SAJ" : "You"}: ${text}`;
    transcriptLog.appendChild(item);
    transcriptLog.scrollTop = transcriptLog.scrollHeight;
}

async function startInterview() {
    if (!resumeContext) {
        showError("Resume is required to start interview");
        return;
    }

    try {
        const role = "Software Engineer";
        const level = "Mid";
        const candidateName = resumeContext.name || "Candidate";

        ws = new WebSocket(wsUrl);
        ws.binaryType = "arraybuffer";

        ws.onopen = () => {
            updateConversationState("ready");
            console.log("WebSocket connected");
            ws.send(
                JSON.stringify({
                    type: "start",
                    data: {
                        role,
                        level,
                        candidate_name: candidateName,
                        resume_context: resumeContext,
                    },
                })
            );
            setupMedia();
            startTimer();
        };

        let isReceivingAudio = false;
        let audioTimeoutId = null;

        ws.onmessage = async (event) => {
            if (typeof event.data === "string") {
                const msg = JSON.parse(event.data);
                
                // If we were receiving audio and now get a new message, audio stream is complete
                if (isReceivingAudio && audioChunks.length > 0) {
                    console.log("New message received while receiving audio - playing accumulated audio");
                    playAccumulatedAudio();
                }
                
                // If this is a new question, prepare for new audio (but don't clear yet - audio comes after)
                if (msg.type === "question_text") {
                    // Clear any pending timeout
                    if (audioTimeoutId) {
                        clearTimeout(audioTimeoutId);
                        audioTimeoutId = null;
                    }
                    // Reset state for new audio stream
                    audioChunks = [];
                    isReceivingAudio = false;
                }
                
                handleJson(msg);
            } else {
                // Handle binary audio data
                isReceivingAudio = true;
                const chunk = new Uint8Array(event.data);
                audioChunks.push(chunk);
                const totalSize = audioChunks.reduce((acc, c) => acc + c.length, 0);
                console.log(`Received audio chunk: ${chunk.length} bytes, total chunks: ${audioChunks.length}, total size: ${totalSize} bytes`);
                
                // Clear any existing timeout
                if (audioTimeoutId) {
                    clearTimeout(audioTimeoutId);
                }
                
                // Set timeout to play audio if no more chunks arrive (stream ended)
                // Increased timeout to 1000ms to handle slower streams
                audioTimeoutId = setTimeout(() => {
                    if (audioChunks.length > 0 && isReceivingAudio) {
                        console.log("Audio stream timeout - playing accumulated audio");
                        playAccumulatedAudio();
                    }
                }, 1000); // Wait 1 second after last chunk
            }
        };

        async function playAccumulatedAudio() {
            if (audioChunks.length === 0) {
                console.log("No audio chunks to play");
                return;
            }
            
            const totalSize = audioChunks.reduce((acc, c) => acc + c.length, 0);
            console.log(`Playing audio: ${audioChunks.length} chunks, total size: ${totalSize} bytes`);
            
            // Don't play if audio is too small (likely incomplete)
            if (totalSize < 1000) {
                console.warn("Audio too small, likely incomplete. Waiting for more chunks...");
                return;
            }
            
            // Create blob and try both methods: HTML5 audio and Web Audio API
            const blob = new Blob(audioChunks, { type: "audio/mpeg" });
            const url = URL.createObjectURL(blob);
            
            updateConversationState("speaking");
            
            // Try HTML5 audio first (simpler, works if browser supports MPEG)
            const canPlayMpeg = audioPlayer.canPlayType("audio/mpeg");
            console.log("Browser audio support:", {
                mpeg: canPlayMpeg,
                mp3: audioPlayer.canPlayType("audio/mp3")
            });
            
            if (canPlayMpeg && canPlayMpeg !== "") {
                // Browser supports MPEG, use HTML5 audio
                if (audioPlayer.src && audioPlayer.src.startsWith("blob:")) {
                    const oldUrl = audioPlayer.src;
                    audioPlayer.src = "";
                    URL.revokeObjectURL(oldUrl);
                }
                
                audioPlayer.pause();
                audioPlayer.currentTime = 0;
                audioPlayer.src = url;
                
                audioPlayer.onloadeddata = () => {
                    console.log("Audio loaded via HTML5, playing...");
                    audioPlayer.play().then(() => {
                        console.log("Audio playing successfully via HTML5");
                        audioPlayer.onended = () => {
                            console.log("Audio playback ended");
                            updateConversationState("listening");
                            URL.revokeObjectURL(url);
                            audioChunks = [];
                            isReceivingAudio = false;
                        };
                    }).catch((err) => {
                        console.error("HTML5 audio play failed, trying Web Audio API:", err);
                        playWithWebAudioAPI(blob, url);
                    });
                };
                
                audioPlayer.onerror = (e) => {
                    console.error("HTML5 audio error, trying Web Audio API:", e);
                    playWithWebAudioAPI(blob, url);
                };
                
                audioPlayer.load();
            } else {
                // Browser doesn't support MPEG, use Web Audio API
                console.log("Browser doesn't support MPEG, using Web Audio API");
                playWithWebAudioAPI(blob, url);
            }
            
            if (audioTimeoutId) {
                clearTimeout(audioTimeoutId);
                audioTimeoutId = null;
            }
        }
        
        async function playWithWebAudioAPI(blob, url) {
            try {
                // Create Web Audio API context if needed
                if (!audioPlaybackContext) {
                    audioPlaybackContext = new (window.AudioContext || window.webkitAudioContext)();
                }
                
                // Resume context if suspended (browser autoplay policy)
                if (audioPlaybackContext.state === 'suspended') {
                    await audioPlaybackContext.resume();
                    console.log("Audio context resumed");
                }
                
                // Decode audio data
                console.log("Decoding audio data via Web Audio API...");
                const arrayBuffer = await blob.arrayBuffer();
                const audioBuffer = await audioPlaybackContext.decodeAudioData(arrayBuffer);
                console.log("Audio decoded successfully, duration:", audioBuffer.duration, "seconds");
                
                // Create source and play
                const source = audioPlaybackContext.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(audioPlaybackContext.destination);
                
                source.onended = () => {
                    console.log("Web Audio API playback ended");
                    updateConversationState("listening");
                    URL.revokeObjectURL(url);
                    audioChunks = [];
                    isReceivingAudio = false;
                };
                
                source.start(0);
                console.log("Audio playing successfully via Web Audio API");
            } catch (err) {
                console.error("Web Audio API playback failed:", err);
                console.error("Error details:", {
                    name: err.name,
                    message: err.message,
                    stack: err.stack
                });
                updateConversationState("listening");
                URL.revokeObjectURL(url);
                audioChunks = [];
                isReceivingAudio = false;
            }
        }

        ws.onclose = () => {
            updateConversationState("ready");
            stopTimer();
            stopAudioProcessing();
        };

        ws.onerror = (err) => {
            console.error("WebSocket error", err);
            showError("Connection failed. Please refresh and try again.");
        };
    } catch (error) {
        console.error("Error starting interview:", error);
        showError("Error starting interview: " + error.message);
    }
}

function handleJson(msg) {
    switch (msg.type) {
        case "question_text":
            questionText.textContent = msg.text;
            addTranscriptEntry("assistant", msg.text);
            // Audio will be played when stream completes (handled in onmessage)
            // Start listening after a delay to allow audio to finish
            setTimeout(() => {
                if (audioPlayer.paused || audioPlayer.ended) {
                    updateConversationState("listening");
                    startAudioProcessing();
                } else {
                    // Wait for audio to finish
                    audioPlayer.onended = () => {
                        updateConversationState("listening");
                        startAudioProcessing();
                    };
                }
            }, 1000);
            break;
        case "turn_result":
            addTranscriptEntry("candidate", msg.transcript);
            if (msg.end_interview) {
                updateConversationState("processing");
                stopAudioProcessing();
            } else {
                updateProgress();
            }
            break;
        case "done":
            updateConversationState("ready");
            stopTimer();
            stopAudioProcessing();
            questionText.textContent = "Interview complete. Thank you for your time!";
            break;
        case "summary":
            addTranscriptEntry("assistant", `Summary: ${msg.text}`);
            break;
        case "json_report":
            console.log("Evaluation Report:", msg.data);
            break;
        case "tts_error":
            console.error("TTS Error:", msg.message);
            showError("Audio generation failed: " + msg.message);
            addTranscriptEntry("assistant", `[Audio Error: ${msg.message}]`);
            updateConversationState("listening");
            // Continue interview without audio
            startAudioProcessing();
            break;
        case "error":
            showError(msg.message);
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
        
        analyserNode = audioContext.createAnalyser();
        analyserNode.fftSize = 2048;
        analyserNode.smoothingTimeConstant = 0.8;
        mediaStreamSource.connect(analyserNode);
        
        const bufferLength = analyserNode.frequencyBinCount;
        audioDataArray = new Float32Array(bufferLength);
    } catch (e) {
        showError("Microphone access denied: " + e.message);
        console.error("Media setup error:", e);
    }
}

function processAudio() {
    if (!capturing || !analyserNode) {
        return;
    }
    
    analyserNode.getFloatTimeDomainData(audioDataArray);
    handleAudioData(audioDataArray);
    
    animationFrameId = requestAnimationFrame(processAudio);
}

function handleAudioData(audioData) {
    if (!capturing) return;
    const now = performance.now();
    
    let voiced = false;
    for (let i = 0; i < audioData.length; i++) {
        if (Math.abs(audioData[i]) > 0.02) {
            voiced = true;
            break;
        }
    }
    
    if (voiced) {
        lastVoiceTime = now;
    }
    
    turnBuffer.push(new Float32Array(audioData));

    const elapsed = now - (turnBufferStart || now);
    const silenceElapsed = now - lastVoiceTime;

    if (!turnBufferStart) {
        turnBufferStart = now;
    }

    const voicedDuration = elapsed - silenceElapsed;
    let dynamicSilenceMs = vadSilenceMs;
    let dynamicMaxTurnMs = vadMaxTurnMs;

    if (voicedDuration < 2000) {
        dynamicSilenceMs = 600;
        dynamicMaxTurnMs = 8000;
    } else if (voicedDuration > 6000) {
        dynamicSilenceMs = 1500;
        dynamicMaxTurnMs = 18000;
    }

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
    updateConversationState("listening");
    
    if (!animationFrameId && analyserNode) {
        processAudio();
    }
}

function stopAudioProcessing() {
    capturing = false;
    if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
    }
}

function float32ToWavBase64(buffers, sampleRate = 16000) {
    const length = buffers.reduce((acc, b) => acc + b.length, 0);
    const pcm16 = new Int16Array(length);
    let offset = 0;
    buffers.forEach((b) => {
        for (let i = 0; i < b.length; i++) {
            let s = Math.max(-1, Math.min(1, b[i]));
            pcm16[offset++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
    });
    
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
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, byteRate, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, 16, true);
    writeStr(36, "data");
    view.setUint32(40, pcm16.length * 2, true);
    const wavBytes = new Uint8Array(buffer);
    wavBytes.set(new Uint8Array(pcm16.buffer), 44);
    
    // Convert to base64 in chunks to avoid stack overflow
    // Use a simple loop approach that's safe for large arrays
    const chunkSize = 8192;
    let binaryString = "";
    for (let i = 0; i < wavBytes.length; i += chunkSize) {
        const chunk = wavBytes.slice(i, Math.min(i + chunkSize, wavBytes.length));
        // Build string character by character to avoid stack overflow
        for (let j = 0; j < chunk.length; j++) {
            binaryString += String.fromCharCode(chunk[j]);
        }
    }
    return btoa(binaryString);
}

function finalizeTurn() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (!turnBuffer || turnBuffer.length === 0) return;
    
    updateConversationState("processing");
    const base64Audio = float32ToWavBase64(turnBuffer, 16000);
    ws.send(
        JSON.stringify({
            type: "answer",
            data: { audio_base64: base64Audio, mime_type: "audio/wav" },
        })
    );
}
