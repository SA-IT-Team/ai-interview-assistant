import os
from dotenv import load_dotenv

load_dotenv()

ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID", "MV2lIGFO3SleI2bwL8Cp")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

ELEVEN_TTS_STABILITY = float(os.getenv("ELEVEN_TTS_STABILITY", "0.45"))
ELEVEN_TTS_SIMILARITY = float(os.getenv("ELEVEN_TTS_SIMILARITY", "0.8"))
