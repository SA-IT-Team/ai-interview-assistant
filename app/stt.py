import asyncio
import base64
import io
import logging
from typing import Optional, Tuple
from openai import AsyncOpenAI
from .config import get_settings

logger = logging.getLogger(__name__)


async def transcribe_base64_audio(
    audio_base64: str, 
    mime_type: str = "audio/wav",
    current_question: Optional[str] = None
) -> Optional[str]:
    """
    Transcribe a base64-encoded audio payload using OpenAI Whisper API.
    Returns the text transcript or None on failure.
    
    OPTIMIZED: Added timeout and timing logs for latency tracking.
    """
    import time
    start_time = time.time()
    
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=30.0)  # OPTIMIZATION: Add timeout
    audio_bytes = base64.b64decode(audio_base64)
    
    # OPTIMIZATION: Log audio size for optimization tracking
    audio_size_mb = len(audio_bytes) / (1024 * 1024)
    if audio_size_mb > 2.0:
        logger.warning(f"Large audio file: {audio_size_mb:.2f}MB - may take longer to transcribe")
    
    # Validate audio size (should be at least a few KB for real speech)
    if len(audio_bytes) < 1000:  # Less than 1KB is suspicious
        logger.warning(f"Audio too small: {len(audio_bytes)} bytes - likely invalid")
        return None
    
    file_like = io.BytesIO(audio_bytes)
    file_like.name = f"audio.{mime_type.split('/')[-1]}"
    
    # Build dynamic prompt based on context
    prompt_parts = [
        "This is a job interview. The candidate is answering questions from an AI interviewer.",
        "Common phrases include: yes, yes we can start, yes I'm ready, no, I can, I have experience,",
        "I worked on, we can start, let me explain, for example, I would, I did, we implemented,",
        "I used, I developed, I was responsible for, I helped, I created, I built, I designed."
    ]
    
    if current_question:
        # Add the specific question context to help Whisper understand what's being answered
        prompt_parts.append(f"The candidate is responding to this question: {current_question}")
    
    prompt = " ".join(prompt_parts)
    
    try:
        logger.info(f"Transcribing audio: {len(audio_bytes)} bytes ({audio_size_mb:.2f}MB), format: {mime_type}")
        if current_question:
            logger.info(f"Using question context: {current_question[:100]}...")
        
        api_start = time.time()
        result = await client.audio.transcriptions.create(
            file=file_like,
            model="whisper-1",
            language="en",
            response_format="json",
            prompt=prompt
        )
        api_time = time.time() - api_start
        
        transcript = result.text.strip()
        total_time = time.time() - start_time
        
        logger.info(f"=== TRANSCRIPTION SUCCESSFUL ===")
        logger.info(f"Full transcript: '{transcript}'")
        logger.info(f"Transcript length: {len(transcript)} characters")
        logger.info(f"Transcription time: {total_time:.2f}s (API: {api_time:.2f}s)")
        if current_question:
            logger.info(f"Question context was: '{current_question[:100]}...'")
        logger.info(f"=================================")
        return transcript if transcript else None
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"Transcription failed after {elapsed:.2f}s: {str(e)}", exc_info=True)
        return None


async def transcribe_with_early_reasoning(
    audio_base64: str,
    mime_type: str,
    current_question: Optional[str],
    state,
    prepared_context: dict,
    call_llm_func
) -> Tuple[Optional[str], Optional[any]]:
    """
    Simplified transcription - removed incremental approach that was adding latency.
    Now just uses single transcription call for better performance and accuracy.
    
    Returns: (transcript, None) - no early reasoning to avoid latency overhead
    """
    # SIMPLIFIED: Just use single transcription call - it's faster and more accurate
    # The incremental approach was actually slower (2 API calls) and caused quality issues
    try:
        transcript = await transcribe_base64_audio(audio_base64, mime_type, current_question)
        return transcript, None  # No early reasoning - it adds latency without benefit
    except Exception as e:
        logger.error(f"Transcription failed: {str(e)}", exc_info=True)
        return None, None
