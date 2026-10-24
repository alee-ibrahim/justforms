"""S3 storage for any external S3-compatible service (AWS S3, Cloudflare R2, Ceph, Garage...).

Browsers upload with presigned POST (which can enforce a size range) and download through
short-lived presigned GET URLs, so file bytes do not pass through the API.

``public_endpoint_url`` (optional) is the address browsers use when it differs from the one the
backend talks to. Presigning is offline, so a second client signs URLs for that host while all
object operations keep using ``endpoint_url``.
"""

from collections.abc import AsyncIterator
from typing import Any, BinaryIO

import boto3
from anyio import to_thread
from botocore.config import Config
from botocore.exceptions import ClientError

from app.storage.base import (
    DEFAULT_CHUNK_SIZE,
    FileTooLargeError,
    ObjectInfo,
    ObjectNotFoundError,
    PresignedUpload,
    Storage,
    validate_key,
)

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


def _is_not_found(exc: ClientError) -> bool:
    return str(exc.response.get("Error", {}).get("Code")) in _NOT_FOUND_CODES


class _LimitedReader:
    """File-like wrapper that raises once more than ``max_bytes`` have been read."""

    def __init__(self, raw: BinaryIO, max_bytes: int) -> None:
        self._raw = raw
        self._max = max_bytes
        self.size = 0

    def read(self, n: int = -1) -> bytes:
        chunk = self._raw.read(n)
        self.size += len(chunk)
        if self.size > self._max:
            raise FileTooLargeError(f"Object exceeds {self._max} bytes")
        return chunk


class S3Storage(Storage):
    name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        public_endpoint_url: str | None = None,
        region: str | None = None,
        access_key_id: str = "",
        secret_access_key: str = "",
        addressing_style: str = "auto",
        client: Any = None,
    ) -> None:
        if not bucket:
            raise ValueError("JUSTFORMS_S3_BUCKET is required for the s3 storage backend")
        self.bucket = bucket

        def make_client(endpoint: str | None) -> Any:
            return boto3.client(
                "s3",
                endpoint_url=endpoint or None,
                region_name=region or None,
                aws_access_key_id=access_key_id or None,
                aws_secret_access_key=secret_access_key or None,
                config=Config(signature_version="s3v4", s3={"addressing_style": addressing_style}),
            )

        self.client = client or make_client(endpoint_url)
        # Signs the URLs handed to browsers; the same client unless a public endpoint is set.
        self.presign_client = (
            make_client(public_endpoint_url)
            if public_endpoint_url and public_endpoint_url != endpoint_url
            else self.client
        )

    @property
    def supports_presigned_urls(self) -> bool:
        return True

    async def put(
        self,
        key: str,
        data: bytes | BinaryIO,
        *,
        content_type: str | None = None,
        max_bytes: int | None = None,
    ) -> ObjectInfo:
        validate_key(key)
        extra = {"ContentType": content_type} if content_type else {}
        if isinstance(data, bytes | bytearray | memoryview):
            if max_bytes is not None and len(data) > max_bytes:
                raise FileTooLargeError(f"Object exceeds {max_bytes} bytes")
            await to_thread.run_sync(
                lambda: self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
            )
            return ObjectInfo(key=key, size=len(data))
        body: Any = data if max_bytes is None else _LimitedReader(data, max_bytes)
        await to_thread.run_sync(
            lambda: self.client.upload_fileobj(body, self.bucket, key, ExtraArgs=extra)
        )
        return await self.stat(key)

    async def stat(self, key: str) -> ObjectInfo:
        validate_key(key)
        try:
            res = await to_thread.run_sync(
                lambda: self.client.head_object(Bucket=self.bucket, Key=key)
            )
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFoundError(key) from exc
            raise
        return ObjectInfo(key=key, size=int(res["ContentLength"]))

    async def _get(self, key: str, length: int | None = None) -> Any:
        validate_key(key)
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if length is not None:
            kwargs["Range"] = f"bytes=0-{max(length, 1) - 1}"
        try:
            return await to_thread.run_sync(lambda: self.client.get_object(**kwargs))
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFoundError(key) from exc
            raise

    async def read(self, key: str, *, length: int | None = None) -> bytes:
        res = await self._get(key, length)
        data: bytes = await to_thread.run_sync(res["Body"].read)
        return data if length is None else data[:length]

    async def iter_chunks(
        self, key: str, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        res = await self._get(key)
        body = res["Body"]
        try:
            while chunk := await to_thread.run_sync(body.read, chunk_size):
                yield chunk
        finally:
            await to_thread.run_sync(body.close)

    async def copy(self, src_key: str, dst_key: str) -> None:
        validate_key(src_key)
        validate_key(dst_key)
        try:
            await to_thread.run_sync(
                lambda: self.client.copy_object(
                    Bucket=self.bucket,
                    Key=dst_key,
                    CopySource={"Bucket": self.bucket, "Key": src_key},
                )
            )
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFoundError(src_key) from exc
            raise

    async def delete(self, key: str) -> None:
        validate_key(key)
        await to_thread.run_sync(lambda: self.client.delete_object(Bucket=self.bucket, Key=key))

    async def presign_upload(
        self,
        key: str,
        *,
        content_type: str,
        max_bytes: int,
        expires_in: int = 900,
    ) -> PresignedUpload:
        validate_key(key)
        res = await to_thread.run_sync(
            lambda: self.presign_client.generate_presigned_post(
                Bucket=self.bucket,
                Key=key,
                Fields={"Content-Type": content_type},
                Conditions=[
                    {"Content-Type": content_type},
                    ["content-length-range", 1, max_bytes],
                ],
                ExpiresIn=expires_in,
            )
        )
        return PresignedUpload(url=res["url"], fields=dict(res["fields"]))

    async def presign_download(
        self,
        key: str,
        *,
        filename: str | None = None,
        expires_in: int = 300,
    ) -> str:
        validate_key(key)
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if filename:
            safe = filename.replace('"', "").replace("\\", "")
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
        return await to_thread.run_sync(
            lambda: self.presign_client.generate_presigned_url(
                "get_object", Params=params, ExpiresIn=expires_in
            )
        )
