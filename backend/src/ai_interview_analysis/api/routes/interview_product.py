"""Turn-based mock interview + optional audio helpers."""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ai_interview_analysis.api.deps import get_current_user
from ai_interview_analysis.db.models import User
from ai_interview_analysis.db.session import get_db
from ai_interview_analysis.services import mock_orchestration
from ai_interview_analysis.services.mock_section_scores import public_section_scores

router = APIRouter(tags=["interviews"])


try:
    from ai_interview_analysis.services.tts_google import synthesize_to_mp3 as _tts_mp3
except ImportError:

    def _tts_mp3(_text: str) -> bytes:  # pragma: no cover
        raise RuntimeError("google-cloud-texttospeech not configured")


from ai_interview_analysis.services.speech_stt import transcribe_audio_bytes


class CreateSessionBody(BaseModel):
    resume_profile_id: uuid.UUID
    jd_id: uuid.UUID | None = None
    role: str = "Software Engineer"
    level: str = Field(default="mid")
    interview_type: str = Field(default="behavioral")
    max_followups_per_topic: int = Field(default=2, ge=0, le=4)


class CreateSessionResp(BaseModel):
    session_id: str
    assistant_message: str


class SubmitAnswerBody(BaseModel):
    text: str | None = None
    modality: str | None = "text"


@router.get("/interviews/sessions/active")
def get_active_session(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    s = mock_orchestration.get_active_session(db, user.id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no active session")
    turns = [{"role": t.role, "content": t.content, "evaluation": t.evaluation} for t in sorted(s.turns, key=lambda x: x.turn_index)]
    raw_outline = s.outline if isinstance(s.outline, dict) else {}
    topic_list = raw_outline.get("topics") if isinstance(raw_outline.get("topics"), list) else []
    sess_st = s.session_state if isinstance(s.session_state, dict) else {}
    la = sess_st.get("last_activity_at")
    return {
        "id": str(s.id),
        "role": s.role,
        "level": s.level,
        "interview_type": s.interview_type,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "phase": s.phase,
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        "final_report": s.final_report,
        "turns": turns,
        "topic_index": s.topic_index,
        "topics": topic_list,
        "topics_total": len(topic_list),
        "section_scores": public_section_scores(s),
        "last_activity_at": la if isinstance(la, str) else None,
    }


@router.get("/interviews/sessions")
def list_sessions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    from sqlalchemy import select as _select
    from ai_interview_analysis.db.models import MockInterviewSession as _S

    rows = db.execute(
        _select(_S)
        .where(_S.user_id == user.id)
        .order_by(_S.ended_at.desc().nulls_last())
        .limit(50)
    ).scalars().all()

    # Hide cancelled attempts from history UI.
    rows = [
        s
        for s in rows
        if not (isinstance(s.session_state, dict) and s.session_state.get("cancelled") is True)
    ]
    # Hide ended sessions with zero user answers (accidental / idle starts).
    rows = [
        s
        for s in rows
        if not (isinstance(s.session_state, dict) and s.session_state.get("ended_without_answers") is True)
    ]
    return [
        {
            "id": str(s.id),
            "role": s.role,
            "level": s.level,
            "interview_type": s.interview_type,
            "phase": s.phase,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "final_report": s.final_report,
        }
        for s in rows
    ]


@router.post("/interviews/sessions", response_model=CreateSessionResp)
def create_mock_session(
    body: CreateSessionBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CreateSessionResp:
    try:
        _sess, bundle = mock_orchestration.start_session(
            db,
            user_id=user.id,
            resume_profile_id=body.resume_profile_id,
            jd_id=body.jd_id,
            role=body.role,
            level=body.level.lower(),
            interview_type=body.interview_type.lower(),
            max_followups=body.max_followups_per_topic,
        )
        return CreateSessionResp(session_id=bundle["session_id"], assistant_message=bundle["assistant_message"])
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid resume_profile_id")


@router.get("/interviews/sessions/{session_id}")
def get_mock_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    s = mock_orchestration.get_session(db, session_id, user.id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session")
    turns = [{"role": t.role, "content": t.content, "evaluation": t.evaluation} for t in sorted(s.turns, key=lambda x: x.turn_index)]
    raw_outline = s.outline if isinstance(s.outline, dict) else {}
    topic_list = raw_outline.get("topics") if isinstance(raw_outline.get("topics"), list) else []
    sess_st = s.session_state if isinstance(s.session_state, dict) else {}
    la = sess_st.get("last_activity_at")
    return {
        "id": str(s.id),
        "role": s.role,
        "level": s.level,
        "interview_type": s.interview_type,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "phase": s.phase,
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        "final_report": s.final_report,
        "turns": turns,
        "topic_index": s.topic_index,
        "topics": topic_list,
        "topics_total": len(topic_list),
        "section_scores": public_section_scores(s),
        "last_activity_at": la if isinstance(la, str) else None,
    }


@router.post("/interviews/sessions/{session_id}/answers")
def submit_answer(
    session_id: uuid.UUID,
    body: SubmitAnswerBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not body.text or not body.text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "text required")

    try:
        return mock_orchestration.submit_answer(
            db,
            user_id=user.id,
            session_id=session_id,
            answer_text=body.text.strip(),
            modality=body.modality,
        )
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="session not found")
    except RuntimeError as exc:
        if str(exc) == "session_already_ended":
            raise HTTPException(status.HTTP_410_GONE, detail="session ended") from exc
        if str(exc) == "session_not_accepting_answers":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="session not accepting answers",
            ) from exc
        logger.warning("submit_answer RuntimeError: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                str(exc)[:500]
                if len(str(exc)) <= 600
                else "The AI service returned an error. Wait a moment and try again."
            ),
        ) from exc
    except Exception as exc:
        logger.exception("submit_answer failed")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not process your answer right now. Please try again in a few seconds.",
        ) from exc


@router.post("/interviews/sessions/{session_id}/report")
def finalize_mock_interview_report(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Complete report generation after the interview entered `closing` (goodbye shown)."""
    try:
        out = mock_orchestration.finalize_pending_session_report(db, session_id, user.id)
    except Exception as exc:
        logger.exception("finalize_mock_interview_report failed session_id=%s", session_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not generate your performance report right now. Try again shortly.",
        ) from exc
    if out is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="session is not waiting for report generation",
        )
    return out


@router.post("/interviews/sessions/{session_id}/end")
def end_mock_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Force-end a session and generate the final performance report."""
    try:
        result = mock_orchestration.end_session(db, session_id, user.id)
    except Exception as exc:
        logger.exception("end_mock_session failed session_id=%s", session_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not finalize this interview session right now. Please try again in a few seconds.",
        ) from exc
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return result


@router.post("/interviews/sessions/{session_id}/heartbeat")
def heartbeat_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Keep-alive to prevent idle end while user is typing/thinking."""
    try:
        ok = mock_orchestration.heartbeat_session(db, session_id, user.id)
    except Exception as exc:
        logger.exception("heartbeat_session failed session_id=%s", session_id)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="heartbeat failed") from exc
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return {"status": "ok"}


@router.post("/interviews/sessions/{session_id}/cancel")
def cancel_mock_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Fast-stop a session (no report generation) so the user can retry immediately."""
    try:
        result = mock_orchestration.cancel_session(db, session_id, user.id)
    except Exception as exc:
        logger.exception("cancel_mock_session failed session_id=%s", session_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not cancel this interview session right now. Please try again in a few seconds.",
        ) from exc
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return result


@router.post("/speech/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    _user: User = Depends(get_current_user),
) -> dict[str, str]:
    blob = await audio.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")
    mime = audio.content_type or "audio/wav"
    text = transcribe_audio_bytes(blob, mime_type=mime)
    return {"text": text}


class TtsRequest(BaseModel):
    text: str = Field(default="", max_length=5000)


@router.post("/speech/synthesize")
def synthesize(
    body: TtsRequest,
    _user: User = Depends(get_current_user),
) -> Response:
    if not body.text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "plain text required")

    try:
        audio = _tts_mp3(body.text[:5000])
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return Response(content=audio, media_type="audio/mpeg")


