import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_interview_analysis.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResumeUpload(Base):
    __tablename__ = "resume_uploads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(1024))  # local path or GCS object path
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_notes: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    role_hint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    jd_embedding_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    extracted_keywords: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResumeProfile(Base):
    __tablename__ = "resume_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    upload_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("resume_uploads.id"), nullable=True)
    jd_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("job_descriptions.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    profile_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    match_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    feedback: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    bullet_revisions = relationship("BulletRevision", back_populates="profile", cascade="all, delete-orphan")


class BulletRevision(Base):
    __tablename__ = "bullet_revisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("resume_profiles.id"))
    section_path: Mapped[str] = mapped_column(String(512))
    previous_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    revised_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    profile = relationship("ResumeProfile", back_populates="bullet_revisions")


class InterviewPhase(str, enum.Enum):
    opening = "opening"
    main = "main"
    closing = "closing"
    ended = "ended"


class MockInterviewSession(Base):
    __tablename__ = "mock_interview_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    jd_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("job_descriptions.id"), nullable=True)
    resume_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("resume_profiles.id"))
    resume_entity: Mapped["ResumeProfile | None"] = relationship("ResumeProfile", foreign_keys=[resume_profile_id])
    role: Mapped[str] = mapped_column(String(255), default="General")
    level: Mapped[str] = mapped_column(String(64), default="mid")  # fresher/mid/senior
    interview_type: Mapped[str] = mapped_column(String(64), default="behavioral")

    phase: Mapped[str] = mapped_column(String(32), default=InterviewPhase.main.value)
    session_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    outline: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    topic_index: Mapped[int] = mapped_column(Integer, default=0)
    followups_in_topic: Mapped[int] = mapped_column(Integer, default=0)
    max_followups_per_topic: Mapped[int] = mapped_column(Integer, default=2)

    final_report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    turns = relationship(
        "MockTurn",
        back_populates="session",
        order_by="MockTurn.turn_index",
        cascade="all, delete-orphan",
    )


class MockTurn(Base):
    __tablename__ = "mock_turns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mock_interview_sessions.id"), index=True)
    turn_index: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(16))  # assistant | user
    content: Mapped[str] = mapped_column(Text)
    modality: Mapped[str | None] = mapped_column(String(32), nullable=True)  # text | voice
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session = relationship("MockInterviewSession", back_populates="turns")
