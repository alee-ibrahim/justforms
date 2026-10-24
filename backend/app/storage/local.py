"""Local filesystem storage: files live under a root directory on a mounted volume/PVC."""

import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import BinaryIO

from anyio import to_thread

from app.storage.base import (
    DEFAULT_CHUNK_SIZE,
    FileTooLargeError,
    InvalidKeyError,
    ObjectInfo,
    ObjectNotFoundError,
    Storage,
    validate_key,
)


class LocalStorage(Storage):
    name = "local"

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()

    def path_for(self, key: str) -> Path:
        """Absolute path of ``key`` inside the root. Never resolves outside it."""
        validate_key(key)
        path = (self.root / key).resolve()
        if path == self.root or not path.is_relative_to(self.root):
            raise InvalidKeyError(f"Invalid object key: {key!r}")
        return path

    @staticmethod
    def _atomic_write(dst: Path, write: Callable[[BinaryIO], None]) -> None:
        """Write via a temp file in the target directory, then rename into place.

        Readers never see a partial object, and a failed write leaves nothing behind.
        """
        dst.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=dst.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as out:
                write(out)
            os.replace(tmp_name, dst)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    # -- writes -----------------------------------------------------------------

    def _put_sync(self, key: str, data: bytes | BinaryIO, max_bytes: int | None) -> ObjectInfo:
        path = self.path_for(key)
        size = 0

        def write(out: BinaryIO) -> None:
            nonlocal size
            if isinstance(data, bytes | bytearray | memoryview):
                size = len(data)
                if max_bytes is not None and size > max_bytes:
                    raise FileTooLargeError(f"Object exceeds {max_bytes} bytes")
                out.write(data)
                return
            while chunk := data.read(DEFAULT_CHUNK_SIZE):
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise FileTooLargeError(f"Object exceeds {max_bytes} bytes")
                out.write(chunk)

        self._atomic_write(path, write)
        return ObjectInfo(key=key, size=size)

    async def put(
        self,
        key: str,
        data: bytes | BinaryIO,
        *,
        content_type: str | None = None,
        max_bytes: int | None = None,
    ) -> ObjectInfo:
        return await to_thread.run_sync(self._put_sync, key, data, max_bytes)

    def _copy_sync(self, src_key: str, dst_key: str) -> None:
        src = self.path_for(src_key)
        dst = self.path_for(dst_key)
        if not src.is_file():
            raise ObjectNotFoundError(src_key)

        def write(out: BinaryIO) -> None:
            with src.open("rb") as f:
                shutil.copyfileobj(f, out, DEFAULT_CHUNK_SIZE)

        self._atomic_write(dst, write)

    async def copy(self, src_key: str, dst_key: str) -> None:
        await to_thread.run_sync(self._copy_sync, src_key, dst_key)

    def _move_sync(self, src_key: str, dst_key: str) -> None:
        src = self.path_for(src_key)
        dst = self.path_for(dst_key)
        if not src.is_file():
            raise ObjectNotFoundError(src_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)

    async def move(self, src_key: str, dst_key: str) -> None:
        await to_thread.run_sync(self._move_sync, src_key, dst_key)

    def _delete_sync(self, key: str) -> None:
        self.path_for(key).unlink(missing_ok=True)

    async def delete(self, key: str) -> None:
        await to_thread.run_sync(self._delete_sync, key)

    # -- reads ------------------------------------------------------------------

    def _stat_sync(self, key: str) -> ObjectInfo:
        path = self.path_for(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        return ObjectInfo(key=key, size=path.stat().st_size)

    async def stat(self, key: str) -> ObjectInfo:
        return await to_thread.run_sync(self._stat_sync, key)

    def _read_sync(self, key: str, length: int | None) -> bytes:
        path = self.path_for(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        with path.open("rb") as f:
            return f.read() if length is None else f.read(length)

    async def read(self, key: str, *, length: int | None = None) -> bytes:
        return await to_thread.run_sync(self._read_sync, key, length)

    async def iter_chunks(
        self, key: str, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        path = self.path_for(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        f = await to_thread.run_sync(path.open, "rb")
        try:
            while chunk := await to_thread.run_sync(f.read, chunk_size):
                yield chunk
        finally:
            await to_thread.run_sync(f.close)
