import asyncio
import base64
import hashlib
import json
import logging
import os
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
from .llm import call_llm, generate_greeting, prepare_llm_context
from .tts import stream_eleven, TTSException
from .resume import extract_text_from_pdf, summarize_resume
from .schemas import ResumeContext

logger = logging.getLogger(__name__)


app = FastAPI(title="AI Interview Assistant", version="0.1.0")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Configure CORS - must be added before routes
# Get frontend URL from environment (set this to your Vercel URL in Render)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5174")

# Build allowed origins list
# In production (non-localhost), allow all origins for flexibility
# In local development, only allow localhost
if FRONTEND_URL == "http://localhost:5174":
    # Local development - restrict to localhost
    allowed_origins = ["http://localhost:5174"]
    allow_credentials = True
    logger.info(f"Local development - CORS restricted to localhost")
else:
    # Production - allow all origins (frontend on Vercel, backend on Render)
    allowed_origins = ["*"]
    allow_credentials = False  # Must be False when using wildcard
    logger.info(f"Production mode - allowing all origins (FRONTEND_URL={FRONTEND_URL})")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
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
        # Validate filename
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided.")
        
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF resumes are supported.")
        
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Received resume upload request: {file.filename}")
        
        # Read file content with size validation
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Reading file content...")
        
        # Read in chunks to handle large files and detect size early
        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB limit
        content = b""
        chunk_size = 1024 * 1024  # 1MB chunks
        
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            content += chunk
            if len(content) > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400, 
                    detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024):.0f}MB."
                )
        
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] File read: {len(content)} bytes ({len(content)/(1024*1024):.2f}MB)")
        
        if not content:
            raise HTTPException(status_code=400, detail="File is empty.")
        
        # Validate file is actually a PDF (check magic bytes)
        if not content.startswith(b'%PDF'):
            raise HTTPException(status_code=400, detail="File does not appear to be a valid PDF.")
        
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Starting PDF text extraction...")
        
        # Extract text with timeout protection
        try:
            text = await asyncio.wait_for(
                extract_text_from_pdf(content, request_id),
                timeout=30.0  # 30 second timeout for PDF extraction
            )
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.error(f"[{request_id}] [{elapsed:.2f}s] PDF extraction timed out after 30s")
            raise HTTPException(
                status_code=500,
                detail="PDF processing took too long. Please try with a smaller or simpler PDF file."
            )
        
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] PDF extraction completed: {len(text)} characters")
        
        if not text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from PDF. The file may be image-based or corrupted.")
        
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Starting OpenAI summarization...")
        
        # Summarize with timeout protection
        try:
            summary = await asyncio.wait_for(
                summarize_resume(text, request_id),
                timeout=70.0  # 70 second timeout for OpenAI API (slightly longer than internal timeout)
            )
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.error(f"[{request_id}] [{elapsed:.2f}s] OpenAI summarization timed out after 70s")
            raise HTTPException(
                status_code=500,
                detail="Resume analysis took too long. Please try again or contact support."
            )
        except ValueError as ve:
            # Re-raise ValueError from summarize_resume (timeout errors)
            elapsed = time.time() - start_time
            logger.error(f"[{request_id}] [{elapsed:.2f}s] OpenAI summarization error: {str(ve)}")
            raise HTTPException(status_code=500, detail=str(ve))
        
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] OpenAI summarization completed")
        
        elapsed = time.time() - start_time
        logger.info(f"[{request_id}] [{elapsed:.2f}s] Resume processing completed successfully (total: {elapsed:.2f}s)")
        
        return {"resume_context": summary}
        
    except HTTPException:
        elapsed = time.time() - start_time
        logger.error(f"[{request_id}] [{elapsed:.2f}s] HTTPException raised")
        raise
    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        logger.error(f"[{request_id}] [{elapsed:.2f}s] Error processing resume: {error_msg}", exc_info=True)
        
        # Provide more user-friendly error messages
        if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Request timed out. The resume processing took too long. Please try again with a smaller PDF file."
            )
        elif "connection" in error_msg.lower() or "network" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Network error occurred. Please check your connection and try again."
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Error processing resume: {error_msg}. Please try again or contact support."
            )


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
        # Send question text immediately (frontend will display when audio starts)
        await ws.send_json({"type": "question_text", "text": current_question})
        
        # Stream TTS audio in background - text already sent, so user sees it while audio generates
        async def stream_greeting_tts():
            try:
                logger.info(f"Starting TTS for greeting: {len(current_question)} characters")
                chunk_count = 0
                async for chunk in stream_eleven(current_question):
                    await ws.send_bytes(chunk)
                    chunk_count += 1
                logger.info(f"TTS streaming completed: {chunk_count} chunks sent")
                await ws.send_json({"type": "ready_to_listen"})
            except TTSException as e:
                logger.error(f"TTS failed for greeting: {str(e)}")
                await ws.send_json({"type": "tts_error", "message": f"Audio generation failed: {str(e)}"})
                await ws.send_json({"type": "ready_to_listen"})
            except Exception as e:
                logger.error(f"Unexpected error in greeting TTS streaming: {str(e)}", exc_info=True)
                # Ensure ready_to_listen is always sent, even on unexpected errors
                await ws.send_json({"type": "tts_error", "message": f"Audio generation failed: {str(e)}"})
                await ws.send_json({"type": "ready_to_listen"})
        
        # Start TTS streaming as background task with error callback
        greeting_tts_task = asyncio.create_task(stream_greeting_tts())
        
        def greeting_tts_callback(task):
            try:
                if task.exception():
                    logger.error(f"Greeting TTS task failed with exception: {task.exception()}", exc_info=True)
                else:
                    logger.info(f"Greeting TTS task completed successfully")
            except Exception as e:
                logger.error(f"Error in greeting TTS task callback: {str(e)}", exc_info=True)
        
        greeting_tts_task.add_done_callback(greeting_tts_callback)
        
        # Add safety timeout for greeting TTS
        async def greeting_safety_timeout():
            await asyncio.sleep(30)
            if not greeting_tts_task.done():
                logger.warning("Greeting TTS task taking too long (>30s), sending ready_to_listen as safety measure")
                try:
                    await ws.send_json({"type": "ready_to_listen"})
                except Exception as e:
                    logger.error(f"Error sending safety ready_to_listen for greeting: {str(e)}")
        
        asyncio.create_task(greeting_safety_timeout())

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
            
            # Log audio details for debugging
            audio_bytes = base64.b64decode(payload.audio_base64)
            logger.info(f"=== RECEIVED AUDIO ===")
            logger.info(f"Audio size: {len(audio_bytes)} bytes")
            logger.info(f"MIME type: {payload.mime_type}")
            logger.info(f"Current question: '{current_question[:100] if current_question else 'None'}...'")
            logger.info(f"Audio hash (first 100 bytes): {hashlib.md5(audio_bytes[:100]).hexdigest()}")
            logger.info(f"Timestamp: {datetime.now().isoformat()}")
            logger.info(f"=========================")
            
            # OPTIMIZATION: Start transcription and LLM context preparation in parallel
            turn_start_time = time.time()
            
            # Start transcription task (this is the main bottleneck)
            transcription_task = asyncio.create_task(
                transcribe_base64_audio(
                    payload.audio_base64, 
                    payload.mime_type,
                    current_question=current_question
                )
            )
            
            # OPTIMIZATION: Prepare LLM context in parallel while transcription is running
            # This pre-computes resume text, history summary, and signal quality metrics
            llm_prep_task = asyncio.create_task(
                prepare_llm_context(
                    state=state,
                    current_question=current_question,
                    role=state.role,
                    level=state.level,
                    has_asked_intro=state.has_asked_intro,
                    has_asked_behavioral=state.has_asked_behavioral,
                    question_count=state.question_count,
                    followup_count=state.followup_count,
                    force_new_topic=state.followup_count >= 3,
                )
            )
            
            # Wait for transcription to complete (this is still the bottleneck)
            transcript = await transcription_task
            
            # Stricter validation: reject empty or whitespace-only transcripts
            if not transcript or not transcript.strip():
                logger.warning(f"Received empty or invalid transcript, ignoring answer")
                await ws.send_json({
                    "type": "turn_result",
                    "transcript": "[Could not transcribe audio - please try again]",
                    "score": 0,
                    "rationale": "Audio transcription failed or was too quiet. Please speak clearly and try again.",
                    "red_flags": [],
                    "end_interview": False,
                })
                # Send ready_to_listen to allow candidate to try again
                await ws.send_json({"type": "ready_to_listen"})
                continue
            
            # Log the actual transcript for debugging - this should always be the real Whisper result
            transcription_time = time.time() - turn_start_time
            logger.info(f"=== TRANSCRIPT RECEIVED ===")
            logger.info(f"Full transcript: '{transcript}'")
            logger.info(f"Transcript length: {len(transcript)} characters")
            logger.info(f"Transcription completed in {transcription_time:.2f}s")
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
                    # Send question text immediately (frontend will display when audio starts)
                    await ws.send_json({"type": "question_text", "text": current_question})
                    
                    # Stream TTS for intro question in background
                    async def stream_intro_tts():
                        try:
                            logger.info(f"Starting TTS for intro question: {len(current_question)} characters")
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
                        except Exception as e:
                            logger.error(f"Unexpected error in intro TTS streaming: {str(e)}", exc_info=True)
                            await ws.send_json({"type": "tts_error", "message": f"Audio generation failed: {str(e)}"})
                            await ws.send_json({"type": "ready_to_listen"})
                    
                    # Start TTS streaming as background task with error callback
                    intro_tts_task = asyncio.create_task(stream_intro_tts())
                    
                    def intro_tts_callback(task):
                        try:
                            if task.exception():
                                logger.error(f"Intro TTS task failed with exception: {task.exception()}", exc_info=True)
                            else:
                                logger.info(f"Intro TTS task completed successfully")
                        except Exception as e:
                            logger.error(f"Error in intro TTS task callback: {str(e)}", exc_info=True)
                    
                    intro_tts_task.add_done_callback(intro_tts_callback)
                    
                    # Add safety timeout for intro TTS
                    async def intro_safety_timeout():
                        await asyncio.sleep(30)
                        if not intro_tts_task.done():
                            logger.warning("Intro TTS task taking too long (>30s), sending ready_to_listen as safety measure")
                            try:
                                await ws.send_json({"type": "ready_to_listen"})
                            except Exception as e:
                                logger.error(f"Error sending safety ready_to_listen for intro: {str(e)}")
                    
                    asyncio.create_task(intro_safety_timeout())
                    
                    # Continue to next iteration to wait for intro answer
                continue

            # OPTIMIZATION: LLM context preparation should be complete by now
            # Wait for it if it's not done yet (should be very fast)
            prepared_context = await llm_prep_task
            prep_time = time.time() - turn_start_time
            logger.info(f"LLM context prepared in {prep_time:.2f}s (parallel with transcription)")
            
            # Call LLM for scoring + next question (only after consent is given)
            # LLM will intelligently handle all validation (response quality, resume inconsistencies, etc.)
            force_new_topic = state.followup_count >= 3
            llm_start_time = time.time()
            logger.info(f"Calling LLM: question_count={state.question_count}, has_asked_intro={state.has_asked_intro}, has_asked_behavioral={state.has_asked_behavioral}, followup_count={state.followup_count}, force_new_topic={force_new_topic}, transcript='{transcript[:50]}...'")
            llm_result: LlmResult = await call_llm(
                role=state.role,
                level=state.level,
                history=state.history,
                transcript=transcript,  # Pass transcript directly - LLM handles all validation
                resume=state.resume_context,
                has_asked_intro=state.has_asked_intro,
                has_asked_behavioral=state.has_asked_behavioral,
                question_count=state.question_count,
                followup_count=state.followup_count,
                force_new_topic=force_new_topic,
                prepared_context=prepared_context,  # OPTIMIZATION: Use pre-prepared context
                current_question=current_question,  # Pass current question for context-aware validation
            )
            llm_time = time.time() - llm_start_time
            logger.info(f"LLM call completed in {llm_time:.2f}s")
            
            # Log if LLM detected any issues
            if llm_result.answer_score <= 1:
                logger.warning(f"LLM detected low-quality response (score={llm_result.answer_score}): {llm_result.rationale}")
            if any("resume" in flag.lower() or "inconsistency" in flag.lower() for flag in llm_result.red_flags):
                logger.warning(f"LLM detected resume inconsistency: {llm_result.red_flags}")
                logger.info(f"LLM generated clarification: '{llm_result.next_question}'")
            
            logger.info(f"LLM response: answer_score={llm_result.answer_score}, question_type={llm_result.question_type}, end_interview={llm_result.end_interview}, red_flags={llm_result.red_flags}")

            # Track question types and follow-ups
            if llm_result.question_type == "intro":
                state.has_asked_intro = True
                state.current_topic = None  # Reset topic tracking for new question type
                state.followup_count = 0
            elif llm_result.question_type == "behavioral":
                state.has_asked_behavioral = True
                state.current_topic = None  # Reset topic tracking for new question type
                state.followup_count = 0
            elif llm_result.question_type == "followup":
                # Check if we're following up on the same topic
                if state.current_topic:
                    state.followup_count += 1
                    logger.info(f"Follow-up question #{state.followup_count} on topic: {state.current_topic[:50]}...")
                else:
                    # First follow-up, set the topic based on current question
                    state.current_topic = current_question[:50]  # Use first 50 chars as topic identifier
                    state.followup_count = 1
                    logger.info(f"Starting follow-up sequence on topic: {state.current_topic}")
            else:
                # New question type (technical, etc.) - reset follow-up tracking
                state.current_topic = None
                state.followup_count = 0

            # Check if we've exceeded follow-up limit (3 consecutive follow-ups)
            if state.followup_count >= 3:
                logger.info(f"Reached follow-up limit ({state.followup_count}) on topic. Forcing new question from resume.")
                # Reset tracking - will force new topic in next LLM call
                state.current_topic = None
                state.followup_count = 0

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
            
            # Prevent question repetition
            if state.history:
                previous_questions = [turn["q"].lower().strip() for turn in state.history]
                current_question_lower = current_question.lower().strip()
                
                # Check for exact matches or very similar questions (80% similarity threshold)
                is_repeat = False
                for prev_q in previous_questions:
                    if current_question_lower == prev_q:
                        is_repeat = True
                        break
                    # Check for high similarity (simple word overlap check)
                    current_words = set(current_question_lower.split())
                    prev_words = set(prev_q.split())
                    if len(current_words) > 0 and len(prev_words) > 0:
                        overlap = len(current_words & prev_words) / max(len(current_words), len(prev_words))
                        if overlap > 0.8:  # 80% word overlap indicates repetition
                            is_repeat = True
                            break
                
                if is_repeat:
                    logger.warning(f"LLM attempted to repeat question: '{current_question}'. Generating alternative follow-up.")
                    # Generate a fallback follow-up based on the latest answer
                    latest_answer = state.history[-1]["a"] if state.history else transcript
                    # Extract key phrases and create a specific follow-up
                    answer_words = latest_answer.split()[:20]  # First 20 words
                    key_phrase = " ".join(answer_words[-5:]) if len(answer_words) >= 5 else latest_answer[:50]
                    current_question = f"Can you tell me more about {key_phrase}? Specifically, what challenges did you face and how did you overcome them?"
                    logger.info(f"Generated alternative follow-up: '{current_question}'")
            
            # Send question text IMMEDIATELY (frontend will display when audio starts)
            # This reduces perceived latency - user sees question while TTS generates
            await ws.send_json({"type": "question_text", "text": current_question})
            
            # Stream TTS audio in background task - runs in parallel
            # Text already sent, so user sees it while audio generates
            async def stream_question_tts():
                try:
                    logger.info(f"Starting TTS for question: {len(current_question)} characters")
                    chunk_count = 0
                    async for chunk in stream_eleven(current_question):
                        await ws.send_bytes(chunk)
                        chunk_count += 1
                    logger.info(f"TTS streaming completed: {chunk_count} chunks sent")
                    await ws.send_json({"type": "ready_to_listen"})
                except TTSException as e:
                    logger.error(f"TTS failed for question: {str(e)}")
                    await ws.send_json({"type": "tts_error", "message": f"Audio generation failed: {str(e)}"})
                    await ws.send_json({"type": "ready_to_listen"})
                except Exception as e:
                    logger.error(f"Unexpected error in TTS streaming: {str(e)}", exc_info=True)
                    # Ensure ready_to_listen is always sent, even on unexpected errors
                    await ws.send_json({"type": "tts_error", "message": f"Audio generation failed: {str(e)}"})
                    await ws.send_json({"type": "ready_to_listen"})
            
            # Start TTS streaming as background task - non-blocking
            # Store the task to ensure it completes and doesn't fail silently
            question_tts_task = asyncio.create_task(stream_question_tts())
            
            def tts_task_callback(task):
                try:
                    if task.exception():
                        logger.error(f"Question TTS task failed with exception: {task.exception()}", exc_info=True)
                    else:
                        logger.info(f"Question TTS task completed successfully")
                except Exception as e:
                    logger.error(f"Error in TTS task callback: {str(e)}", exc_info=True)
            
            question_tts_task.add_done_callback(tts_task_callback)
            
            # Add a safety timeout: if TTS doesn't complete in 30 seconds, send ready_to_listen anyway
            async def safety_timeout():
                await asyncio.sleep(30)
                if not question_tts_task.done():
                    logger.warning("TTS task taking too long (>30s), sending ready_to_listen as safety measure")
                    try:
                        await ws.send_json({"type": "ready_to_listen"})
                    except Exception as e:
                        logger.error(f"Error sending safety ready_to_listen: {str(e)}")
            
            asyncio.create_task(safety_timeout())

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



