# AI Interview Assistant - Architecture Documentation

## Table of Contents
1. [Project Overview](#project-overview)
2. [System Architecture](#system-architecture)
3. [Technologies Used](#technologies-used)
4. [Application Flow](#application-flow)
5. [Component Details](#component-details)
6. [Data Models](#data-models)
7. [API Endpoints](#api-endpoints)
8. [WebSocket Communication](#websocket-communication)
9. [Frontend Architecture](#frontend-architecture)
10. [Backend Architecture](#backend-architecture)

---

## Project Overview

The AI Interview Assistant is a real-time, voice-based interview screening system that uses AI to conduct adaptive interviews with candidates. The system analyzes resumes, generates personalized questions, conducts voice interviews, and provides evaluation reports.

### Key Features
- **Resume Analysis**: Extracts and summarizes candidate information from PDF resumes
- **Adaptive Question Generation**: Dynamically generates questions based on candidate responses
- **Real-time Voice Interaction**: Bidirectional voice communication using WebSocket
- **Speech-to-Text**: Transcribes candidate responses using OpenAI Whisper
- **Text-to-Speech**: Generates AI voice using ElevenLabs
- **Dynamic Interview Flow**: Adapts question count and depth based on candidate performance
- **Evaluation Reports**: Generates comprehensive candidate assessments

---

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend Layer                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   HTML/UI    │  │   JavaScript │  │  WebSocket   │      │
│  │   (React)    │  │   (app.js)   │  │   Client     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            │                                 │
└────────────────────────────┼─────────────────────────────────┘
                             │
                    HTTP/REST │ WebSocket
                             │
┌────────────────────────────┼─────────────────────────────────┐
│                    Backend Layer (FastAPI)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Main API   │  │   Resume     │  │   LLM        │      │
│  │  (main.py)   │  │  Processing  │  │  (llm.py)    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         │                  │                  │              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   STT        │  │   TTS        │  │   Schemas    │      │
│  │  (stt.py)    │  │  (tts.py)    │  │ (schemas.py) │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└──────────────────────────────────────────────────────────────┘
                             │
                    External APIs
                             │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
┌───────▼──────┐    ┌────────▼────────┐   ┌────────▼────────┐
│   OpenAI     │    │   ElevenLabs   │   │   Company API   │
│  (Whisper +  │    │   (TTS)        │   │  (Reports)      │
│   GPT-4o)    │    │                │   │                 │
└──────────────┘    └────────────────┘   └─────────────────┘
```

### Architecture Patterns
- **Client-Server Architecture**: Frontend communicates with backend via REST and WebSocket
- **Microservices-like Modules**: Backend organized into focused modules (STT, TTS, LLM, Resume)
- **Event-Driven Communication**: WebSocket for real-time bidirectional communication
- **Async/Await Pattern**: Asynchronous processing for I/O-bound operations

---

## Technologies Used

### Backend Technologies

| Technology | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.x | Core backend language |
| **FastAPI** | Latest | Web framework and API server |
| **Uvicorn** | Latest | ASGI server for FastAPI |
| **Pydantic** | Latest | Data validation and settings management |
| **OpenAI API** | Latest | GPT-4o-mini for question generation, Whisper for STT |
| **ElevenLabs API** | Latest | Text-to-Speech voice generation |
| **PyPDF** | Latest | PDF text extraction |
| **httpx** | Latest | Async HTTP client for API calls |
| **python-dotenv** | Latest | Environment variable management |

### Frontend Technologies

| Technology | Version | Purpose |
|------------|---------|---------|
| **HTML5** | - | Structure and UI |
| **CSS3** | - | Styling and layout |
| **JavaScript (ES6+)** | - | Client-side logic |
| **WebSocket API** | - | Real-time bidirectional communication |
| **Web Audio API** | - | Audio capture and playback |
| **MediaRecorder API** | - | Audio recording |
| **Express.js** | 4.18.2 | Static file server |

### External Services

- **OpenAI Whisper**: Speech-to-text transcription
- **OpenAI GPT-4o-mini**: Question generation and answer evaluation
- **ElevenLabs**: Text-to-speech voice synthesis
- **Company Report Endpoint** (Optional): External API for sending evaluation reports

---

## Application Flow

### Complete Interview Flow

```
1. Candidate Uploads Resume
   │
   ├─> Frontend: File upload (PDF)
   │
   ├─> Backend: /upload-resume endpoint
   │   ├─> Extract text from PDF (PyPDF)
   │   ├─> Summarize with OpenAI GPT
   │   └─> Return ResumeContext
   │
   └─> Frontend: Display loading, then show interview screen

2. Interview Initialization
   │
   ├─> Frontend: Establish WebSocket connection
   │
   ├─> Backend: Accept WebSocket, wait for "start" message
   │
   ├─> Frontend: Send start message with resume context
   │
   └─> Backend: Initialize SessionState

3. Greeting Phase
   │
   ├─> Backend: Generate greeting (LLM)
   │
   ├─> Backend: Send question_text message
   │
   ├─> Backend: Stream TTS audio (ElevenLabs)
   │
   ├─> Frontend: Play audio chunks
   │
   └─> Backend: Send ready_to_listen signal

4. Interview Loop (Dynamic)
   │
   ├─> Frontend: Start audio capture (Web Audio API)
   │   ├─> Voice Activity Detection (VAD)
   │   ├─> Buffer audio samples
   │   └─> Detect end of speech (silence detection)
   │
   ├─> Frontend: Convert audio to WAV, encode base64
   │
   ├─> Frontend: Send answer message via WebSocket
   │
   ├─> Backend: Receive audio, transcribe (Whisper)
   │
   ├─> Backend: Validate transcript
   │
   ├─> Backend: Call LLM for scoring + next question
   │   ├─> Analyze answer quality
   │   ├─> Generate adaptive follow-up question
   │   └─> Determine if interview should end
   │
   ├─> Backend: Update SessionState (history, counters)
   │
   ├─> Backend: Send turn_result (transcript, score, rationale)
   │
   ├─> Frontend: Display transcript and score
   │
   ├─> Backend: Check if interview should end
   │   ├─> LLM decision (end_interview flag)
   │   ├─> Signal quality metrics
   │   └─> Question count limits
   │
   ├─> If continuing:
   │   ├─> Backend: Send next question_text
   │   ├─> Backend: Stream TTS audio
   │   └─> Loop back to step 4
   │
   └─> If ending:
       ├─> Backend: Generate final evaluation
       ├─> Backend: Send json_report
       ├─> Backend: Send summary
       ├─> Backend: Send done message
       └─> Frontend: Display results, close connection
```

### Voice Activity Detection (VAD) Flow

```
Audio Capture
   │
   ├─> Web Audio API: Capture microphone input
   │
   ├─> Analyser Node: Get audio samples
   │
   ├─> VAD Logic:
   │   ├─> Calculate amplitude per sample
   │   ├─> Detect voice (amplitude > threshold)
   │   ├─> Track voice duration
   │   ├─> Track silence duration
   │   └─> Buffer audio samples
   │
   ├─> End Detection:
   │   ├─> Silence > threshold (1200ms)
   │   ├─> Voice duration > minimum (600ms)
   │   └─> Total duration < maximum (30s)
   │
   └─> Finalize: Convert to WAV, send to backend
```

---

## Component Details

### Backend Components

#### 1. `main.py` - Core Application
- **Purpose**: FastAPI application, WebSocket handler, HTTP endpoints
- **Key Functions**:
  - `upload_resume()`: Process PDF resume uploads
  - `interview()`: WebSocket handler for interview sessions
  - `send_report_to_company()`: Send evaluation reports to external API
- **Responsibilities**:
  - Session state management
  - Interview flow orchestration
  - Message routing between frontend and backend modules

#### 2. `llm.py` - Language Model Integration
- **Purpose**: Question generation and answer evaluation
- **Key Functions**:
  - `call_llm()`: Generate questions and score answers
  - `generate_greeting()`: Create personalized greetings
- **Features**:
  - Dynamic question generation based on candidate responses
  - Signal quality assessment
  - Adaptive interview ending logic

#### 3. `stt.py` - Speech-to-Text
- **Purpose**: Transcribe candidate audio responses
- **Key Functions**:
  - `transcribe_base64_audio()`: Convert audio to text using Whisper
- **Features**:
  - Context-aware transcription (uses current question as prompt)
  - Audio validation (size checks)
  - Error handling and logging

#### 4. `tts.py` - Text-to-Speech
- **Purpose**: Generate AI voice for questions
- **Key Functions**:
  - `stream_eleven()`: Stream audio chunks from ElevenLabs
- **Features**:
  - Streaming audio for low latency
  - Configurable voice settings (stability, similarity)
  - Error handling with custom exceptions

#### 5. `resume.py` - Resume Processing
- **Purpose**: Extract and summarize resume information
- **Key Functions**:
  - `extract_text_from_pdf()`: Extract text from PDF (async)
  - `summarize_resume()`: Generate structured resume summary
- **Features**:
  - Thread pool executor for CPU-bound PDF extraction
  - Structured data extraction (skills, experience, etc.)
  - Timeout handling for long operations

#### 6. `schemas.py` - Data Models
- **Purpose**: Pydantic models for data validation
- **Key Models**:
  - `ResumeContext`: Parsed resume data
  - `SessionState`: Interview session state
  - `LlmResult`: LLM response structure
  - `FinalEvaluation`: Evaluation report structure

#### 7. `config.py` - Configuration Management
- **Purpose**: Environment variable management and settings
- **Features**:
  - API key validation
  - TTS parameter configuration
  - Company report endpoint configuration
  - LRU cache for settings

### Frontend Components

#### 1. `index.html` - UI Structure
- **Sections**:
  - Upload screen (resume upload)
  - Loading screen (resume processing)
  - Interview screen (two-column layout)
    - Left: Current question display
    - Right: Conversation transcript
- **Features**:
  - Responsive design
  - Dark theme UI
  - Real-time status indicators

#### 2. `app.js` - Core Frontend Logic
- **Key Functions**:
  - `startInterview()`: Initialize WebSocket connection
  - `setupMedia()`: Configure audio capture
  - `startAudioProcessing()`: Begin VAD and audio buffering
  - `finalizeTurn()`: Send audio to backend
  - `handleJson()`: Process WebSocket messages
- **State Management**:
  - Interview state flags (ready, speaking, listening, processing)
  - Audio buffer management
  - WebSocket connection state

#### 3. `server.js` - Static File Server
- **Purpose**: Serve frontend files
- **Technology**: Express.js
- **Port**: 5174

---

## Data Models

### ResumeContext
```python
{
    "name": str | None,
    "summary": str | None,
    "roles": List[str],
    "skills": List[str],
    "tools": List[str],
    "projects": List[str],
    "education": List[str],
    "certifications": List[str],
    "achievements": List[str],
    "experience_years": float | None,
    "claims": List[str]
}
```

### SessionState
```python
{
    "role": str,
    "level": str,
    "candidate_name": str | None,
    "resume_context": ResumeContext | None,
    "history": List[dict],  # [{q, a, score, type}]
    "question_count": int,
    "has_asked_intro": bool,
    "has_asked_behavioral": bool,
    "clarification_attempts": int,
    "struggle_streak": int,
    "interview_started_at": str,
    "consent_given": bool
}
```

### LlmResult
```python
{
    "next_question": str,
    "answer_score": int,  # 1-5
    "rationale": str,
    "red_flags": List[str],
    "end_interview": bool,
    "final_summary": str | None,
    "final_json": dict | None,
    "question_type": str | None  # "intro" | "technical" | "behavioral" | "followup"
}
```

### FinalEvaluation
```python
{
    "status": str,  # "completed" | "canceled"
    "resume_summary": str | None,
    "questions": List[{"q": str, "a": str}],
    "evaluation": {
        "communication": int,  # 1-5
        "technical": int,  # 1-5
        "problem_solving": int,  # 1-5
        "culture_fit": int,  # 1-5
        "recommendation": str  # "move_forward" | "hold" | "reject"
    }
}
```

---

## API Endpoints

### REST Endpoints

#### `GET /health`
- **Purpose**: Health check endpoint
- **Response**: `{"status": "ok"}`

#### `POST /upload-resume`
- **Purpose**: Upload and process PDF resume
- **Request**: Multipart form data with PDF file
- **Response**: `ResumeContext` object
- **Process**:
  1. Extract text from PDF
  2. Summarize with OpenAI GPT
  3. Return structured resume data

#### `GET /test-openai`
- **Purpose**: Test OpenAI API connectivity
- **Response**: Connection status

#### `GET /test-tts`
- **Purpose**: Test ElevenLabs TTS API
- **Response**: TTS configuration and test status

### WebSocket Endpoint

#### `WS /ws/interview`
- **Purpose**: Real-time interview communication
- **Protocol**: JSON messages and binary audio chunks
- **Message Types**:
  - `start`: Initialize interview session
  - `answer`: Send candidate audio response
  - `question_text`: Display question text
  - `turn_result`: Transcript and score
  - `ready_to_listen`: Signal to start recording
  - `json_report`: Final evaluation
  - `summary`: Interview summary
  - `done`: Interview complete
  - `error`: Error message
  - `tts_error`: TTS generation failure

---

## WebSocket Communication

### Message Flow

#### Client → Server Messages

**1. Start Message**
```json
{
    "type": "start",
    "data": {
        "role": "Software Engineer",
        "level": "Mid",
        "candidate_name": "John Doe",
        "resume_context": { /* ResumeContext */ }
    }
}
```

**2. Answer Message**
```json
{
    "type": "answer",
    "data": {
        "audio_base64": "base64_encoded_wav_audio",
        "mime_type": "audio/wav"
    }
}
```

#### Server → Client Messages

**1. Question Text**
```json
{
    "type": "question_text",
    "text": "Please introduce yourself..."
}
```

**2. Audio Chunks (Binary)**
- Raw MP3 audio bytes from ElevenLabs
- Streamed in chunks for low latency

**3. Ready to Listen**
```json
{
    "type": "ready_to_listen"
}
```

**4. Turn Result**
```json
{
    "type": "turn_result",
    "transcript": "Yes, I am ready...",
    "score": 4,
    "rationale": "Clear and confident response...",
    "red_flags": [],
    "end_interview": false
}
```

**5. Final Report**
```json
{
    "type": "json_report",
    "data": { /* FinalEvaluation */ }
}
```

---

## Frontend Architecture

### State Management

The frontend uses a simple state management approach with global variables:

- **Connection State**: `ws`, `resumeContext`
- **Audio State**: `audioContext`, `capturing`, `turnBuffer`
- **Interview State**: `isReadyToAnswer`, `isAudioPlaying`, `pendingReadyToListen`
- **UI State**: Interview screen visibility, conversation status

### Audio Processing Pipeline

```
Microphone Input
    │
    ├─> MediaStream (getUserMedia)
    │
    ├─> AudioContext
    │
    ├─> MediaStreamAudioSourceNode
    │
    ├─> AnalyserNode
    │   ├─> Get audio samples (Float32Array)
    │   └─> Calculate amplitude
    │
    ├─> Voice Activity Detection
    │   ├─> Detect voice (amplitude > 0.015)
    │   ├─> Track voice duration
    │   └─> Track silence duration
    │
    ├─> Buffer Management
    │   ├─> Store samples in turnBuffer
    │   └─> Track buffer start time
    │
    ├─> End Detection
    │   ├─> Silence > 1200ms
    │   ├─> Voice duration > 600ms
    │   └─> Total duration < 30000ms
    │
    └─> Finalization
        ├─> Convert Float32Array to WAV
        ├─> Encode to base64
        └─> Send via WebSocket
```

### UI Components

1. **Upload Screen**: File drag-and-drop interface
2. **Loading Screen**: Progress indicators during resume processing
3. **Interview Screen**:
   - Header: Timer and conversation status
   - Question Panel: Current question display
   - Transcript Panel: Conversation history

---

## Backend Architecture

### Module Organization

```
app/
├── __init__.py          # Package initialization
├── main.py              # FastAPI app, WebSocket handler
├── config.py            # Settings and configuration
├── schemas.py           # Pydantic data models
├── llm.py               # LLM integration (OpenAI GPT)
├── stt.py               # Speech-to-text (OpenAI Whisper)
├── tts.py               # Text-to-speech (ElevenLabs)
└── resume.py            # Resume processing
```

### Async Processing

- **I/O Operations**: All API calls use `async/await`
- **CPU-Bound Tasks**: PDF extraction uses `ThreadPoolExecutor`
- **Streaming**: TTS audio streamed in chunks for low latency
- **Concurrency**: Multiple interview sessions handled concurrently

### Error Handling

- **API Errors**: Custom exceptions (TTSException)
- **Validation**: Pydantic models for request/response validation
- **Logging**: Comprehensive logging with request IDs
- **Graceful Degradation**: Error messages sent to frontend

### Security Considerations

- **API Keys**: Stored in environment variables
- **CORS**: Configurable CORS middleware
- **Input Validation**: Pydantic validation on all inputs
- **Audio Validation**: Size and format checks before processing

---

## Dynamic Interview Logic

### Question Generation Strategy

1. **Response-Based**: Questions derived from candidate's previous answers
2. **Adaptive Depth**: Follow-up questions based on answer quality
3. **Signal Quality**: Metrics used to determine when to end
4. **Coverage**: Ensures technical, behavioral, and communication assessment

### Interview Ending Conditions

The interview ends when:
1. **LLM Decision**: `end_interview = true` (after at least 1 question)
2. **Strong Signals**: High scores (avg ≥3.5, 2+ high scores) after 4+ questions
3. **Weak Signals**: Low scores (avg ≤2.5, 3+ low scores) after 6+ questions
4. **Safety Limit**: Maximum 12 questions to prevent infinite loops

### Signal Quality Metrics

- **Average Score**: Mean of all answer scores
- **High Score Count**: Number of answers scoring ≥4
- **Low Score Count**: Number of answers scoring ≤2
- **Answer Length**: Average character count of responses

---

## Deployment Considerations

### Environment Variables

```bash
# Required
ELEVEN_API_KEY=your_elevenlabs_api_key
ELEVEN_VOICE_ID=your_voice_id
OPENAI_API_KEY=your_openai_api_key

# Optional
ELEVEN_TTS_STABILITY=0.45
ELEVEN_TTS_SIMILARITY=0.8
ELEVEN_TTS_LATENCY=2
COMPANY_REPORT_ENDPOINT=https://api.company.com/reports
```

### Production Recommendations

1. **CORS**: Restrict allowed origins
2. **Rate Limiting**: Implement rate limiting for API endpoints
3. **Monitoring**: Add application monitoring and logging
4. **Scaling**: Consider horizontal scaling for WebSocket connections
5. **Caching**: Cache resume summaries if needed
6. **Error Tracking**: Integrate error tracking service (Sentry, etc.)

---

## Future Enhancements

1. **Database Integration**: Store interview sessions and reports
2. **User Authentication**: Add authentication for candidates
3. **Multi-language Support**: Support interviews in multiple languages
4. **Video Integration**: Add video recording capability
5. **Analytics Dashboard**: Real-time analytics for interviewers
6. **Custom Voice Models**: Support for custom TTS voices
7. **Interview Templates**: Pre-configured interview templates
8. **Export Options**: PDF/CSV export of evaluation reports

---

## Conclusion

The AI Interview Assistant is a sophisticated, real-time voice interview system that leverages modern web technologies and AI services to provide an adaptive, intelligent interview experience. The architecture is designed for scalability, maintainability, and extensibility, with clear separation of concerns and robust error handling.
