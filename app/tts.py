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
        raise TTSException(f"ElevenLabs API error: {e.response.status_code} - {e.response.text}")
    except httpx.RequestError as e:
        raise TTSException(f"Network error calling ElevenLabs: {str(e)}")
    except Exception as e:
        raise TTSException(f"Unexpected TTS error: {str(e)}")
