import os
from dataclasses import dataclass
from pathlib import Path

_dotenv_loaded = False


def load_env() -> None:
    """Load `.env` from the project root into `os.environ` (once)."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        _dotenv_loaded = True
        return

    # This file: src/ai_interview_analysis/core/config.py -> project root is parents[3]
    root = Path(__file__).resolve().parents[3]
    env_path = root / ".env"
    if env_path.is_file():
        load_dotenv(env_path)
    _dotenv_loaded = True


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    speechmatics_api_key: str | None


def get_settings() -> Settings:
    load_env()
    return Settings(
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        speechmatics_api_key=os.environ.get("SPEECHMATICS_API_KEY"),
    )

