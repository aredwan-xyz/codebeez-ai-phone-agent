from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "AI Phone Agent"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    base_url: str = "https://your-ngrok-or-domain.com"

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Deepgram
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    deepgram_language: str = "en-US"

    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_model_id: str = "eleven_turbo_v2_5"

    # Anthropic / Claude
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_phone_agent"

    # Agent persona
    agent_name: str = "Aria"
    agent_company: str = "Acme Corp"
    agent_timezone: str = "America/New_York"

    # Google Calendar
    google_credentials_path: Optional[str] = None
    google_calendar_id: str = "primary"

    # HubSpot
    hubspot_api_key: Optional[str] = None

    # Observability
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: Optional[str] = None

    # VAD / latency tuning
    vad_silence_threshold_ms: int = 700    # ms of silence before treating as end-of-turn
    max_agent_tokens: int = 1024

    model_config = {"env_file": ".env", "case_sensitive": False}


@lru_cache
def get_settings() -> Settings:
    return Settings()
