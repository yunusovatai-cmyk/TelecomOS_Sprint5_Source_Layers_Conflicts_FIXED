from __future__ import annotations

import hashlib
import io
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from minio import Minio
from minio.error import S3Error

from app.core.config import settings


PDF_MIME_TYPE = "application/pdf"
SAFE_KEY_RE = re.compile(r"^[a-z0-9/_-]+\.[a-z0-9]+$")


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    object_key: str
    sha256: str
    size_bytes: int
    mime_type: str


def minio_client() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_private_bucket(client: Minio | None = None) -> None:
    client = client or minio_client()
    bucket = settings.pdf_storage_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    # Explicitly remove any anonymous policy left by an operator or old setup.
    try:
        client.delete_bucket_policy(bucket)
    except S3Error as exc:
        if exc.code not in {"NoSuchBucketPolicy", "NoSuchPolicy"}:
            raise


def document_object_key(project_id: uuid.UUID, document_id: uuid.UUID, digest: str) -> str:
    return f"projects/{project_id.hex}/documents/{document_id.hex}/{digest}.pdf"


def rendered_page_object_key(project_id: uuid.UUID, document_id: uuid.UUID, page_number: int) -> str:
    return f"projects/{project_id.hex}/rendered/{document_id.hex}/{page_number}.png"


def _validate_generated_key(key: str) -> None:
    if ".." in key or key.startswith("/") or not SAFE_KEY_RE.fullmatch(key):
        raise ValueError("Unsafe object key.")


def put_pdf(
    *, project_id: uuid.UUID, document_id: uuid.UUID, content: bytes, expected_sha256: str | None = None,
    client: Minio | None = None,
) -> StoredObject:
    if not content.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF signature.")
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("PDF SHA-256 mismatch.")
    key = document_object_key(project_id, document_id, digest)
    _validate_generated_key(key)
    client = client or minio_client()
    ensure_private_bucket(client)
    client.put_object(
        settings.pdf_storage_bucket,
        key,
        io.BytesIO(content),
        length=len(content),
        content_type=PDF_MIME_TYPE,
        metadata={"sha256": digest},
    )
    return StoredObject(settings.pdf_storage_bucket, key, digest, len(content), PDF_MIME_TYPE)


def put_rendered_page(
    *, project_id: uuid.UUID, document_id: uuid.UUID, page_number: int, content: bytes,
    client: Minio | None = None,
) -> StoredObject:
    key = rendered_page_object_key(project_id, document_id, page_number)
    _validate_generated_key(key)
    digest = hashlib.sha256(content).hexdigest()
    client = client or minio_client()
    ensure_private_bucket(client)
    client.put_object(
        settings.pdf_storage_bucket, key, io.BytesIO(content), length=len(content), content_type="image/png",
        metadata={"sha256": digest},
    )
    return StoredObject(settings.pdf_storage_bucket, key, digest, len(content), "image/png")


def get_object(bucket: str, object_key: str, *, client: Minio | None = None) -> bytes:
    _validate_generated_key(object_key)
    response = (client or minio_client()).get_object(bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def remove_object(bucket: str, object_key: str, *, client: Minio | None = None) -> None:
    _validate_generated_key(object_key)
    (client or minio_client()).remove_object(bucket, object_key)


def presigned_get(bucket: str, object_key: str, *, client: Minio | None = None) -> str:
    _validate_generated_key(object_key)
    ttl = max(30, min(settings.pdf_presigned_ttl_seconds, 900))
    return (client or minio_client()).presigned_get_object(bucket, object_key, expires=timedelta(seconds=ttl))


def cleanup_orphan_objects(
    referenced: set[tuple[str, str]], *, grace_seconds: int = 3600, apply: bool = False,
    client: Minio | None = None,
) -> list[str]:
    """Find old unreferenced managed objects and optionally remove them.

    The grace period prevents racing an upload that has reached MinIO but whose
    database transaction has not committed yet. Dry-run is the default.
    """
    client = client or minio_client()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(60, grace_seconds))
    orphans: list[str] = []
    for item in client.list_objects(settings.pdf_storage_bucket, prefix="projects/", recursive=True):
        if (settings.pdf_storage_bucket, item.object_name) in referenced:
            continue
        modified = item.last_modified
        if modified.tzinfo is None:
            modified = modified.replace(tzinfo=timezone.utc)
        if modified > cutoff:
            continue
        _validate_generated_key(item.object_name)
        orphans.append(item.object_name)
        if apply:
            client.remove_object(settings.pdf_storage_bucket, item.object_name)
    return orphans
