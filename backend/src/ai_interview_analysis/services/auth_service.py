"""Password hashing and JWT issuance."""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_interview_analysis.core.settings import get_settings
from ai_interview_analysis.db.models import User

settings = get_settings()


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _token(subject: str, minutes: int | None = None, days: int | None = None) -> str:
    now = datetime.now(UTC)
    if minutes is not None:
        exp = now + timedelta(minutes=minutes)
        typ = "access"
    elif days is not None:
        exp = now + timedelta(days=days)
        typ = "refresh"
    else:
        raise ValueError("Either minutes or days required")
    payload = {"sub": subject, "exp": exp, "type": typ}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID) -> str:
    return _token(str(user_id), minutes=settings.access_token_expire_minutes)


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _token(str(user_id), days=settings.refresh_token_expire_days)


def decode_token(token: str, expect: str | None = None) -> str:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise JWTError("missing sub")
    if expect and payload.get("type") != expect:
        raise JWTError("wrong token type")
    return sub


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email.lower().strip())).scalar_one_or_none()


def create_user(db: Session, email: str, password: str) -> User:
    user = User(email=email.lower().strip(), hashed_password=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)
