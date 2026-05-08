"""GDPR-ish export/delete (minimal MVP)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ai_interview_analysis.api.deps import get_current_user
from ai_interview_analysis.db.models import (
    BulletRevision,
    JobDescription,
    MockInterviewSession,
    MockTurn,
    ResumeProfile,
    ResumeUpload,
    User,
)
from ai_interview_analysis.db.session import get_db

router = APIRouter(prefix="/privacy", tags=["privacy"])


def _gather_export(db: Session, user_id: Any) -> dict[str, Any]:
    profiles = db.execute(select(ResumeProfile).where(ResumeProfile.user_id == user_id)).scalars().all()
    jds = db.execute(select(JobDescription).where(JobDescription.user_id == user_id)).scalars().all()
    uploads = db.execute(select(ResumeUpload).where(ResumeUpload.user_id == user_id)).scalars().all()
    sessions = (
        db.execute(select(MockInterviewSession).where(MockInterviewSession.user_id == user_id)).scalars().all()
    )

    sess_out = [
        {"id": str(s.id), "report": s.final_report, "outline": s.outline, "jd_id": str(s.jd_id) if s.jd_id else None}
        for s in sessions
    ]

    return {
        "resume_profiles": [{**(dict(p.profile_data or {})), "profile_id": str(p.id)} for p in profiles],
        "job_descriptions": [{"id": str(j.id), "snippet": j.raw_text[:5000]} for j in jds],
        "uploads": [{"id": str(u.id), "filename": u.filename} for u in uploads],
        "mock_sessions_summary": sess_out,
        "bullet_revision_count": db.scalar(
            select(func.count(BulletRevision.id))
            .join(ResumeProfile, BulletRevision.profile_id == ResumeProfile.id)
            .where(ResumeProfile.user_id == user_id),
        )
            or 0,
    }


@router.get("/export")
def export_my_data(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"user_email": user.email, "payload": _gather_export(db, user.id)}


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    uid = user.id

    for s in db.execute(select(MockInterviewSession).where(MockInterviewSession.user_id == uid)).scalars():
        db.execute(delete(MockTurn).where(MockTurn.session_id == s.id))
        db.delete(s)

    for rp in db.execute(select(ResumeProfile).where(ResumeProfile.user_id == uid)).scalars():
        db.delete(rp)

    db.execute(delete(ResumeUpload).where(ResumeUpload.user_id == uid))
    db.execute(delete(JobDescription).where(JobDescription.user_id == uid))

    u = db.get(User, uid)
    if u is not None:
        db.delete(u)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
