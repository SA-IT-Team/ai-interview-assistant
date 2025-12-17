import openai
from app.config import OPENAI_API_KEY

client = openai.OpenAI(api_key=OPENAI_API_KEY)

async def speech_to_text(audio_file) -> str:
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file
    )
    return transcript.text
