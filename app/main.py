import asyncio
import json
import random
from typing import Optional
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from .config import get_settings
from .schemas import AnswerPayload, LlmResult, SessionState, StartPayload
from .stt import transcribe_base64_audio
from .llm import call_llm
from .tts import stream_eleven
from .resume import extract_text_from_pdf, summarize_resume

app = FastAPI(title="AI Interview Assistant", version="0.1.0")


@app.get("/health")
async def health():
    settings = get_settings()
    return JSONResponse({"status": "ok", "voice_id": settings.eleven_voice_id})


@app.post("/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF resumes are supported.")
    content = await file.read()
    text = extract_text_from_pdf(content)
    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from PDF.")
    summary = await summarize_resume(text)
    return {"resume_context": summary}


@app.websocket("/ws/interview")
async def interview(ws: WebSocket):
    await ws.accept()
    settings = get_settings()
    state: Optional[SessionState] = None
    current_question: Optional[str] = None
    try:
        # Expect a start payload first
        start_msg = await ws.receive_json()
        if start_msg.get("type") != "start":
            await ws.send_json({"type": "error", "message": "expected start message"})
            await ws.close()
            return

        start_payload = StartPayload(**start_msg["data"])
        state = SessionState(
            role=start_payload.role,
            level=start_payload.level,
            candidate_name=start_payload.candidate_name,
            resume_context=start_payload.resume_context,
            history=[],
        )
        welcomes = [
            "Hello and welcome to this interview session.",
            "Hi, thanks for joining the screening today.",
            "Welcome, and thanks for taking the time to speak with me.",
        ]
        consents = [
            "Before we begin, is it okay if we start now?",
            "May I have your permission to proceed with the interview?",
            "Can we go ahead and get started?",
            "Are you ready for me to begin?",
        ]
        welcome = random.choice(welcomes)
        consent_q = random.choice(consents)
        current_question = start_payload.initial_question or consent_q

        combined = f"{welcome} {current_question}"
        await ws.send_json({"type": "question_text", "text": combined, "expected_length": "short"})
        async for chunk in stream_eleven(combined):
            await ws.send_bytes(chunk)

        # Main turn loop
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=15)
            except asyncio.TimeoutError:
                # No response — repeat once then end
                await ws.send_json({"type": "question_text", "text": current_question, "expected_length": "short"})
                async for chunk in stream_eleven(current_question):
                    await ws.send_bytes(chunk)
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=15)
                except asyncio.TimeoutError:
                    await ws.send_json({"type": "done", "message": "No response detected. Ending the interview."})
                    await ws.close()
                    return
            if msg.get("type") != "answer":
                await ws.send_json({"type": "error", "message": "expected answer message"})
                continue

            payload = AnswerPayload(**msg["data"])
            transcript = await transcribe_base64_audio(payload.audio_base64, payload.mime_type)
            if not transcript:
                await ws.send_json({"type": "error", "message": "transcription failed"})
                continue

            # Call LLM for scoring + next question
            llm_result: LlmResult = await call_llm(
                role=state.role,
                level=state.level,
                history=state.history,
                transcript=transcript,
                resume=state.resume_context,
            )

            state.history.append({"q": current_question, "a": transcript, "score": llm_result.answer_score})
            await ws.send_json(
                {
                    "type": "turn_result",
                    "transcript": transcript,
                    "score": llm_result.answer_score,
                    "rationale": llm_result.rationale,
                    "red_flags": llm_result.red_flags,
                    "end_interview": llm_result.end_interview,
                }
            )

            if llm_result.end_interview or len(state.history) >= 6:
                if llm_result.final_summary:
                    await ws.send_json({"type": "summary", "text": llm_result.final_summary})
                if llm_result.final_json:
                    await ws.send_json({"type": "json_report", "data": llm_result.final_json})
                await ws.send_json({"type": "done", "message": "Interview complete. Thank you!"})
                await ws.close()
                return

            current_question = llm_result.next_question
            await ws.send_json({"type": "question_text", "text": current_question, "expected_length": llm_result.expected_response_length})
            async for chunk in stream_eleven(current_question):
                await ws.send_bytes(chunk)

    except WebSocketDisconnect:
        return
    except Exception as exc:
        await ws.send_json({"type": "error", "message": str(exc)})
        await asyncio.sleep(0)