import asyncio
import logging
import httpx
from .config import get_settings

logger = logging.getLogger(__name__)


class TTSException(Exception):
    """Custom exception for TTS errors"""
    pass


async def stream_eleven(text: str):
    """
    Stream ElevenLabs TTS audio chunks for the given text.
    Yields raw audio bytes suitable for WebSocket binary frames.
    
    Raises TTSException on error.
    """
    settings = get_settings()
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{settings.eleven_voice_id}/stream"
    headers = {
        "xi-api-key": settings.eleven_api_key,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2",
        "voice_settings": {
            "stability": settings.tts_stability,
            "similarity_boost": settings.tts_similarity_boost,
        },
        "optimize_streaming_latency": settings.tts_streaming_latency,
    }
    
    logger.info(f"Starting TTS request: text_length={len(text)}, voice_id={settings.eleven_voice_id}")
    chunk_count = 0
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        chunk_count += 1
                        yield chunk
                    await asyncio.sleep(0)  # cooperative scheduling
        logger.info(f"TTS request completed successfully: {chunk_count} chunks received")
    except httpx.HTTPStatusError as e:
        error_msg = f"ElevenLabs API error: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        raise TTSException(error_msg) from e
    except httpx.RequestError as e:
        error_msg = f"Network error connecting to ElevenLabs API: {str(e)}"
        logger.error(error_msg)
        raise TTSException(error_msg) from e
    except httpx.TimeoutException as e:
        error_msg = f"Timeout connecting to ElevenLabs API: {str(e)}"
        logger.error(error_msg)
        raise TTSException(error_msg) from e
    except Exception as e:
        error_msg = f"Unexpected error in TTS: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise TTSException(error_msg) from e
