from sqlalchemy import text

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ai_interview_analysis.core.settings import get_settings, reload_settings
from ai_interview_analysis.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.post("/health/reload-config")
def reload_config() -> dict[str, str]:
    """Reload settings from .env without restarting the server.
    Call this after changing GEMINI_API_KEY or other settings in .env.
    """
    s = reload_settings()
    key_hint = f"…{s.gemini_api_key[-6:]}" if s.gemini_api_key else "NOT SET"
    return {
        "status": "reloaded",
        "gemini_model": s.gemini_model,
        "gemini_key_tail": key_hint,
    }
