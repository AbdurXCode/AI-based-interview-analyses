"""Application settings (Pydantic).

Settings are re-read from .env on every call to get_settings() — no caching.
This means changes to .env are picked up immediately without a server restart.
"""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")

    # Core
    env: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/interview_prep"
    jwt_secret: str = "change-me-in-production-use-openssl-rand-hex-32"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 14

    # Legacy (optional; answer-suggestions route)
    openai_api_key: str | None = None
    speechmatics_api_key: str | None = None

    # Google AI / GCP
    gemini_api_key: str | None = None
    # Vertex AI region for ADK (e.g. us-central1). With gcp_project_id + this, JSON
    # generation uses Agent Development Kit (AdkApp) per Google Agent Platform docs.
    vertex_ai_location: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    embedding_model: str = "models/text-embedding-004"
    gcp_project_id: str | None = None
    gcs_bucket_uploads: str | None = None
    speech_language_code: str = "en-US"
    tts_language_code: str = "en-US"
    tts_voice_name: str = "en-US-Neural2-F"

    # Storage
    storage_backend: str = "local"  # local | gcs
    local_upload_dir: str = "./uploads"

    # Feature flags
    feature_video_analysis: bool = False
    use_openai_legacy_answer_suggestions: bool = False

    # CORS
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Rate limiting
    rate_limit_default: str = "200/minute"

    @property
    def cors_origins_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


def _find_env_file() -> Optional[Path]:
    backend_root = Path(__file__).resolve().parents[3]
    repo_root = backend_root.parent
    for p in (backend_root / ".env", repo_root / ".env"):
        if p.is_file():
            return p
    return None


# Discover the .env path once at import time (the path never changes at runtime)
_ENV_FILE: Optional[Path] = _find_env_file()


def get_settings() -> Settings:
    """Read settings fresh from .env on every call.

    Not cached — so editing GEMINI_MODEL, GEMINI_API_KEY or any other value
    in backend/.env is picked up immediately without restarting the server.
    """
    if _ENV_FILE:
        return Settings(_env_file=_ENV_FILE)
    return Settings()


# ── backwards-compat stubs (used by app.py / config.py) ─────────────────────

def reload_settings() -> Settings:
    return get_settings()


def clear_settings_cache() -> None:
    """No-op — caching has been removed from get_settings()."""
    pass
