"""Upload storage: local filesystem or GCS when configured."""

import uuid
from pathlib import Path

from fastapi import UploadFile

from ai_interview_analysis.core.settings import get_settings


def _local_dir() -> Path:
    s = get_settings()
    d = Path(s.local_upload_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_resume_file(user_id: uuid.UUID, upload: UploadFile) -> tuple[str, str]:
    """Return (storage_key, absolute_path_for_reading)."""
    settings = get_settings()
    ext = Path(upload.filename or "resume").suffix[:16] or ".bin"
    key = f"{user_id}/{uuid.uuid4()}{ext}"
    if settings.storage_backend == "gcs" and settings.gcs_bucket_uploads:
        return _save_gcs(key, upload)
    base = _local_dir() / str(user_id)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{uuid.uuid4()}{ext}"
    data = upload.file.read()
    path.write_bytes(data)
    return str(path), str(path)


def _save_gcs(key: str, upload: UploadFile) -> tuple[str, str]:
    from google.cloud import storage

    settings = get_settings()
    assert settings.gcs_bucket_uploads
    client = storage.Client(project=settings.gcp_project_id)
    bucket = client.bucket(settings.gcs_bucket_uploads)
    blob = bucket.blob(key)
    upload.file.seek(0)
    blob.upload_from_file(upload.file, content_type=upload.content_type)
    return key, f"gcs://{settings.gcs_bucket_uploads}/{key}"


def read_bytes(storage_key: str) -> bytes:
    """Read file from local path or GCS key."""
    settings = get_settings()
    if settings.storage_backend == "gcs" and not storage_key.startswith("/") and not storage_key.startswith("\\\\"):
        from google.cloud import storage

        assert settings.gcs_bucket_uploads
        client = storage.Client(project=settings.gcp_project_id)
        bucket = client.bucket(settings.gcs_bucket_uploads)
        return bucket.blob(storage_key).download_as_bytes()
    return Path(storage_key).read_bytes()
