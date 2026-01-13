from functools import lru_cache
from typing import Optional
import logging
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


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
        validated = v.strip()
        
        # Log validation (mask sensitive data)
        if info.field_name == "eleven_api_key":
            preview = validated[:8] + "..." + validated[-4:] if len(validated) > 12 else "***"
            logger.info(f"Loaded {info.field_name}: {preview} (length: {len(validated)})")
        else:
            logger.info(f"Loaded {info.field_name}: {validated}")
        
        return validated

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
    """Get settings instance (cached). Clear cache if environment variables change."""
    return Settings()


def clear_settings_cache():
    """Clear the settings cache. Useful when environment variables are updated."""
    get_settings.cache_clear()
    logger.info("Settings cache cleared")
