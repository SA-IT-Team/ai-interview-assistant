const API_URL = 'http://localhost:8000';

let conversationHistory = [];
let jobRole = '';
let resumeText = '';
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

document.getElementById('fileUpload').addEventListener('click', () => {
    document.getElementById('resumeFile').click();
});

document.getElementById('resumeFile').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (file) {
        document.getElementById('fileLabel').textContent = `✅ ${file.name}`;
        document.getElementById('fileUpload').classList.add('has-file');
        
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            const response = await fetch(`${API_URL}/upload-resume`, {
                method: 'POST',
                body: formData
            });
            const data = await response.json();
            resumeText = data.text;
        } catch (error) {
            console.error('Error uploading resume:', error);
        }
    }
});

async function startInterview() {
    jobRole = document.getElementById('jobRole').value.trim();
    
    if (!jobRole) {
        alert('Please enter a job role');
        return;
    }
    
    document.getElementById('setupPanel').style.display = 'none';
    document.getElementById('chatContainer').style.display = 'block';
    
    conversationHistory = [];
    
    await getInterviewerResponse();
}

async function getInterviewerResponse() {
    try {
        const response = await fetch(`${API_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: '',
                conversation_history: conversationHistory,
                job_role: jobRole,
                resume_text: resumeText
            })
        });
        
        const data = await response.json();
        const assistantMessage = data.response;
        
        conversationHistory.push({ role: 'assistant', content: assistantMessage });
        addMessageToChat('assistant', assistantMessage);
        
        await playTTS(assistantMessage);
        
    } catch (error) {
        console.error('Error getting response:', error);
        addMessageToChat('assistant', 'Sorry, there was an error. Please try again.');
    }
}

async function sendMessage() {
    const input = document.getElementById('userInput');
    const message = input.value.trim();
    
    if (!message) return;
    
    input.value = '';
    
    conversationHistory.push({ role: 'user', content: message });
    addMessageToChat('user', message);
    
    await getInterviewerResponse();
}

function handleKeyPress(event) {
    if (event.key === 'Enter') {
        sendMessage();
    }
}

function addMessageToChat(role, content) {
    const messagesContainer = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    const avatar = role === 'assistant' ? '🤖' : '👤';
    
    messageDiv.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">${content}</div>
    `;
    
    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

async function playTTS(text) {
    try {
        const response = await fetch(`${API_URL}/tts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
        
        const audioBlob = await response.blob();
        const audioUrl = URL.createObjectURL(audioBlob);
        const audio = new Audio(audioUrl);
        await audio.play();
        
    } catch (error) {
        console.error('TTS error:', error);
    }
}

async function toggleRecording() {
    const micBtn = document.getElementById('micBtn');
    
    if (!isRecording) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];
            
            mediaRecorder.ondataavailable = (event) => {
                audioChunks.push(event.data);
            };
            
            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                await transcribeAudio(audioBlob);
                stream.getTracks().forEach(track => track.stop());
            };
            
            mediaRecorder.start();
            isRecording = true;
            micBtn.classList.add('recording');
            
        } catch (error) {
            console.error('Microphone error:', error);
            alert('Could not access microphone');
        }
    } else {
        mediaRecorder.stop();
        isRecording = false;
        micBtn.classList.remove('recording');
    }
}

async function transcribeAudio(audioBlob) {
    try {
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');
        
        const response = await fetch(`${API_URL}/stt`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        document.getElementById('userInput').value = data.text;
        
    } catch (error) {
        console.error('STT error:', error);
    }
}

async function endInterview() {
    document.getElementById('chatContainer').style.display = 'none';
    document.getElementById('evaluationPanel').style.display = 'block';
    document.getElementById('evaluationContent').innerHTML = '<div class="loading"></div> Generating evaluation...';
    
    try {
        const response = await fetch(`${API_URL}/evaluate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                conversation_history: conversationHistory,
                job_role: jobRole
            })
        });
        
        const data = await response.json();
        document.getElementById('evaluationContent').textContent = data.evaluation;
        
    } catch (error) {
        console.error('Evaluation error:', error);
        document.getElementById('evaluationContent').textContent = 'Error generating evaluation. Please try again.';
    }
}

function resetInterview() {
    conversationHistory = [];
    jobRole = '';
    resumeText = '';
    
    document.getElementById('jobRole').value = '';
    document.getElementById('resumeFile').value = '';
    document.getElementById('fileLabel').textContent = '📄 Click to upload PDF resume';
    document.getElementById('fileUpload').classList.remove('has-file');
    document.getElementById('chatMessages').innerHTML = '';
    
    document.getElementById('evaluationPanel').style.display = 'none';
    document.getElementById('chatContainer').style.display = 'none';
    document.getElementById('setupPanel').style.display = 'block';
}
