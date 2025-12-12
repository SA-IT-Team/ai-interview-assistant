import base64
import io
from typing import Optional
from openai import AsyncOpenAI
from .config import get_settings


async def transcribe_base64_audio(audio_base64: str, mime_type: str = "audio/webm") -> Optional[str]:
    """
    Transcribe a base64-encoded audio payload using OpenAI Whisper API.
    Returns the text transcript or None on failure.
    """
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    audio_bytes = base64.b64decode(audio_base64)
    file_like = io.BytesIO(audio_bytes)
    file_like.name = f"audio.{mime_type.split('/')[-1]}"
    try:
        result = await client.audio.transcriptions.create(
            file=file_like,
            model="whisper-1",
            language="en",
            response_format="json",
        )
        return result.text
    except Exception:
        return None



