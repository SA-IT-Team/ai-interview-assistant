import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Optional
import httpx
from openai import AsyncOpenAI
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .config import get_settings
from .schemas import AnswerPayload, LlmResult, SessionState, StartPayload
from .stt import transcribe_base64_audio
from .llm import call_llm, generate_greeting
from .tts import stream_eleven, TTSException
from .resume import extract_text_from_pdf, summarize_resume

logger = logging.getLogger(__name__)

app = FastAPI(title="AI Interview Assistant", version="0.1.0")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Configure CORS - must be added before routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins like ["http://localhost:5174"]
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    """Handle CORS preflight requests"""
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )


@app.get("/health")
async def health():
    settings = get_settings()
    return JSONResponse({"status": "ok", "voice_id": settings.eleven_voice_id})


@app.get("/test-openai")
async def test_openai():
    """Test OpenAI API connection and response time."""
    try:
        settings = get_settings()
        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=10.0)
        
        import time
        start = time.time()
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say 'OK'"}],
            max_tokens=10,
        )
        elapsed = time.time() - start
        
        return {
            "status": "success",
            "response": resp.choices[0].message.content,
            "response_time_seconds": round(elapsed, 2)
        }
    except Exception as e:
        logger.error(f"OpenAI test failed: {str(e)}", exc_info=True)
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


@app.get("/test-tts")
async def test_tts():
    """
    Test endpoint to verify ElevenLabs TTS configuration and API connectivity.
    Returns status and any error messages.
    """
    settings = get_settings()
    result = {
        "status": "unknown",
        "api_key_configured": bool(settings.eleven_api_key),
        "voice_id_configured": bool(settings.eleven_voice_id),
        "voice_id": settings.eleven_voice_id if settings.eleven_voice_id else None,
        "error": None,
        "chunks_received": 0,
    }
    
    # Check if credentials are configured
    if not settings.eleven_api_key:
        result["status"] = "error"
        result["error"] = "ELEVEN_API_KEY is not configured"
        return JSONResponse(result, status_code=400)
    
    if not settings.eleven_voice_id:
        result["status"] = "error"
        result["error"] = "ELEVEN_VOICE_ID is not configured"
        return JSONResponse(result, status_code=400)
    
    # Test with a short text
    test_text = "Hello, this is a test."
    logger.info(f"Testing TTS with text: '{test_text}'")
    
    try:
        chunk_count = 0
        async for chunk in stream_eleven(test_text):
            chunk_count += 1
            if chunk_count > 10:  # Limit to first 10 chunks for testing
                break
        
        result["status"] = "success"
        result["chunks_received"] = chunk_count
        result["message"] = f"TTS test successful: received {chunk_count} audio chunks"
        logger.info(f"TTS test successful: {chunk_count} chunks")
        return JSONResponse(result)
    except TTSException as e:
        result["status"] = "error"
        result["error"] = str(e)
        logger.error(f"TTS test failed: {str(e)}")
        return JSONResponse(result, status_code=500)
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Unexpected error: {str(e)}"
        logger.error(f"TTS test unexpected error: {str(e)}", exc_info=True)
        return JSONResponse(result, status_code=500)


@app.post("/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    request_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    
    try:
        file_size = file.size if hasattr(file, 'size') else None
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Received resume upload request: {file.filename}, size: {file_size}")
        
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF resumes are supported.")
        
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Reading file content...")
        content = await file.read()
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] File read: {len(content)} bytes")
        
        if not content:
            raise HTTPException(status_code=400, detail="File is empty.")
        
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Starting PDF text extraction...")
        text = await extract_text_from_pdf(content, request_id)  # Now async, pass request_id
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] PDF extraction completed: {len(text)} characters")
        
        if not text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from PDF.")
        
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Starting OpenAI summarization...")
        summary = await summarize_resume(text, request_id)  # Pass request_id
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] OpenAI summarization completed")
        
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Resume processing completed successfully")
        return {"resume_context": summary}
    except HTTPException:
        elapsed = time.time() - start_time
        logger.error(f"[{request_id}] [{elapsed:.2f}s] HTTPException raised")
        raise
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[{request_id}] [{elapsed:.2f}s] Error processing resume: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing resume: {str(e)}")


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
        
        # Require resume context
        if not start_payload.resume_context:
            await ws.send_json({"type": "error", "message": "Resume is required to start interview"})
            await ws.close()
            return
        
        # Use name from resume if available
        candidate_name = start_payload.resume_context.name or start_payload.candidate_name
        
        state = SessionState(
            role=start_payload.role,
            level=start_payload.level,
            candidate_name=candidate_name,
            resume_context=start_payload.resume_context,
            history=[],
            interview_started_at=datetime.now().isoformat(),
        )
        
        # Display resume summary
        resume_summary_text = ""
        if state.resume_context.summary:
            resume_summary_text = f"Based on your resume: {state.resume_context.summary}"
        elif state.resume_context.skills:
            top_skills = ", ".join(state.resume_context.skills[:3])
            resume_summary_text = f"I see you have experience with {top_skills}."
        if resume_summary_text:
            await ws.send_json({"type": "resume_summary", "text": resume_summary_text})
        
        # Generate varied greeting
        greeting = await generate_greeting(candidate_name)
        current_question = greeting
        await ws.send_json({"type": "question_text", "text": current_question})
        
        # Stream TTS audio with error handling
        logger.info(f"Starting TTS for greeting: {len(current_question)} characters")
        try:
            chunk_count = 0
            async for chunk in stream_eleven(current_question):
                await ws.send_bytes(chunk)
                chunk_count += 1
            logger.info(f"TTS streaming completed: {chunk_count} chunks sent")
            # Signal that audio is complete and system is ready to listen
            await ws.send_json({"type": "ready_to_listen"})
        except TTSException as e:
            logger.error(f"TTS failed for greeting: {str(e)}")
            await ws.send_json({"type": "tts_error", "message": f"Audio generation failed: {str(e)}"})
            # Even on TTS error, allow text-based interview
            await ws.send_json({"type": "ready_to_listen"})

        # Main turn loop
        while True:
            try:
                logger.info("Waiting for answer from candidate...")
                # Remove timeout - wait indefinitely for candidate's answer
                # The frontend VAD will handle when to send the answer based on actual speech
                msg = await ws.receive_json()
                logger.info(f"Received message type: {msg.get('type')}")
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected by client")
                return
            except Exception as e:
                logger.error(f"Error receiving message: {str(e)}", exc_info=True)
                await ws.send_json({"type": "error", "message": "Error receiving answer"})
                continue
                
            if msg.get("type") != "answer":
                await ws.send_json({"type": "error", "message": "expected answer message"})
                continue

            payload = AnswerPayload(**msg["data"])
            transcript = await transcribe_base64_audio(
                payload.audio_base64, 
                payload.mime_type,
                current_question=current_question
            )
            
            # Stricter validation: reject empty or whitespace-only transcripts
            if not transcript or not transcript.strip():
                logger.warning(f"Received empty or invalid transcript, ignoring answer")
                await ws.send_json({"type": "error", "message": "transcription failed or empty"})
                # Don't repeat question immediately - wait for next answer attempt
                continue
            
            # Log the actual transcript for debugging - this should always be the real Whisper result
            logger.info(f"=== TRANSCRIPT RECEIVED ===")
            logger.info(f"Full transcript: '{transcript}'")
            logger.info(f"Transcript length: {len(transcript)} characters")
            logger.info(f"Current question: '{current_question[:100] if current_question else 'None'}...'")
            logger.info(f"===========================")

            # Check for consent cancellation (first answer only)
            if len(state.history) == 0 and not state.consent_given:
                # Log the actual transcript for debugging
                logger.info(f"Consent answer received: '{transcript}'")
                transcript_lower = transcript.lower()
                cancel_keywords = ["no", "not now", "later", "cancel", "not ready", "wait"]
                if any(keyword in transcript_lower for keyword in cancel_keywords):
                    # Generate canceled evaluation
                    canceled_eval = {
                        "status": "canceled",
                        "resume_summary": state.resume_context.summary if state.resume_context else None,
                        "questions": [{"q": current_question, "a": transcript}],
                        "evaluation": {
                            "communication": 0,
                            "technical": 0,
                            "problem_solving": 0,
                            "culture_fit": 0,
                            "recommendation": "reject"
                        }
                    }
                    await ws.send_json({"type": "json_report", "data": canceled_eval})
                    await send_report_to_company(state, canceled_eval)
                    await ws.send_json({"type": "done", "message": "Interview canceled. Thank you."})
                    await ws.close()
                    return
                else:
                    state.consent_given = True
                    # Send the consent answer transcript to frontend for display
                    await ws.send_json({
                        "type": "turn_result",
                        "transcript": transcript,  # Show what candidate actually said
                        "score": 0,  # No score for consent
                        "rationale": "Consent given",
                        "red_flags": [],
                        "end_interview": False,
                    })
                    
                    # Don't call LLM for consent answer - proceed directly to intro question
                    # Set the intro question directly
                    current_question = "Please introduce yourself in 60 seconds focusing on your most relevant experience for this role."
                    await ws.send_json({"type": "question_text", "text": current_question})
                    
                    # Stream TTS for intro question
                    logger.info(f"Starting TTS for intro question: {len(current_question)} characters")
                    try:
                        chunk_count = 0
                        async for chunk in stream_eleven(current_question):
                            await ws.send_bytes(chunk)
                            chunk_count += 1
                        logger.info(f"TTS streaming completed: {chunk_count} chunks sent")
                        await ws.send_json({"type": "ready_to_listen"})
                    except TTSException as e:
                        logger.error(f"TTS failed for intro question: {str(e)}")
                        await ws.send_json({"type": "tts_error", "message": f"Audio generation failed: {str(e)}"})
                        await ws.send_json({"type": "ready_to_listen"})
                    
                    # Continue to next iteration to wait for intro answer
                    continue

            # Call LLM for scoring + next question (only after consent is given)
            logger.info(f"Calling LLM: question_count={state.question_count}, has_asked_intro={state.has_asked_intro}, has_asked_behavioral={state.has_asked_behavioral}, transcript='{transcript[:50]}...'")
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
            logger.info(f"LLM response: answer_score={llm_result.answer_score}, question_type={llm_result.question_type}, end_interview={llm_result.end_interview}")

            # Track question types and struggle streak
            if llm_result.question_type == "intro":
                state.has_asked_intro = True
            elif llm_result.question_type == "behavioral":
                state.has_asked_behavioral = True

            # Very simple struggle heuristic based on low answer scores.
            if llm_result.answer_score <= 2:
                state.struggle_streak += 1
            else:
                state.struggle_streak = 0

            state.question_count += 1
            state.history.append({
                "q": current_question, 
                "a": transcript, 
                "score": llm_result.answer_score,
                "type": llm_result.question_type or "technical"
            })
            
            # Send turn_result with actual transcript from Whisper (never hardcoded)
            await ws.send_json(
                {
                    "type": "turn_result",
                    "transcript": transcript,  # This is always the actual Whisper transcript
                    "score": llm_result.answer_score,
                    "rationale": llm_result.rationale,
                    "red_flags": llm_result.red_flags,
                    "end_interview": llm_result.end_interview,
                }
            )

            # Check if interview should end
            # Dynamic ending based on signal quality and LLM decision
            # Calculate signal quality metrics
            if state.history:
                avg_score = sum(turn.get('score', 3) for turn in state.history) / len(state.history)
                high_score_count = sum(1 for turn in state.history if turn.get('score', 3) >= 4)
                low_score_count = sum(1 for turn in state.history if turn.get('score', 3) <= 2)
                has_strong_signals = avg_score >= 3.5 and high_score_count >= 2 and len(state.history) >= 4
                has_weak_signals = avg_score <= 2.5 and low_score_count >= 3 and len(state.history) >= 5
            else:
                avg_score = 0
                has_strong_signals = False
                has_weak_signals = False
            
            # Dynamic ending conditions:
            # 1. LLM decides to end (and we have at least 1 real question)
            # 2. Strong signals collected (high scores, good coverage) after minimum questions
            # 3. Weak signals but enough questions asked (candidate struggling, move on)
            # 4. Maximum safety limit (12 questions) to prevent infinite loops
            should_end = (
                (llm_result.end_interview and state.question_count >= 1) or
                (has_strong_signals and state.has_asked_intro and (state.has_asked_behavioral or state.question_count >= 5)) or
                (has_weak_signals and state.question_count >= 6) or
                state.question_count >= 12  # Safety maximum (increased from 8)
            )
            
            logger.info(f"Interview end check: should_end={should_end}, question_count={state.question_count}, end_interview={llm_result.end_interview}, has_asked_intro={state.has_asked_intro}, has_asked_behavioral={state.has_asked_behavioral}, avg_score={avg_score:.1f}, has_strong_signals={has_strong_signals}")
            
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
                
                # Send report to company endpoint if configured
                await send_report_to_company(state, final_eval)
                
                await ws.send_json({"type": "done", "message": "Interview complete. Thank you!"})
                await ws.close()
                return

            current_question = llm_result.next_question
            await ws.send_json({"type": "question_text", "text": current_question})
            
            # Stream TTS audio with error handling
            logger.info(f"Starting TTS for question: {len(current_question)} characters")
            try:
                chunk_count = 0
                async for chunk in stream_eleven(current_question):
                    await ws.send_bytes(chunk)
                    chunk_count += 1
                logger.info(f"TTS streaming completed: {chunk_count} chunks sent")
                # Signal that audio is complete and system is ready to listen
                await ws.send_json({"type": "ready_to_listen"})
            except TTSException as e:
                logger.error(f"TTS failed for question: {str(e)}")
                await ws.send_json({"type": "tts_error", "message": f"Audio generation failed: {str(e)}"})
                # Even on TTS error, allow text-based interview
                await ws.send_json({"type": "ready_to_listen"})

    except WebSocketDisconnect:
        return
    except Exception as exc:
        await ws.send_json({"type": "error", "message": str(exc)})
        await asyncio.sleep(0)


def generate_final_evaluation(state: SessionState, last_llm_result: LlmResult) -> dict:
    """
    Generate final evaluation JSON matching the schema:
    {
      "status": "completed|canceled",
      "resume_summary": "...",
      "questions": [{"q": "...", "a": "..."}],
      "evaluation": {
        "communication": 1-5,
        "technical": 1-5,
        "problem_solving": 1-5,
        "culture_fit": 1-5,
        "recommendation": "move_forward|hold|reject"
      }
    }
    """
    questions = [
        {"q": turn["q"], "a": turn["a"]}
        for turn in state.history
    ]

    # Aggregate scores from history
    if state.history:
        scores = [turn.get("score", 3) for turn in state.history]
        avg_score = sum(scores) / len(scores)
        communication_score = last_llm_result.answer_score
        
        # Calculate technical score from technical questions
        technical_turns = [t for t in state.history if t.get("type") in ["technical", "followup"]]
        technical_score = (
            sum(t.get("score", 3) for t in technical_turns) / len(technical_turns)
            if technical_turns
            else avg_score
        )
        
        # Problem solving from behavioral and follow-up questions
        problem_turns = [t for t in state.history if t.get("type") in ["behavioral", "followup"]]
        problem_score = (
            sum(t.get("score", 3) for t in problem_turns) / len(problem_turns)
            if problem_turns
            else avg_score
        )
        
        # Culture fit from behavioral questions
        behavioral_turns = [t for t in state.history if t.get("type") == "behavioral"]
        culture_score = (
            sum(t.get("score", 3) for t in behavioral_turns) / len(behavioral_turns)
            if behavioral_turns
            else avg_score
        )
    else:
        avg_score = 3
        communication_score = 3
        technical_score = 3
        problem_score = 3
        culture_score = 3

    overall_avg = (communication_score + technical_score + problem_score + culture_score) / 4
    recommendation = (
        "move_forward" if overall_avg >= 4
        else "hold" if overall_avg >= 3
        else "reject"
    )

    resume_summary = state.resume_context.summary if state.resume_context and state.resume_context.summary else None

    return {
        "status": "completed",
        "resume_summary": resume_summary,
        "questions": questions,
        "evaluation": {
            "communication": int(round(communication_score)),
            "technical": int(round(technical_score)),
            "problem_solving": int(round(problem_score)),
            "culture_fit": int(round(culture_score)),
            "recommendation": recommendation,
        },
    }


def generate_human_summary(state: SessionState, evaluation: dict) -> str:
    """Generate a human-readable summary."""
    candidate_name = state.candidate_name or "The candidate"
    role = state.role
    eval_scores = evaluation.get("evaluation", {})
    avg_score = sum(eval_scores.values()) / len(eval_scores) if eval_scores else 3
    
    recommendation = eval_scores.get("recommendation", "hold")
    rec_text = {
        "move_forward": "Recommend moving to technical interview",
        "hold": "Recommend holding for further review",
        "reject": "Recommend rejection"
    }.get(recommendation, "Recommend further review")
    
    strengths = []
    if eval_scores.get("technical", 0) >= 4:
        strengths.append("strong technical skills")
    if eval_scores.get("communication", 0) >= 4:
        strengths.append("clear communication")
    if eval_scores.get("problem_solving", 0) >= 4:
        strengths.append("good problem-solving")
    
    strengths_text = ", ".join(strengths) if strengths else "adequate skills"
    
    return (
        f"{candidate_name} demonstrates {strengths_text} for the {role} position. "
        f"Overall assessment shows {avg_score:.1f}/5 average across evaluation dimensions. "
        f"{rec_text}."
    )


async def send_report_to_company(state: SessionState, evaluation: dict) -> None:
    """
    Send the final evaluation report to the configured company endpoint.
    Handles errors gracefully without failing the interview.
    """
    settings = get_settings()
    if not settings.company_report_endpoint:
        return
    
    try:
        interview_duration = None
        if state.interview_started_at:
            start_time = datetime.fromisoformat(state.interview_started_at)
            end_time = datetime.now()
            interview_duration = int((end_time - start_time).total_seconds())
        
        report_payload = {
            "candidate_name": state.candidate_name or "Unknown",
            "interview_date": state.interview_started_at or datetime.now().isoformat(),
            "duration_seconds": interview_duration or 0,
            "evaluation": evaluation,
            "resume_summary": state.resume_context.summary if state.resume_context else None,
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.company_report_endpoint,
                json=report_payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
    except Exception as e:
        # Log error but don't fail the interview
        print(f"Failed to send report to company endpoint: {e}")



