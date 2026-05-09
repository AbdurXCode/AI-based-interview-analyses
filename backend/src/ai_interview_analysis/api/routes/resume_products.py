"""Job descriptions + resume ingestion + profiling + JD analysis."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ai_interview_analysis.api.deps import get_current_user
from ai_interview_analysis.db.models import BulletRevision, JobDescription, ResumeProfile, ResumeUpload, User
from ai_interview_analysis.db.session import get_db

from sqlalchemy import select
from ai_interview_analysis.services import resume_pipeline
from ai_interview_analysis.services.profile_edit import patch_bullet_by_id
from ai_interview_analysis.services.resume_text import extract_text_from_bytes
from ai_interview_analysis.services.storage import read_bytes, save_resume_file


router = APIRouter(prefix="", tags=["resume"])


class JobDescriptionCreate(BaseModel):
    raw_text: str = Field(min_length=20, max_length=120_000)
    role_hint: str | None = None
    title: str | None = None


class JobDescriptionOut(BaseModel):
    id: uuid.UUID
    raw_text: str
    role_hint: str | None
    title: str | None


@router.get("/job-descriptions", response_model=list[JobDescriptionOut])
def list_job_descriptions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[JobDescriptionOut]:
    rows = db.execute(select(JobDescription).where(JobDescription.user_id == user.id)).scalars().all()
    ordered = sorted(rows, key=lambda x: x.created_at, reverse=True)
    return [
        JobDescriptionOut(id=r.id, raw_text=r.raw_text, role_hint=r.role_hint, title=r.title) for r in ordered
    ]


@router.post("/job-descriptions", response_model=JobDescriptionOut)
def create_job_description(
    body: JobDescriptionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobDescriptionOut:
    struct = resume_pipeline.extract_jd_profile(body.raw_text)
    if not isinstance(struct, dict):
        struct = {}
    if not struct.get("valid_jd"):
        msg = str(struct.get("rejection_reason") or "This does not look like a valid job posting.")
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_jd", "message": msg},
        )
    jd = JobDescription(user_id=user.id, raw_text=body.raw_text, role_hint=body.role_hint, title=body.title)
    jd.extracted_keywords = struct
    db.add(jd)
    db.commit()
    db.refresh(jd)
    return JobDescriptionOut(
        id=jd.id,
        raw_text=jd.raw_text,
        role_hint=jd.role_hint,
        title=jd.title,
    )


class ResumeUploadOut(BaseModel):
    upload_id: uuid.UUID
    filename: str
    extracted_preview: str


@router.post("/resume-uploads", response_model=ResumeUploadOut)
async def upload_resume(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    file: UploadFile = File(...),
) -> ResumeUploadOut:
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "filename missing")
    storage_key, _path = save_resume_file(user.id, file)
    data = read_bytes(storage_key)
    try:
        text = extract_text_from_bytes(data, file.filename or "resume.pdf")
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    ru = ResumeUpload(
        user_id=user.id,
        filename=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        storage_key=storage_key,
        extracted_text=text[:500_000],
    )
    db.add(ru)
    db.commit()
    db.refresh(ru)
    return ResumeUploadOut(
        upload_id=ru.id,
        filename=ru.filename,
        extracted_preview=text[:2800],
    )


class ParseProfileBody(BaseModel):
    upload_id: uuid.UUID
    jd_id: uuid.UUID | None = None


class ResumeProfileOut(BaseModel):
    profile_id: uuid.UUID
    version: int
    profile_data: dict[str, Any]
    jd_id: uuid.UUID | None
    created_at: datetime
    source_filename: str | None = None
    match_result: dict[str, Any] | None = None
    feedback: dict[str, Any] | None = None


def _resume_profile_out(db: Session, rp: ResumeProfile) -> ResumeProfileOut:
    filename: str | None = None
    if rp.upload_id:
        ru = db.get(ResumeUpload, rp.upload_id)
        if ru and isinstance(ru.filename, str) and ru.filename.strip():
            filename = ru.filename.strip()
    return ResumeProfileOut(
        profile_id=rp.id,
        version=rp.version or 1,
        profile_data=dict(rp.profile_data or {}),
        jd_id=rp.jd_id,
        created_at=rp.created_at,
        source_filename=filename,
        match_result=dict(rp.match_result) if rp.match_result else None,
        feedback=dict(rp.feedback) if rp.feedback else None,
    )


@router.get("/resume-profiles", response_model=list[ResumeProfileOut])
def list_resume_profiles(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ResumeProfileOut]:
    rows = db.execute(select(ResumeProfile).where(ResumeProfile.user_id == user.id)).scalars().all()
    return [_resume_profile_out(db, rp) for rp in sorted(rows, key=lambda x: x.created_at, reverse=True)]


@router.post("/resume-profiles/from-upload", response_model=ResumeProfileOut)
def parse_profile_from_upload(
    body: ParseProfileBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ResumeProfileOut:
    ru = db.get(ResumeUpload, body.upload_id)
    if not ru or ru.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
    if not ru.extracted_text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no extracted text")

    jd_id = body.jd_id
    if jd_id:
        jd = db.get(JobDescription, jd_id)
        if not jd or jd.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "job description missing")

    try:
        pdata = resume_pipeline.parse_resume_structure(ru.extracted_text)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e

    prof = ResumeProfile(user_id=user.id, upload_id=ru.id, jd_id=jd_id, profile_data=pdata, version=1)
    db.add(prof)
    db.commit()
    db.refresh(prof)
    return _resume_profile_out(db, prof)


class PatchResumeBody(BaseModel):
    profile_data: dict[str, Any] | None = None
    jd_id: uuid.UUID | None = None


@router.patch("/resume-profiles/{profile_id}", response_model=ResumeProfileOut)
def patch_resume_profile(
    profile_id: uuid.UUID,
    body: PatchResumeBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ResumeProfileOut:
    rp = db.get(ResumeProfile, profile_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "profile not found")

    if body.jd_id is not None:
        if body.jd_id:
            jd = db.get(JobDescription, body.jd_id)
            if not jd or jd.user_id != user.id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "job description missing")
        rp.jd_id = body.jd_id
    if body.profile_data is not None:
        rp.version = (rp.version or 1) + 1
        rp.profile_data = body.profile_data
    db.commit()
    db.refresh(rp)
    return _resume_profile_out(db, rp)


@router.post("/resume-profiles/{profile_id}/analyze", response_model=dict)
async def analyze_match(
    profile_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    import asyncio
    import functools

    rp = db.get(ResumeProfile, profile_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "profile not found")

    jd_row = db.get(JobDescription, rp.jd_id) if rp.jd_id else None
    if not jd_row:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Attach a JD: create a job description, then PATCH resume-profiles/{id} with jd_id.",
        )
    jd_raw = jd_row.raw_text
    try:
        jd_struct = resume_pipeline.ensure_valid_jd_struct(db, jd_row)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_jd", "message": str(exc) or "Invalid job description."},
        ) from exc

    profile = dict(rp.profile_data or {})
    resume_plain: str | None = None
    if rp.upload_id:
        ru = db.get(ResumeUpload, rp.upload_id)
        if ru and ru.user_id == user.id and ru.extracted_text:
            resume_plain = ru.extracted_text

    # Run the blocking Gemini call in a thread-pool executor so uvicorn's
    # async event loop is not blocked while the model generates its response
    # (which can take 60–120 s for this detailed prompt).
    loop = asyncio.get_event_loop()
    try:
        match, feedback = await loop.run_in_executor(
            None,
            functools.partial(
                resume_pipeline.unified_resume_analysis,
                profile,
                jd_raw,
                jd_struct,
                resume_plain,
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc) if str(exc) else "Resume analysis failed; try again later.",
        ) from exc

    rp.match_result = match
    rp.feedback = feedback
    db.commit()
    db.refresh(rp)
    out: dict[str, Any] = {
        "profile_id": str(rp.id),
        **match,
        "feedback": feedback,
    }
    return out


class RewriteBody(BaseModel):
    bullet_id: str
    extra_instruction: str | None = None


@router.post("/resume-profiles/{profile_id}/bullets/rewrite")
def rewrite_bullet(
    profile_id: uuid.UUID,
    body: RewriteBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    rp = db.get(ResumeProfile, profile_id)
    if not rp or rp.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "profile not found")
    pdata = dict(rp.profile_data or {})

    bullet_text_before = ""
    for ex in pdata.get("experience") or []:
        if not isinstance(ex, dict):
            continue
        for b in ex.get("bullets") or []:
            if isinstance(b, dict) and str(b.get("id")) == str(body.bullet_id):
                bullet_text_before = str(b.get("text", ""))
                break

    if not bullet_text_before:
        for pj in pdata.get("projects") or []:
            if not isinstance(pj, dict):
                continue
            for b in pj.get("bullets") or []:
                if isinstance(b, dict) and str(b.get("id")) == str(body.bullet_id):
                    bullet_text_before = str(b.get("text", ""))

    fb = dict(rp.feedback or {})
    da = fb.get("domain_alignment") if isinstance(fb.get("domain_alignment"), dict) else {}
    if not da or "domain_mismatch" not in da:
        jd_row = db.get(JobDescription, rp.jd_id) if rp.jd_id else None
        if jd_row and jd_row.user_id == user.id:
            try:
                jd_struct = resume_pipeline.ensure_valid_jd_struct(db, jd_row)
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail={"error": "invalid_jd", "message": str(exc) or "Invalid job description."},
                ) from exc
            da = resume_pipeline.analyze_domain_alignment(pdata, jd_row.raw_text or "", jd_struct)
    if da.get("domain_mismatch"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "Rewriting bullets is disabled when the résumé targets a different career domain than the "
                "attached job. Run analyze or adjust your JD, then align your experience before rewriting."
            ),
        )

    try:
        out = resume_pipeline.rewrite_bullet(bullet_text_before or " ", body.extra_instruction)
    except RuntimeError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "LLM unavailable")
    revised = str(out.get("revised_text", "")).strip()
    patch_bullet_by_id(pdata, body.bullet_id, revised)

    rp.version = (rp.version or 1) + 1
    rp.profile_data = pdata

    db.add(
        BulletRevision(
            profile_id=rp.id,
            section_path=body.bullet_id,
            previous_text=bullet_text_before or None,
            revised_text=revised,
        )
    )
    db.commit()
    db.refresh(rp)
    return {
        "bullet_id": body.bullet_id,
        "revised_text": revised,
        "rationale": out.get("rationale"),
        "profile_version": rp.version,
    }
