"""File uploads end to end on both storage backends (DESIGN 10, Phase 3 acceptance)."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import pytest
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import FileRecord, FileState, FormPermission, FormRole, User
from app.storage import Storage
from app.storage.s3 import S3Storage
from app.uploads import service as uploads
from app.uploads import sniff
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import Published, admin_client, field, publish

PDF = b"%PDF-1.7\n" + b"0" * 2000
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200

ID_COPY = field(
    "id_copy", "file", required=True, accept=[".pdf", "image/*"], maxFiles=2, maxSizeMb=1
)
NAME = field("name")


# -- sniffing (no database) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "name", "mime", "accept", "expected"),
    [
        (PDF, "id.pdf", "application/pdf", [".pdf"], "application/pdf"),
        (PNG, "photo.png", "image/png", ["image/*"], "image/png"),
        (PNG, "id.pdf", "application/pdf", [".pdf"], None),  # disguised as a PDF
        (PDF, "id.png", "image/png", ["image/*"], None),
        (b"MZ\x90\x00binary\x00", "run.pdf", "application/pdf", [".pdf"], None),
        (b"MZ\x90\x00binary\x00", "data.bin", "", [], "application/octet-stream"),
        (b"name,age\nAisha,19\n", "list.csv", "text/csv", [".csv"], "text/csv"),
        (b"name,age\n", "list.csv", "text/csv", [".pdf"], None),
        (b"<svg onload=alert(1)>", "x.txt", "text/plain", [".txt"], None),
        (b"PK\x03\x04rest", "cv.docx", "", [".docx"], "application/zip"),
        (
            b"PK\x03\x04rest",
            "cv.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            [".pdf", ".docx"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (b"\xff\xd8\xff\xe0JFIF", "scan.JPG", "image/jpeg", [".jpg", ".png"], "image/jpeg"),
    ],
)
def test_checked_type(
    head: bytes, name: str, mime: str, accept: list[str], expected: str | None
) -> None:
    assert sniff.checked_type(head, name, mime, accept) == expected


def test_accepts_by_extension_and_type() -> None:
    assert sniff.accepts([], "x.exe", "application/x-msdownload")
    assert sniff.accepts([".PDF"], "A.pdf", "")
    assert sniff.accepts(["image/*"], "a", "image/heic")
    assert not sniff.accepts(["image/*"], "a.pdf", "application/pdf")


def test_clean_name_strips_paths() -> None:
    assert uploads.clean_name("C:\\Users\\me\\..\\id card.pdf") == "id card.pdf"
    assert uploads.clean_name("../../etc/passwd") == "passwd"
    assert uploads.clean_name("\x00\x07") == "file"


def test_upload_token_round_trip(settings: Settings) -> None:
    fid = uuid.uuid4()
    token = uploads.upload_token(settings, fid)
    assert uploads.check_upload_token(settings, fid, token)
    assert not uploads.check_upload_token(settings, uuid.uuid4(), token)
    expired = uploads.upload_token(settings, fid, now=time.time() - 10_000)
    assert not uploads.check_upload_token(settings, fid, expired)
    assert not uploads.check_upload_token(settings, fid, "garbage")


# -- local backend through the API -----------------------------------------------------------


async def _start(
    client: AsyncClient, pub: Published, body: bytes, name: str, mime: str, **extra: Any
) -> Any:
    return await client.post(
        f"{pub.base}/uploads",
        json={
            "fieldId": "id_copy",
            "name": name,
            "size": len(body),
            "mime": mime,
            "uploadNonce": pub.live["uploadNonce"],
            **extra,
        },
    )


async def upload_local(
    client: AsyncClient,
    pub: Published,
    body: bytes,
    name: str = "id.pdf",
    mime: str = "application/pdf",
) -> dict[str, Any]:
    res = await _start(client, pub, body, name, mime)
    assert res.status_code == 201, res.text
    target = res.json()
    assert target["method"] == "PUT" and target["url"].startswith("/api/v1/public/uploads/")
    res = await client.put(target["url"], content=body, headers=target["headers"])
    assert res.status_code == 200, res.text
    return dict(res.json())


async def test_required_file_question_end_to_end(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [NAME, ID_COPY])
    assert pub.live["uploadNonce"] and pub.live["maxUploadMb"] == settings.max_upload_mb

    # Required file missing -> 422.
    res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"name": "A"}))
    assert res.status_code == 422
    assert {"field": "id_copy", "code": "required"} in res.json()["errors"]

    ref = await upload_local(client, pub, PDF)
    assert ref["size"] == len(PDF) and ref["mime"] == "application/pdf"
    rec = await db.get(FileRecord, uuid.UUID(ref["fileId"]))
    assert rec is not None and rec.state == FileState.PENDING
    assert rec.storage_key.startswith("tmp/")

    # The client's own metadata is replaced by the server's.
    sent = {**ref, "name": "evil.exe", "size": 1}
    res = await client.post(
        f"{pub.base}/submissions", json=pub.submit_body({"name": "A", "id_copy": [sent]})
    )
    assert res.status_code == 201, res.text

    await db.refresh(rec)
    assert rec.state == FileState.ATTACHED and rec.submission_id is not None
    assert rec.storage_key == f"files/{rec.org_id}/{rec.form_id}/{rec.submission_id}/{rec.id}"
    assert rec.sha256 is not None and len(rec.sha256) == 64
    assert not await file_storage.exists(f"tmp/{rec.form_id}/{rec.id}")
    assert await file_storage.read(rec.storage_key) == PDF

    sub = (await client.get(f"/api/v1/forms/{pub.id}/submissions")).json()["items"][0]
    assert sub["data"]["id_copy"] == [
        {"fileId": ref["fileId"], "name": "id.pdf", "size": len(PDF), "mime": "application/pdf"}
    ]

    # The owner downloads it as an attachment.
    res = await client.get(f"/api/v1/files/{ref['fileId']}")
    assert res.status_code == 200 and res.content == PDF
    assert res.headers["content-disposition"].startswith("attachment;")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["content-type"] == "application/octet-stream"

    # An attached file cannot be reused by another submission.
    res = await client.post(
        f"{pub.base}/submissions", json=pub.submit_body({"name": "B", "id_copy": [ref]})
    )
    assert res.status_code == 422
    assert res.json()["errors"] == [{"field": "id_copy", "code": "file_missing"}]


async def test_size_and_type_limits_at_upload(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [ID_COPY])
    mb = 1024 * 1024

    # Declared too large, wrong type, unknown question, empty.
    res = await _start(client, pub, b"x" * (mb + 1), "big.pdf", "application/pdf")
    assert res.status_code == 413 and res.json()["detail"] == "file_too_large"
    res = await _start(client, pub, b"x", "notes.txt", "text/plain")
    assert res.status_code == 422 and res.json()["detail"] == "file_type"
    res = await _start(client, pub, b"x", "a.pdf", "application/pdf", fieldId="nope")
    assert res.status_code == 422 and res.json()["detail"] == "unknown_field"
    res = await _start(client, pub, b"", "a.pdf", "application/pdf")
    assert res.status_code == 422 and res.json()["detail"] == "file_empty"

    # The streamed body is counted: going past the limit fails with 413 and keeps nothing.
    res = await _start(client, pub, b"x" * 10, "small.pdf", "application/pdf")
    target = res.json()
    res = await client.put(target["url"], content=b"%PDF-" + b"x" * mb, headers=target["headers"])
    assert res.status_code == 413
    rec = await db.get(FileRecord, uuid.UUID(target["fileId"]))
    assert rec is not None and not await file_storage.exists(rec.storage_key)

    # Same with a chunked body (no Content-Length): the stream itself is cut off.
    async def chunks() -> Any:
        for _ in range(5):
            yield b"x" * (256 * 1024)

    res = await client.put(target["url"], content=chunks(), headers=target["headers"])
    assert res.status_code == 413
    assert not await file_storage.exists(rec.storage_key)

    # Without a valid token nothing is accepted; a finished upload can't be overwritten.
    res = await _start(client, pub, PDF, "id.pdf", "application/pdf")
    target = res.json()
    bad = await client.put(target["url"], content=PDF, headers={"X-Upload-Token": "1.abc"})
    assert bad.status_code == 403
    assert (await client.put(target["url"], content=PDF, headers=target["headers"])).is_success
    again = await client.put(target["url"], content=PNG, headers=target["headers"])
    assert again.status_code == 409


async def test_magic_bytes_and_session_checked_at_attach(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [ID_COPY])

    # A PNG renamed to .pdf passes the name check at upload but not the bytes check at attach.
    ref = await upload_local(client, pub, PNG, name="scan.pdf")
    res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"id_copy": [ref]}))
    assert res.status_code == 422
    assert res.json()["errors"] == [{"field": "id_copy", "code": "file_type"}]

    # Another page load (different nonce) cannot attach this upload.
    ok = await upload_local(client, pub, PDF)
    other = {**pub.submit_body({"id_copy": [ok]}), "uploadNonce": "x" * 32}
    res = await client.post(f"{pub.base}/submissions", json=other)
    assert res.json()["errors"] == [{"field": "id_copy", "code": "file_missing"}]

    # More files than the question allows; a malformed value; a random id.
    three = [await upload_local(client, pub, PDF) for _ in range(3)]
    res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"id_copy": three}))
    assert res.json()["errors"] == [
        {"field": "id_copy", "code": "too_many_files", "params": {"n": 2}}
    ]
    res = await client.post(
        f"{pub.base}/submissions",
        json=pub.submit_body({"id_copy": [{"fileId": str(uuid.uuid4())}]}),
    )
    assert res.json()["errors"] == [{"field": "id_copy", "code": "file_missing"}]

    # Started but never uploaded.
    started = (await _start(client, pub, PDF, "id.pdf", "application/pdf")).json()
    res = await client.post(
        f"{pub.base}/submissions",
        json=pub.submit_body({"id_copy": [{"fileId": started["fileId"]}]}),
    )
    assert res.json()["errors"] == [{"field": "id_copy", "code": "file_missing"}]

    # The good one still attaches.
    res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"id_copy": [ok]}))
    assert res.status_code == 201, res.text


async def test_file_in_repeater_and_hidden_file_dropped(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    docs = field("doc", "file", accept=[".pdf"])
    repeater = {"kind": "repeater", "id": "people", "label": "People", "elements": [docs]}
    toggle = field("send", "yes_no")
    extra = field(
        "extra",
        "file",
        visibleIf={"field": "send", "op": "eq", "value": True},
    )
    pub = await publish(client, me, [repeater, toggle, extra])
    a = await upload_local_field(client, pub, "doc")
    b = await upload_local_field(client, pub, "extra")
    res = await client.post(
        f"{pub.base}/submissions",
        json=pub.submit_body({"people": [{"doc": [a]}], "send": False, "extra": [b]}),
    )
    assert res.status_code == 201, res.text
    rec_a = await db.get(FileRecord, uuid.UUID(a["fileId"]))
    rec_b = await db.get(FileRecord, uuid.UUID(b["fileId"]))
    assert rec_a is not None and rec_a.state == FileState.ATTACHED
    # The hidden question's file is not attached; it stays pending until the cleanup job.
    assert rec_b is not None and rec_b.state == FileState.PENDING


async def upload_local_field(client: AsyncClient, pub: Published, field_id: str) -> dict[str, Any]:
    res = await client.post(
        f"{pub.base}/uploads",
        json={
            "fieldId": field_id,
            "name": "doc.pdf",
            "size": len(PDF),
            "mime": "application/pdf",
            "uploadNonce": pub.live["uploadNonce"],
        },
    )
    assert res.status_code == 201, res.text
    target = res.json()
    res = await client.put(target["url"], content=PDF, headers=target["headers"])
    assert res.status_code == 200, res.text
    return dict(res.json())


async def test_download_permissions_and_preview(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    me = await admin_client(client, db, settings, queue)
    photo = field("photo", "file", accept=["image/*"])
    pub = await publish(client, me, [photo])
    res = await client.post(
        f"{pub.base}/uploads",
        json={
            "fieldId": "photo",
            "name": "me.png",
            "size": len(PNG),
            "mime": "image/png",
            "uploadNonce": pub.live["uploadNonce"],
        },
    )
    target = res.json()
    ref = (await client.put(target["url"], content=PNG, headers=target["headers"])).json()
    # Not attached yet: nobody can download it.
    assert (await client.get(f"/api/v1/files/{ref['fileId']}")).status_code == 404
    res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"photo": [ref]}))
    assert res.status_code == 201

    res = await client.get(f"/api/v1/files/{ref['fileId']}?preview=1")
    assert res.status_code == 200 and res.headers["content-type"] == "image/png"
    assert res.headers["content-disposition"].startswith("inline;")
    assert "sandbox" in res.headers["content-security-policy"]

    for role in ("viewer", "editor", "owner", None):
        email = f"{role or 'outsider'}@example.org"
        user = User(email=email)
        db.add(user)
        await db.flush()
        if role:
            db.add(FormPermission(form_id=pub.id, user_id=user.id, role=FormRole(role)))
        await db.commit()
        async with make_client(app) as other:
            await login(other, queue, email)
            res = await other.get(f"/api/v1/files/{ref['fileId']}")
            assert res.status_code == (200 if role else 404), (role, res.status_code)


async def test_purge_pending(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [ID_COPY])
    ref = await upload_local(client, pub, PDF)
    fid = uuid.UUID(ref["fileId"])
    assert await uploads.purge_pending(db, file_storage, settings) == 0
    await db.execute(
        update(FileRecord)
        .where(FileRecord.id == fid)
        .values(created_at=datetime.now(UTC) - timedelta(hours=25))
    )
    await db.commit()
    assert await uploads.purge_pending(db, file_storage, settings) == 1
    rec = (await db.scalars(select(FileRecord).where(FileRecord.id == fid))).one()
    await db.refresh(rec)
    assert rec.state == FileState.ORPHANED
    assert not await file_storage.exists(rec.storage_key)


# -- s3 backend (moto) -----------------------------------------------------------------------


@pytest.fixture
def s3_client() -> Any:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="justforms-test")
        yield client


@pytest.fixture
def file_storage(request: pytest.FixtureRequest, tmp_path: Any) -> Storage:
    if "s3_client" in request.fixturenames:
        return S3Storage(bucket="justforms-test", client=request.getfixturevalue("s3_client"))
    from app.storage import LocalStorage

    return LocalStorage(tmp_path / "storage")


async def test_s3_presigned_post_and_attach(
    s3_client: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    assert isinstance(file_storage, S3Storage)
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [ID_COPY])
    res = await _start(client, pub, PDF, "id.pdf", "application/pdf")
    assert res.status_code == 201, res.text
    target = res.json()
    assert target["method"] == "POST" and "justforms-test" in target["url"]
    assert target["fields"]["Content-Type"] == "application/pdf"
    assert target["fields"]["key"].startswith("tmp/")
    policy = target["fields"]["policy"]
    import base64
    import json

    conditions = json.loads(base64.b64decode(policy))["conditions"]
    assert ["content-length-range", 1, 1024 * 1024] in conditions
    assert {"Content-Type": "application/pdf"} in conditions

    # The local PUT endpoint is closed on s3.
    res = await client.put(f"/api/v1/public/uploads/{target['fileId']}", content=PDF)
    assert res.status_code == 403

    # The browser posts to the bucket; simulate it, then submit.
    s3_client.put_object(Bucket="justforms-test", Key=target["fields"]["key"], Body=PDF)
    ref = {
        "fileId": target["fileId"],
        "name": "id.pdf",
        "size": len(PDF),
        "mime": "application/pdf",
    }
    res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"id_copy": [ref]}))
    assert res.status_code == 201, res.text
    rec = await db.get(FileRecord, uuid.UUID(target["fileId"]))
    assert rec is not None
    await db.refresh(rec)
    assert rec.state == FileState.ATTACHED and rec.storage_key.startswith("files/")
    body = s3_client.get_object(Bucket="justforms-test", Key=rec.storage_key)["Body"].read()
    assert body == PDF

    res = await client.get(f"/api/v1/files/{target['fileId']}", follow_redirects=False)
    assert res.status_code == 302 and "justforms-test" in res.headers["location"]

    # An object larger than the limit (policy bypassed) is caught at attach.
    res = await _start(client, pub, PDF, "id.pdf", "application/pdf")
    big = res.json()
    s3_client.put_object(
        Bucket="justforms-test", Key=big["fields"]["key"], Body=b"%PDF-" + b"0" * (1024 * 1024)
    )
    ref = {"fileId": big["fileId"]}
    res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"id_copy": [ref]}))
    assert res.json()["errors"] == [{"field": "id_copy", "code": "file_too_large"}]
