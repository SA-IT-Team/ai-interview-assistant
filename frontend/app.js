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
let vadMaxTurnMs = 30000; // Increased from 12000 to 30000 (30 seconds) for longer answers
let lastVoiceTime = 0;
let turnBuffer = [];
let turnBufferStart = null;
let animationFrameId = null;
let audioDataArray = null;
let audioChunks = [];
let interviewStartTime = null;
let timerInterval = null;
let isReadyToAnswer = false;
let countdownInterval = null;
let pendingReadyToListen = false;
let isAudioPlaying = false;
let isSendingAnswer = false; // Prevent multiple simultaneous sends

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
    
    // Update loading message with progress updates
    const loadingSubtext = document.querySelector("#loadingScreen .loading-subtext");
    let progressStep = 0;
    const progressMessages = [
        "Uploading file...",
        "Extracting text from PDF...",
        "Analyzing with AI...",
        "Finalizing..."
    ];
    
    // Update progress message every 20 seconds
    const progressInterval = setInterval(() => {
        if (progressStep < progressMessages.length - 1) {
            progressStep++;
            if (loadingSubtext) {
                loadingSubtext.textContent = progressMessages[progressStep];
            }
        }
    }, 20000); // Update every 20 seconds
    
    // Set initial message
    if (loadingSubtext) {
        loadingSubtext.textContent = progressMessages[0];
    }

    const form = new FormData();
    form.append("file", file);

    try {
        // Create AbortController for timeout
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 90000); // 90 second timeout (increased from 60)
        
        const res = await fetch(`${apiUrl}/upload-resume`, {
            method: "POST",
            body: form,
            signal: controller.signal,
        });

        clearTimeout(timeoutId);
        clearInterval(progressInterval); // Clear progress updates on success

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
        clearInterval(progressInterval); // Clear progress updates on error
        
        if (err.name === 'AbortError' || err.name === 'TimeoutError') {
            showError("Upload timed out after 90 seconds. The resume may be complex or the API is slow. Please try again or check your connection.");
        } else {
            showError("Upload failed: " + err.message);
        }
        loadingScreen.classList.remove("active");
        uploadScreen.classList.remove("hidden");
        
        // Reset loading message
        if (loadingSubtext) {
            loadingSubtext.textContent = "Extracting skills, experience, and qualifications";
        }
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

    // Clear any stale audio buffers from previous sessions
    turnBuffer = [];
    turnBufferStart = null;
    lastVoiceTime = 0;
    isReadyToAnswer = false;
    isSendingAnswer = false;
    capturing = false;

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
            isAudioPlaying = true; // Track that audio is playing
            
            // Helper function to handle audio completion
            const onAudioComplete = () => {
                console.log("Audio playback completed");
                isAudioPlaying = false; // Audio is no longer playing
                URL.revokeObjectURL(url);
                audioChunks = [];
                isReceivingAudio = false;
                
                // If ready_to_listen was received while audio was playing, start countdown now
                if (pendingReadyToListen) {
                    console.log("Audio finished, starting countdown now");
                    pendingReadyToListen = false;
                    startCountdownAndListening();
                }
            };
            
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
                        audioPlayer.onended = onAudioComplete;
                    }).catch((err) => {
                        console.error("HTML5 audio play failed, trying Web Audio API:", err);
                        playWithWebAudioAPI(blob, url, onAudioComplete);
                    });
                };
                
                audioPlayer.onerror = (e) => {
                    console.error("HTML5 audio error, trying Web Audio API:", e);
                    playWithWebAudioAPI(blob, url, onAudioComplete);
                };
                
                audioPlayer.load();
            } else {
                // Browser doesn't support MPEG, use Web Audio API
                console.log("Browser doesn't support MPEG, using Web Audio API");
                playWithWebAudioAPI(blob, url, onAudioComplete);
            }
            
            if (audioTimeoutId) {
                clearTimeout(audioTimeoutId);
                audioTimeoutId = null;
            }
        }
        
        async function playWithWebAudioAPI(blob, url, onComplete) {
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
                    if (onComplete) onComplete();
                    URL.revokeObjectURL(url);
                };
                
                source.start(0);
                console.log("Web Audio API playback started");
            } catch (err) {
                console.error("Web Audio API playback failed:", err);
                console.error("Error details:", {
                    name: err.name,
                    message: err.message,
                    stack: err.stack
                });
                URL.revokeObjectURL(url);
                // On error, still signal completion so interview can continue
                // Reset audio playing state
                isAudioPlaying = false;
                if (onComplete) onComplete();
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

function startCountdownAndListening() {
    // Remove countdown - start listening immediately
    // Clear any previous audio data
    turnBuffer = [];
    turnBufferStart = null;
    lastVoiceTime = 0;
    
    // Check media before starting
    if (!analyserNode) {
        console.error("Cannot start listening: analyserNode is null");
        showError("Microphone not available. Please refresh and allow microphone access.");
        return;
    }
    
    // Check if AudioContext needs to be resumed
    if (audioContext && audioContext.state === 'suspended') {
        console.log("AudioContext suspended, attempting to resume...");
        audioContext.resume().then(() => {
            console.log("AudioContext resumed, starting audio processing");
            isReadyToAnswer = true;
            questionText.textContent = "🎤 Your turn! Please speak your answer now...";
            updateConversationState("listening");
            startAudioProcessing();
        }).catch((err) => {
            console.error("Failed to resume AudioContext:", err);
            showError("Please click anywhere on the page to activate the microphone.");
        });
        return;
    }
    
    isReadyToAnswer = true; // Ready to accept answers immediately
    
    // Show clear "Your Turn" message
    questionText.textContent = "🎤 Your turn! Please speak your answer now...";
    updateConversationState("listening");
    
    startAudioProcessing();
}

function handleJson(msg) {
    // Handle resume_summary early to prevent "Unknown message" warning
    // Don't add to transcript - this is internal context only
    if (msg.type === "resume_summary") {
        return;
    }
    
    switch (msg.type) {
        case "question_text":
            // Stop any ongoing audio processing when new question arrives
            stopAudioProcessing();
            isReadyToAnswer = false; // Reset flag - wait for ready_to_listen
            pendingReadyToListen = false; // Reset pending flag
            isAudioPlaying = false; // Reset audio playing flag
            isSendingAnswer = false; // Reset sending flag
            // Clear any existing countdown
            if (countdownInterval) {
                clearInterval(countdownInterval);
                countdownInterval = null;
            }
            // Clear any buffered audio from previous turn
            turnBuffer = [];
            turnBufferStart = null;
            lastVoiceTime = 0;
            
            // Update question display
            questionText.textContent = msg.text;
            // Only add to transcript if it's different from what's already displayed
            // Check if the last transcript entry is the same question to avoid duplication
            const transcriptEntries = document.querySelectorAll('.transcript-entry');
            const lastEntry = transcriptEntries[transcriptEntries.length - 1];
            const isDuplicate = lastEntry && 
                                lastEntry.classList.contains('assistant') && 
                                lastEntry.textContent.trim() === msg.text.trim();
            
            if (!isDuplicate) {
                addTranscriptEntry("assistant", msg.text);
            }
            // Don't start listening yet - wait for ready_to_listen signal
            // Audio will be played when stream completes (handled in onmessage)
            updateConversationState("speaking");
            break;
        case "ready_to_listen":
            // Backend has finished sending audio and is ready for answer
            console.log("System ready to listen - starting audio capture");
            
            // Stop any existing audio processing first
            stopAudioProcessing();
            
            // CRITICAL: Clear any stale audio buffer before starting new capture
            turnBuffer = [];
            turnBufferStart = null;
            lastVoiceTime = 0;
            isSendingAnswer = false; // Reset sending flag
            
            // Clear any existing countdown
            if (countdownInterval) {
                clearInterval(countdownInterval);
                countdownInterval = null;
            }
            
            // If audio is still playing, wait for it to finish
            if (isAudioPlaying) {
                console.log("Audio still playing, will start listening when audio finishes");
                pendingReadyToListen = true;
                // Keep "speaking" state until audio finishes
                break;
            }
            
            // Audio has finished, start listening immediately
            // Note: isReadyToAnswer will be set to true in startCountdownAndListening()
            startCountdownAndListening();
            break;
        case "turn_result":
            console.log("=== TURN RESULT RECEIVED ===");
            console.log("Transcript:", msg.transcript);
            console.log("Score:", msg.score);
            console.log("Rationale:", msg.rationale);
            console.log("End interview:", msg.end_interview);
            console.log("============================");
            
            // Always display the actual transcript from backend
            if (msg.transcript && msg.transcript.trim()) {
                addTranscriptEntry("candidate", msg.transcript);
                console.log("Transcript displayed in UI:", msg.transcript);
            } else {
                console.warn("Received empty transcript in turn_result!");
                addTranscriptEntry("candidate", "[No transcript available]");
            }
            
            stopAudioProcessing(); // Stop listening when answer is processed
            isReadyToAnswer = false; // Reset flag
            if (countdownInterval) {
                clearInterval(countdownInterval);
                countdownInterval = null;
            }
            if (msg.end_interview) {
                updateConversationState("processing");
            } else {
                updateConversationState("processing"); // Show processing while next question is generated
            }
            break;
        case "done":
            updateConversationState("ready");
            stopTimer();
            stopAudioProcessing();
            isReadyToAnswer = false; // Reset flag
            if (countdownInterval) {
                clearInterval(countdownInterval);
                countdownInterval = null;
            }
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
            // ready_to_listen will be sent after tts_error, so don't start here
            break;
        case "error":
            showError(msg.message);
            // Reset state on error
            stopAudioProcessing();
            isReadyToAnswer = false;
            if (countdownInterval) {
                clearInterval(countdownInterval);
                countdownInterval = null;
            }
            break;
        default:
            console.warn("Unknown message", msg);
    }
}

async function setupMedia() {
    try {
        console.log("Requesting microphone access...");
        const stream = await navigator.mediaDevices.getUserMedia({ 
            audio: {
                sampleRate: 44100, // Higher sample rate for better quality
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            }
        });
        console.log("Microphone access granted");
        
        // Use higher sample rate for better transcription accuracy
        audioContext = new AudioContext({ sampleRate: 44100 });
        mediaStreamSource = audioContext.createMediaStreamSource(stream);
        
        analyserNode = audioContext.createAnalyser();
        analyserNode.fftSize = 2048;
        analyserNode.smoothingTimeConstant = 0.8;
        mediaStreamSource.connect(analyserNode);
        
        const bufferLength = analyserNode.frequencyBinCount;
        audioDataArray = new Float32Array(bufferLength);
        
        console.log("Media setup complete:", {
            hasAudioContext: !!audioContext,
            hasAnalyserNode: !!analyserNode,
            hasAudioDataArray: !!audioDataArray,
            bufferLength: bufferLength,
            sampleRate: audioContext.sampleRate
        });
    } catch (e) {
        const errorMsg = "Microphone access denied: " + e.message;
        console.error("Media setup error:", e);
        showError(errorMsg);
        // Don't silently fail - show error to user
        updateConversationState("ready");
    }
}

function processAudio() {
    if (!capturing || !analyserNode) {
        if (!capturing) {
            console.log("processAudio: not capturing, stopping");
        }
        if (!analyserNode) {
            console.error("processAudio: analyserNode is null!");
        }
        return;
    }
    
    // Log periodically to verify the loop is running
    if (turnBuffer.length % 200 === 0 && turnBuffer.length > 0) {
        console.log(`processAudio: running, buffer_size=${turnBuffer.length}, capturing=${capturing}`);
    }
    
    analyserNode.getFloatTimeDomainData(audioDataArray);
    handleAudioData(audioDataArray);
    
    animationFrameId = requestAnimationFrame(processAudio);
}

function handleAudioData(audioData) {
    if (!capturing) return;
    const now = performance.now();
    
    // Improved voice detection: check for sustained voice, not just peaks
    let maxAmplitude = 0;
    let voiceSamples = 0;
    
    for (let i = 0; i < audioData.length; i++) {
        const amplitude = Math.abs(audioData[i]);
        if (amplitude > maxAmplitude) {
            maxAmplitude = amplitude;
        }
        // Count samples above threshold to detect sustained voice
        // Slightly higher threshold (0.015) to reduce noise sensitivity
        if (amplitude > 0.015) {
            voiceSamples++;
        }
    }
    
    // Require at least 10% of samples to be above threshold for sustained voice
    const voiced = voiceSamples > (audioData.length * 0.1);
    
    // Log amplitude periodically to debug voice detection
    if (turnBuffer.length % 100 === 0) {
        console.log(`Audio amplitude: max=${maxAmplitude.toFixed(4)}, voiced=${voiced}, voice_samples=${voiceSamples}/${audioData.length}, buffer_size=${turnBuffer.length}`);
    }
    
    // Track when voice was first detected (not just any audio)
    if (voiced && lastVoiceTime === 0) {
        console.log("Voice detected! Starting to record answer...");
        lastVoiceTime = now; // Only set when voice is actually detected
    }
    
    // Update lastVoiceTime only when voice is detected
    if (voiced) {
        lastVoiceTime = now;
    }
    
    turnBuffer.push(new Float32Array(audioData));

    const elapsed = now - (turnBufferStart || now);
    // Calculate silence: if no voice detected, silence = elapsed time
    const silenceElapsed = lastVoiceTime > 0 ? (now - lastVoiceTime) : elapsed;

    if (!turnBufferStart) {
        turnBufferStart = now;
        console.log("Started buffering audio at:", new Date().toISOString());
    }

    // Calculate voiced duration: how long the candidate has actually been speaking
    // This is total elapsed time minus silence time
    // If no voice detected, duration is 0
    const voicedDuration = lastVoiceTime > 0 ? (elapsed - silenceElapsed) : 0;
    let dynamicSilenceMs = vadSilenceMs;
    let dynamicMaxTurnMs = vadMaxTurnMs;

    // Dynamically adjust thresholds based on actual speech length:
    // - Short answers (< 2s of speech): shorter silence threshold (600ms) and max turn (15s)
    // - Long answers (> 6s of speech): longer silence threshold (1500ms) and max turn (45s)
    // - Medium answers: default thresholds (1200ms silence, 30s max turn)
    if (voicedDuration < 2000) {
        // Short answer detected - candidate is speaking briefly
        dynamicSilenceMs = 600;
        dynamicMaxTurnMs = 15000;
    } else if (voicedDuration > 6000) {
        // Long answer detected - candidate is speaking at length
        dynamicSilenceMs = 1500;
        dynamicMaxTurnMs = 45000;
    }
    
    // CRITICAL FIX: Only finalize if we've actually detected voice
    // Don't finalize on silence alone - require at least some voice detection
    // Check if we've had at least 500ms of actual voice (not just background noise)
    const hasDetectedVoice = lastVoiceTime > 0 && voicedDuration > 500; // At least 500ms of actual voice
    
    // Only finalize if:
    // 1. We've detected actual voice (hasDetectedVoice)
    // 2. AND (silence threshold exceeded OR max turn time exceeded)
    if (capturing && hasDetectedVoice && (
        (silenceElapsed > dynamicSilenceMs && elapsed > vadMinVoiceMs) || 
        elapsed > dynamicMaxTurnMs
    )) {
        console.log(`Finalizing turn: elapsed=${elapsed.toFixed(0)}ms, silence=${silenceElapsed.toFixed(0)}ms, voiced_duration=${voicedDuration.toFixed(0)}ms, has_voice=${hasDetectedVoice}`);
        finalizeTurn();
    }
}

function startAudioProcessing() {
    // Clear any previous audio data before starting
    turnBuffer = [];
    turnBufferStart = null;
    lastVoiceTime = 0;
    
    // Check if media was set up successfully
    if (!analyserNode) {
        console.error("Cannot start audio processing: analyserNode is null. Media setup may have failed.");
        showError("Microphone not available. Please refresh and allow microphone access.");
        updateConversationState("ready");
        return;
    }
    
    if (!audioDataArray) {
        console.error("Cannot start audio processing: audioDataArray is null.");
        showError("Audio processing not initialized. Please refresh the page.");
        updateConversationState("ready");
        return;
    }
    
    // Check and resume AudioContext if suspended (browser autoplay policy)
    if (audioContext && audioContext.state === 'suspended') {
        console.log("AudioContext is suspended, resuming...");
        audioContext.resume().then(() => {
            console.log("AudioContext resumed successfully");
            startAudioProcessingInternal();
        }).catch((err) => {
            console.error("Failed to resume AudioContext:", err);
            showError("Failed to activate microphone. Please click anywhere on the page and try again.");
        });
        return;
    }
    
    startAudioProcessingInternal();
}

function startAudioProcessingInternal() {
    capturing = true;
    updateConversationState("listening");
    
    console.log("Starting audio processing - ready to capture candidate response");
    console.log("AudioContext state:", audioContext ? audioContext.state : "null");
    console.log("AnalyserNode:", analyserNode, "AudioDataArray:", audioDataArray);
    
    if (!animationFrameId && analyserNode) {
        processAudio();
        console.log("Audio processing loop started");
    } else {
        console.warn("Audio processing not started:", {
            hasAnimationFrame: !!animationFrameId,
            hasAnalyserNode: !!analyserNode
        });
    }
}

function stopAudioProcessing() {
    capturing = false;
    if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
    }
}

function float32ToWavBase64(buffers, sampleRate = 44100) {
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
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        console.log("Cannot finalize turn: WebSocket not open");
        return;
    }
    if (!turnBuffer || turnBuffer.length === 0) {
        console.log("Cannot finalize turn: Empty buffer");
        return;
    }
    
    // Prevent multiple sends
    if (isSendingAnswer) {
        console.warn("Already sending answer, ignoring duplicate call");
        return;
    }
    
    // Don't send if we're not ready to answer (e.g., during countdown)
    if (!isReadyToAnswer) {
        console.log("Cannot finalize turn: Not ready to answer yet (countdown in progress)");
        turnBuffer = [];
        turnBufferStart = null;
        lastVoiceTime = performance.now();
        return;
    }
    
    // Calculate total audio duration - use actual sample rate from audioContext
    const actualSampleRate = audioContext ? audioContext.sampleRate : 44100;
    const totalSamples = turnBuffer.reduce((acc, buf) => acc + buf.length, 0);
    const durationSeconds = totalSamples / actualSampleRate;
    
    console.log(`Finalizing turn: ${durationSeconds.toFixed(2)}s of audio, ${turnBuffer.length} buffers, sample rate: ${actualSampleRate}Hz`);
    
    // CRITICAL FIX: Increase minimum duration and require actual voice content
    // Don't send if audio is too short (less than 1.5 seconds) - likely noise or accidental trigger
    // This prevents sending audio when candidate hasn't actually spoken
    if (durationSeconds < 1.5) {
        console.log("Audio too short or no voice detected, ignoring:", durationSeconds, "seconds");
        // Reset buffer but keep listening
        turnBuffer = [];
        turnBufferStart = null;
        lastVoiceTime = performance.now();
        return;
    }
    
    // Stop audio processing before sending to prevent multiple sends
    stopAudioProcessing();
    isReadyToAnswer = false; // Prevent sending again until next ready_to_listen
    isSendingAnswer = true; // Set flag to prevent duplicate sends
    updateConversationState("processing");
    
    console.log("=== SENDING ANSWER TO BACKEND ===");
    console.log(`Audio duration: ${durationSeconds.toFixed(2)} seconds`);
    console.log(`Sample rate: ${actualSampleRate}Hz`);
    console.log(`Buffer chunks: ${turnBuffer.length}`);
    console.log(`Current question context: ${questionText.textContent}`);
    console.log(`Timestamp: ${new Date().toISOString()}`);
    
    // Create a hash of the audio to verify uniqueness
    if (turnBuffer.length > 0 && turnBuffer[0].length > 0) {
        const sampleHash = Array.from(turnBuffer[0].slice(0, Math.min(100, turnBuffer[0].length)))
            .map(v => String.fromCharCode(Math.floor((v + 1) * 127)))
            .join('');
        console.log(`Audio hash (first 100 samples): ${btoa(sampleHash).substring(0, 20)}...`);
    }
    
    const base64Audio = float32ToWavBase64(turnBuffer, actualSampleRate);
    console.log(`Base64 audio length: ${base64Audio.length} characters`);
    console.log(`Base64 audio preview: ${base64Audio.substring(0, 50)}...`);
    console.log("===================================");
    
    ws.send(
        JSON.stringify({
            type: "answer",
            data: { audio_base64: base64Audio, mime_type: "audio/wav" },
        })
    );
    
    // Clear buffer after sending
    turnBuffer = [];
    turnBufferStart = null;
    lastVoiceTime = 0;
    isSendingAnswer = false; // Reset flag after sending
}
