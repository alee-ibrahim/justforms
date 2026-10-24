"""File storage: a small backend abstraction over a local directory or S3.

``local`` (default) keeps files on a mounted volume/PVC and needs no extra services; the API
receives uploads and streams downloads itself. ``s3`` targets any external S3-compatible
service; browsers upload and download directly through presigned URLs.

Use :func:`get_storage` to obtain the configured backend.
"""

from functools import lru_cache

from app.config import Settings, get_settings
from app.storage.base import (
    FileTooLargeError,
    InvalidKeyError,
    ObjectInfo,
    ObjectNotFoundError,
    PresignedUpload,
    Storage,
    StorageError,
    validate_key,
)
from app.storage.local import LocalStorage

__all__ = [
    "FileTooLargeError",
    "InvalidKeyError",
    "LocalStorage",
    "ObjectInfo",
    "ObjectNotFoundError",
    "PresignedUpload",
    "Storage",
    "StorageError",
    "build_storage",
    "get_storage",
    "validate_key",
]


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "local":
        return LocalStorage(settings.storage_local_path)
    if settings.storage_backend == "s3":
        # Imported lazily so the local backend never loads boto3.
        from app.storage.s3 import S3Storage

        return S3Storage(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            addressing_style=settings.s3_addressing_style,
        )
    raise ValueError(f"Unknown storage backend: {settings.storage_backend!r}")


@lru_cache
def get_storage() -> Storage:
    return build_storage(get_settings())
