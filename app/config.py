from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API keys
    eleven_api_key: str = Field(..., env="ELEVEN_API_KEY")
    eleven_voice_id: str = Field(..., env="ELEVEN_VOICE_ID")
    openai_api_key: str = Field(..., env="OPENAI_API_KEY")

    # Tunables
    tts_stability: float = Field(0.45, env="ELEVEN_TTS_STABILITY")
    tts_similarity_boost: float = Field(0.8, env="ELEVEN_TTS_SIMILARITY")
    tts_streaming_latency: int = Field(2, env="ELEVEN_TTS_LATENCY")  # 0-4

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

