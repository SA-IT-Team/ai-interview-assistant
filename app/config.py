from functools import lru_cache
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # API keys - using Field with env parameter for explicit mapping
    eleven_api_key: str = Field(..., env="ELEVEN_API_KEY")
    eleven_voice_id: str = Field(..., env="ELEVEN_VOICE_ID")
    openai_api_key: str = Field(..., env="OPENAI_API_KEY")
    
    @field_validator("eleven_api_key", "eleven_voice_id", "openai_api_key")
    @classmethod
    def validate_api_keys(cls, v: str, info) -> str:
        """Validate that API keys are not empty"""
        if not v or not v.strip():
            field_name = info.field_name
            raise ValueError(f"{field_name} cannot be empty. Please set the {field_name.upper()} environment variable.")
        return v.strip()

    # Tunables - using Field with env parameter
    tts_stability: float = Field(default=0.45, env="ELEVEN_TTS_STABILITY")
    tts_similarity_boost: float = Field(default=0.8, env="ELEVEN_TTS_SIMILARITY")
    tts_streaming_latency: int = Field(default=2, env="ELEVEN_TTS_LATENCY")  # 0-4

    # Company report delivery
    company_report_endpoint: Optional[str] = Field(default=None, env="COMPANY_REPORT_ENDPOINT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore extra env vars that don't map to fields
        case_sensitive=False,  # Allow case-insensitive matching
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
