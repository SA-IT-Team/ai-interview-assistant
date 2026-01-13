import asyncio
import httpx
from .config import get_settings


class TTSException(Exception):
    """Custom exception for TTS errors."""
    pass


async def stream_eleven(text: str):
    """
    Stream ElevenLabs TTS audio chunks for the given text.
    Yields raw audio bytes suitable for WebSocket binary frames.
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
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield chunk
                    await asyncio.sleep(0)  # cooperative scheduling
    except httpx.HTTPStatusError as e:
        # For streaming responses, we need to read the response before accessing .text
        error_message = f"ElevenLabs API error: {e.response.status_code}"
        try:
            # Try to read the error response body
            # For streaming responses, use aread() to read the body
            error_body = await e.response.aread()
            if error_body:
                error_message += f" - {error_body.decode('utf-8', errors='ignore')}"
        except (AttributeError, httpx.ResponseNotRead, Exception):
            # If we can't read the error body (streaming response not read, or other error),
            # just use the status code - this is fine for error reporting
            pass
        
        # Add helpful message for 401 errors
        if e.response.status_code == 401:
            error_message += " (Check that ELEVEN_API_KEY is set correctly in Railway environment variables)"
        
        raise TTSException(error_message)
    except httpx.RequestError as e:
        raise TTSException(f"Network error calling ElevenLabs: {str(e)}")
    except Exception as e:
        raise TTSException(f"Unexpected TTS error: {str(e)}")
