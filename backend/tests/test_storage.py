import io
from pathlib import Path

import pytest

from app.config import Settings
from app.storage import (
    FileTooLargeError,
    InvalidKeyError,
    LocalStorage,
    ObjectNotFoundError,
    build_storage,
    validate_key,
)


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


def _leftovers(root: Path) -> list[Path]:
    """Temp files that a failed or completed write must not leave behind."""
    return [p for p in root.rglob(".tmp-*")] if root.exists() else []


async def test_put_bytes_and_read_back(storage: LocalStorage) -> None:
    info = await storage.put("tmp/form1/file1", b"hello world", content_type="text/plain")
    assert info.key == "tmp/form1/file1"
    assert info.size == 11
    assert (storage.root / "tmp" / "form1" / "file1").read_bytes() == b"hello world"
    assert await storage.read("tmp/form1/file1") == b"hello world"
    assert await storage.read("tmp/form1/file1", length=5) == b"hello"
    assert (await storage.stat("tmp/form1/file1")).size == 11
    assert await storage.exists("tmp/form1/file1")


async def test_put_file_object_streams_in_chunks(storage: LocalStorage) -> None:
    payload = b"x" * (3 * 1024 * 1024 + 7)
    info = await storage.put("exports/big.xlsx", io.BytesIO(payload))
    assert info.size == len(payload)
    chunks = [c async for c in storage.iter_chunks("exports/big.xlsx", chunk_size=1024 * 1024)]
    assert len(chunks) == 4
    assert b"".join(chunks) == payload


async def test_put_overwrites_existing(storage: LocalStorage) -> None:
    await storage.put("a/b", b"one")
    await storage.put("a/b", b"two!")
    assert await storage.read("a/b") == b"two!"


@pytest.mark.parametrize("as_stream", [False, True])
async def test_max_bytes_rejects_and_leaves_nothing(storage: LocalStorage, as_stream: bool) -> None:
    data = b"0123456789"
    with pytest.raises(FileTooLargeError):
        await storage.put("tmp/f/too-big", io.BytesIO(data) if as_stream else data, max_bytes=9)
    assert not await storage.exists("tmp/f/too-big")
    assert _leftovers(storage.root) == []


async def test_max_bytes_allows_exact_size(storage: LocalStorage) -> None:
    info = await storage.put("tmp/f/exact", io.BytesIO(b"0123456789"), max_bytes=10)
    assert info.size == 10


async def test_failed_overwrite_keeps_previous_object(storage: LocalStorage) -> None:
    await storage.put("files/x", b"original")
    with pytest.raises(FileTooLargeError):
        await storage.put("files/x", b"much too large", max_bytes=8)
    assert await storage.read("files/x") == b"original"


async def test_copy_move_delete(storage: LocalStorage) -> None:
    await storage.put("tmp/form/f1", b"data")

    await storage.copy("tmp/form/f1", "files/org/form/sub/f1-copy")
    assert await storage.read("files/org/form/sub/f1-copy") == b"data"
    assert await storage.exists("tmp/form/f1")

    await storage.move("tmp/form/f1", "files/org/form/sub/f1")
    assert await storage.read("files/org/form/sub/f1") == b"data"
    assert not await storage.exists("tmp/form/f1")

    await storage.delete("files/org/form/sub/f1")
    assert not await storage.exists("files/org/form/sub/f1")
    # Deleting a missing object is a no-op.
    await storage.delete("files/org/form/sub/f1")
    assert _leftovers(storage.root) == []


async def test_missing_objects_raise_not_found(storage: LocalStorage) -> None:
    with pytest.raises(ObjectNotFoundError):
        await storage.stat("nope")
    with pytest.raises(ObjectNotFoundError):
        await storage.read("nope")
    with pytest.raises(ObjectNotFoundError):
        await storage.copy("nope", "other")
    with pytest.raises(ObjectNotFoundError):
        await storage.move("nope", "other")
    with pytest.raises(ObjectNotFoundError):
        [c async for c in storage.iter_chunks("nope")]
    assert not await storage.exists("nope")


async def test_directory_is_not_an_object(storage: LocalStorage) -> None:
    await storage.put("dir/file", b"x")
    assert not await storage.exists("dir")
    with pytest.raises(ObjectNotFoundError):
        await storage.read("dir")


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/etc/passwd",
        "../escape",
        "a/../../escape",
        "a/./b",
        "a//b",
        "a/",
        ".hidden",
        "a\\b",
        "C:/windows",
        "a/b c",
        "x" * 1025,
    ],
)
async def test_unsafe_keys_are_rejected(storage: LocalStorage, key: str) -> None:
    with pytest.raises(InvalidKeyError):
        validate_key(key)
    with pytest.raises(InvalidKeyError):
        await storage.put(key, b"x")
    with pytest.raises(InvalidKeyError):
        await storage.read(key)
    assert not storage.root.exists() or not any(storage.root.rglob("*"))


async def test_presigned_urls_are_not_supported(storage: LocalStorage) -> None:
    assert storage.supports_presigned_urls is False
    assert await storage.presign_upload("k", content_type="image/png", max_bytes=10) is None
    assert await storage.presign_download("k", filename="a.png") is None


def test_build_storage_defaults_to_local(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, storage_local_path=tmp_path / "files")
    assert settings.storage_backend == "local"
    storage = build_storage(settings)
    assert isinstance(storage, LocalStorage)
    assert storage.root == (tmp_path / "files").resolve()


def test_build_storage_s3_requires_bucket() -> None:
    settings = Settings(_env_file=None, storage_backend="s3", s3_bucket="")
    with pytest.raises(ValueError, match="JUSTFORMS_S3_BUCKET"):
        build_storage(settings)


def test_build_storage_s3() -> None:
    from app.storage.s3 import S3Storage

    settings = Settings(
        _env_file=None,
        storage_backend="s3",
        s3_bucket="justforms",
        s3_endpoint_url="https://s3.example.org",
        s3_access_key_id="test",
        s3_secret_access_key="test",
        s3_addressing_style="path",
    )
    storage = build_storage(settings)
    assert isinstance(storage, S3Storage)
    assert storage.supports_presigned_urls is True
    assert storage.bucket == "justforms"


async def test_s3_presigned_urls_are_generated_offline() -> None:
    from app.storage.s3 import S3Storage

    storage = S3Storage(
        bucket="justforms",
        endpoint_url="https://s3.example.org",
        region="us-east-1",
        access_key_id="test",
        secret_access_key="test",
        addressing_style="path",
    )
    upload = await storage.presign_upload("tmp/f/1", content_type="image/png", max_bytes=1024)
    assert upload is not None
    assert upload.url == "https://s3.example.org/justforms"
    assert upload.fields["key"] == "tmp/f/1"
    assert upload.fields["Content-Type"] == "image/png"
    assert "policy" in upload.fields

    url = await storage.presign_download("files/a/b", filename='re"port.pdf')
    assert url is not None
    assert url.startswith("https://s3.example.org/justforms/files/a/b?")
    assert "X-Amz-Signature=" in url
    assert "attachment" in url


async def test_s3_public_endpoint_signs_browser_urls_only() -> None:
    from app.storage.s3 import S3Storage

    settings = Settings(
        _env_file=None,
        storage_backend="s3",
        s3_bucket="justforms",
        s3_endpoint_url="http://objects.internal:9000",
        s3_public_endpoint_url="https://files.example.org",
        s3_access_key_id="test",
        s3_secret_access_key="test",
        s3_addressing_style="path",
    )
    storage = build_storage(settings)
    assert isinstance(storage, S3Storage)
    # Object operations stay on the internal endpoint ...
    assert storage.client.meta.endpoint_url == "http://objects.internal:9000"
    # ... while browsers get URLs for the public one.
    upload = await storage.presign_upload("tmp/f/1", content_type="image/png", max_bytes=1024)
    assert upload is not None
    assert upload.url == "https://files.example.org/justforms"
    url = await storage.presign_download("files/a/b")
    assert url is not None
    assert url.startswith("https://files.example.org/justforms/files/a/b?")


def test_s3_without_public_endpoint_uses_one_client() -> None:
    from app.storage.s3 import S3Storage

    storage = S3Storage(
        bucket="justforms",
        endpoint_url="https://s3.example.org",
        access_key_id="test",
        secret_access_key="test",
    )
    assert storage.presign_client is storage.client
