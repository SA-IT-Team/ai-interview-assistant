# AI Interview Assistant (Python + FastAPI)

Minimal scaffold for an AI-led voice screening round using:
- FastAPI + WebSockets
- ElevenLabs for TTS
- OpenAI Whisper for STT
- OpenAI GPT-4o-mini for follow-ups/scoring

## Quickstart
1) Install deps (ideally in a venv):
   ```
   pip install -r requirements.txt
   ```
2) Set environment variables (or a `.env` file):
   - `ELEVEN_API_KEY`
   - `ELEVEN_VOICE_ID`
   - `OPENAI_API_KEY`
   - Optional tunables: `ELEVEN_TTS_STABILITY` (default 0.45), `ELEVEN_TTS_SIMILARITY` (0.8), `ELEVEN_TTS_LATENCY` (2)
3) Run the server:
   ```
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

4) Frontend:
   - Option A: open `frontend/index.html` directly in a browser.
   - Option B (recommended): run the Node static server:
     ```
     cd frontend
     npm install
     WS_URL=ws://localhost:8000/ws/interview API_URL=http://localhost:8000 npm run start
     ```
     Then open http://localhost:5173
   - Upload a PDF resume, click “Start Interview”, allow microphone, then “Send Answer” to record a 4s answer (adjust in `frontend/app.js`).

## Resume upload
- Endpoint: `POST /upload-resume` (multipart form, field `file`, PDF only). Returns `resume_context` with summary, roles, skills, projects, claims, experience_years.
- Frontend uploads the resume first, then passes `resume_context` in the WebSocket start message.

## WebSocket protocol (happy path)
- Client sends `{"type":"start","data":{"role":"Backend","level":"Mid","candidate_name":"A","resume_context":{...},"initial_question":"I will ask questions about your profile. Shall we start?"}}`
- Server replies with `question_text` and streams ElevenLabs audio chunks as binary frames.
- Client sends answers as base64 audio: `{"type":"answer","data":{"audio_base64":"...","mime_type":"audio/webm"}}`
- Server responds with `turn_result` (transcript, score, rationale, red_flags) and next `question_text` + audio.
- Server may send `summary` (human-readable) and `json_report` (structured evaluation) before `done`.
- Server ends with `done` when `end_interview` is true or after 6 questions.

## Files of interest
- `app/main.py` — FastAPI app + WS loop.
- `app/tts.py` — ElevenLabs streaming TTS.
- `app/stt.py` — Whisper transcription of base64 audio.
- `app/llm.py` — LLM call for follow-ups and scoring.
- `app/schemas.py` — Pydantic message models.
- `app/config.py` — Environment-driven settings.

## Notes
- This is a skeleton; add auth, storage, persistence, and VAD as needed.
- Frontend should play binary audio frames in order and send base64-encoded mic captures. Optional: add markers for audio start/end if your client needs them.