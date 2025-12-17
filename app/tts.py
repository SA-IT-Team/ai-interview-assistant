import httpx
from app.config import ELEVEN_API_KEY, ELEVEN_VOICE_ID, ELEVEN_TTS_STABILITY, ELEVEN_TTS_SIMILARITY

async def text_to_speech(text: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVEN_API_KEY
    }
    
    data = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": ELEVEN_TTS_STABILITY,
            "similarity_boost": ELEVEN_TTS_SIMILARITY
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=data, headers=headers, timeout=30.0)
        response.raise_for_status()
        return response.content
