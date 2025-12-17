import asyncio
import json
import random
from datetime import datetime
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
            interview_started_at=datetime.now().isoformat(),
        )
        
        # Display resume summary if available
        if state.resume_context:
            resume_summary_text = ""
            if state.resume_context.summary:
                resume_summary_text = f"Based on your resume: {state.resume_context.summary}"
            elif state.resume_context.skills:
                top_skills = ", ".join(state.resume_context.skills[:3])
                resume_summary_text = f"I see you have experience with {top_skills}."
            if resume_summary_text:
                await ws.send_json({"type": "resume_summary", "text": resume_summary_text})
        
        # Greet and ask for consent
        welcomes = [
            "Hello and welcome to this interview session.",
            "Hi, thanks for joining the screening today.",
            "Welcome, and thanks for taking the time to speak with me.",
        ]
        consent_q = "I will ask questions about your profile. Shall we start?"
        welcome = random.choice(welcomes)
        current_question = start_payload.initial_question or consent_q

        combined = f"{welcome} {current_question}"
        await ws.send_json({"type": "question_text", "text": combined})
        async for chunk in stream_eleven(combined):
            await ws.send_bytes(chunk)

        # Main turn loop
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=15)
            except asyncio.TimeoutError:
                # No response — repeat once then end
                await ws.send_json({"type": "question_text", "text": current_question})
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

            # Check for consent cancellation (first answer only)
            if len(state.history) == 0 and not state.consent_given:
                transcript_lower = transcript.lower()
                cancel_keywords = ["no", "not now", "later", "cancel", "not ready", "wait"]
                if any(keyword in transcript_lower for keyword in cancel_keywords):
                    # Generate canceled evaluation
                    canceled_eval = {
                        "status": "canceled",
                        "questions_and_answers": [{"q": current_question, "a": transcript}],
                        "scores": {
                            "communication": 0,
                            "technical": 0,
                            "problem_solving": 0,
                            "culture_fit": 0,
                        },
                        "recommendation": "reject"
                    }
                    await ws.send_json({"type": "json_report", "data": canceled_eval})
                    await ws.send_json({"type": "done", "message": "Interview canceled. Thank you."})
                    await ws.close()
                    return
                else:
                    state.consent_given = True

            # Call LLM for scoring + next question
            llm_result: LlmResult = await call_llm(
                role=state.role,
                level=state.level,
                history=state.history,
                transcript=transcript,
                resume=state.resume_context,
                has_asked_intro=state.has_asked_intro,
                has_asked_behavioral=state.has_asked_behavioral,
                question_count=state.question_count,
            )

            # Track question types
            if llm_result.question_type == "intro":
                state.has_asked_intro = True
            elif llm_result.question_type == "behavioral":
                state.has_asked_behavioral = True
            
            state.question_count += 1
            state.history.append({
                "q": current_question, 
                "a": transcript, 
                "score": llm_result.answer_score,
                "type": llm_result.question_type or "technical"
            })
            
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

            # Check if interview should end
            should_end = (
                llm_result.end_interview or 
                (state.has_asked_intro and state.has_asked_behavioral and state.question_count >= 4) or
                state.question_count >= 8
            )
            
            if should_end:
                # Generate final evaluation if not provided by LLM
                if llm_result.final_json:
                    final_eval = llm_result.final_json
                else:
                    # Generate evaluation from history
                    final_eval = generate_final_evaluation(state, llm_result)
                
                if llm_result.final_summary:
                    await ws.send_json({"type": "summary", "text": llm_result.final_summary})
                else:
                    # Generate summary if not provided
                    summary = generate_human_summary(state, final_eval)
                    await ws.send_json({"type": "summary", "text": summary})
                
                await ws.send_json({"type": "json_report", "data": final_eval})
                await ws.send_json({"type": "done", "message": "Interview complete. Thank you!"})
                await ws.close()
                return

            current_question = llm_result.next_question
            await ws.send_json({"type": "question_text", "text": current_question})
            async for chunk in stream_eleven(current_question):
                await ws.send_bytes(chunk)

    except WebSocketDisconnect:
        return
    except Exception as exc:
        await ws.send_json({"type": "error", "message": str(exc)})
        await asyncio.sleep(0)


def generate_final_evaluation(state: SessionState, last_llm_result: LlmResult) -> dict:
    """Generate final evaluation JSON matching the required schema."""
    questions_and_answers = [
        {"q": turn["q"], "a": turn["a"]} 
        for turn in state.history
    ]
    
    # Aggregate scores from history (simplified - LLM should provide these in final_json)
    avg_score = sum(turn.get("score", 3) for turn in state.history) / len(state.history) if state.history else 3
    
    return {
        "status": "completed",
        "questions_and_answers": questions_and_answers,
        "scores": {
            "communication": last_llm_result.answer_score if state.history else 3,
            "technical": int(avg_score),
            "problem_solving": int(avg_score),
            "culture_fit": int(avg_score),
        },
        "recommendation": "move_forward" if avg_score >= 4 else "hold" if avg_score >= 3 else "reject"
    }


def generate_human_summary(state: SessionState, evaluation: dict) -> str:
    """Generate a human-readable summary."""
    candidate_name = state.candidate_name or "The candidate"
    role = state.role
    avg_score = sum(evaluation["scores"].values()) / len(evaluation["scores"])
    
    recommendation = evaluation["recommendation"]
    rec_text = {
        "move_forward": "Recommend moving to technical interview",
        "hold": "Recommend holding for further review",
        "reject": "Recommend rejection"
    }.get(recommendation, "Recommend further review")
    
    strengths = []
    if evaluation["scores"]["technical"] >= 4:
        strengths.append("strong technical skills")
    if evaluation["scores"]["communication"] >= 4:
        strengths.append("clear communication")
    if evaluation["scores"]["problem_solving"] >= 4:
        strengths.append("good problem-solving")
    
    strengths_text = ", ".join(strengths) if strengths else "adequate skills"
    
    return (
        f"{candidate_name} demonstrates {strengths_text} for the {role} position. "
        f"Overall assessment shows {avg_score:.1f}/5 average across evaluation dimensions. "
        f"{rec_text}."
    )



