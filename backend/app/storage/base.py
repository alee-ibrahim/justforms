"""Storage interface shared by the local and S3 backends."""

import re
import tempfile
from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass, field
from typing import BinaryIO

DEFAULT_CHUNK_SIZE = 1024 * 1024

# Keys are relative, slash-separated paths such as "tmp/<form_id>/<file_id>".
_KEY_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StorageError(Exception):
    """Base class for storage errors."""


class InvalidKeyError(StorageError, ValueError):
    """The object key is empty, absolute, or tries to escape the storage root."""


class ObjectNotFoundError(StorageError, FileNotFoundError):
    """No object exists under the given key."""


class FileTooLargeError(StorageError):
    """The data written exceeds the allowed maximum size."""


def validate_key(key: str) -> str:
    """Return ``key`` if it is a safe relative object key, else raise :class:`InvalidKeyError`.

    Each ``/``-separated segment must start with an alphanumeric character and contain only
    ``A-Z a-z 0-9 . _ -``. This rules out absolute paths, ``..``, backslashes, drive letters
    and hidden files on every backend.
    """
    if not key or len(key) > 1024:
        raise InvalidKeyError("Object key must be 1-1024 characters")
    for segment in key.split("/"):
        if not _KEY_SEGMENT.match(segment):
            raise InvalidKeyError(f"Invalid object key: {key!r}")
    return key


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int


@dataclass(frozen=True)
class PresignedUpload:
    """A browser upload target: POST multipart ``fields`` plus the file to ``url``."""

    url: str
    fields: dict[str, str] = field(default_factory=dict)


class Storage(ABC):
    """Async object storage.

    ``presign_upload``/``presign_download`` return ``None`` when the backend cannot hand out
    direct URLs (``local``). Callers then accept the upload body in the API and stream
    downloads through :meth:`iter_chunks`.
    """

    name: str

    @property
    def supports_presigned_urls(self) -> bool:
        return False

    @abstractmethod
    async def put(
        self,
        key: str,
        data: bytes | BinaryIO,
        *,
        content_type: str | None = None,
        max_bytes: int | None = None,
    ) -> ObjectInfo:
        """Store ``data`` under ``key``, replacing any existing object.

        Raises :class:`FileTooLargeError` (and stores nothing) if ``max_bytes`` is exceeded.
        """

    async def put_stream(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        *,
        content_type: str | None = None,
        max_bytes: int,
    ) -> ObjectInfo:
        """Store an async byte stream, stopping with :class:`FileTooLargeError` as soon as
        more than ``max_bytes`` arrive. Nothing is stored when the limit is exceeded."""
        size = 0
        with tempfile.SpooledTemporaryFile(max_size=DEFAULT_CHUNK_SIZE) as spool:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise FileTooLargeError(f"Object exceeds {max_bytes} bytes")
                spool.write(chunk)
            spool.seek(0)
            return await self.put(key, spool, content_type=content_type, max_bytes=max_bytes)  # type: ignore[arg-type]

    @abstractmethod
    async def stat(self, key: str) -> ObjectInfo:
        """Return metadata for ``key`` or raise :class:`ObjectNotFoundError`."""

    async def exists(self, key: str) -> bool:
        try:
            await self.stat(key)
        except ObjectNotFoundError:
            return False
        return True

    @abstractmethod
    async def read(self, key: str, *, length: int | None = None) -> bytes:
        """Return the object's bytes, or only the first ``length`` bytes (for sniffing)."""

    @abstractmethod
    def iter_chunks(self, key: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> AsyncIterator[bytes]:
        """Stream the object in chunks. Raises :class:`ObjectNotFoundError` on first use."""

    @abstractmethod
    async def copy(self, src_key: str, dst_key: str) -> None:
        """Copy an object to a new key."""

    async def move(self, src_key: str, dst_key: str) -> None:
        await self.copy(src_key, dst_key)
        await self.delete(src_key)

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete ``key``. Deleting a missing object is not an error."""

    async def presign_upload(
        self,
        key: str,
        *,
        content_type: str,
        max_bytes: int,
        expires_in: int = 900,
    ) -> PresignedUpload | None:
        """Direct browser upload target, or ``None`` if uploads must go through the API."""
        return None

    async def presign_download(
        self,
        key: str,
        *,
        filename: str | None = None,
        expires_in: int = 300,
    ) -> str | None:
        """Short-lived download URL, or ``None`` if the API must stream the file."""
        return None
