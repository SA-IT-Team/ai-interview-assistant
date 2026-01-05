import base64
import io
import logging
from typing import Optional
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
    """
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    audio_bytes = base64.b64decode(audio_base64)
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
        logger.info(f"Transcribing audio: {len(audio_bytes)} bytes, format: {mime_type}")
        if current_question:
            logger.info(f"Using question context: {current_question[:100]}...")
        result = await client.audio.transcriptions.create(
            file=file_like,
            model="whisper-1",
            language="en",
            response_format="json",
            prompt=prompt
        )
        transcript = result.text.strip()
        logger.info(f"=== TRANSCRIPTION SUCCESSFUL ===")
        logger.info(f"Full transcript: '{transcript}'")
        logger.info(f"Transcript length: {len(transcript)} characters")
        if current_question:
            logger.info(f"Question context was: '{current_question[:100]}...'")
        logger.info(f"=================================")
        return transcript if transcript else None
    except Exception as e:
        logger.error(f"Transcription failed: {str(e)}", exc_info=True)
        return None
