"""Reference numbers come from a per-form counter that never goes down: erasing a submission
never frees its number for another one (app.submissions.numbering)."""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.importers import service
from app.models import AuditLog, FormRecord, Submission
from app.storage import Storage
from app.submissions import numbering, retention
from tests.conftest import RecordingQueue
from tests.helpers import Published, admin_client, field, publish
from tests.test_imports_api import FIXTURES, _imported_form, _publish, _upload


async def _submit(client: AsyncClient, pub: Published, name: str) -> int:
    res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"name": name}))
    assert res.status_code == 201, res.text
    return int(res.json()["seq"])


async def _counter(db: AsyncSession, form_id: str) -> int:
    value = await db.scalar(select(FormRecord.last_seq).where(FormRecord.id == uuid.UUID(form_id)))
    return int(value or 0)


async def test_erased_newest_number_is_not_reused(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name", label="Name")])
    assert [await _submit(client, pub, f"P{i}") for i in range(3)] == [1, 2, 3]
    newest = await db.scalar(
        select(Submission.id).where(Submission.form_id == uuid.UUID(pub.id), Submission.seq == 3)
    )
    assert newest is not None

    # To the trash, then erased by the nightly job once the trash period is over.
    bulk = f"/api/v1/forms/{pub.id}/submissions/bulk"
    res = await client.post(bulk, json={"ids": [str(newest)], "action": "delete"})
    assert res.json() == {"changed": 1}
    await db.execute(
        update(Submission)
        .where(Submission.id == newest)
        .values(deleted_at=datetime.now(UTC) - timedelta(days=31))
    )
    await db.commit()
    assert await retention.purge(db, file_storage, trash_days=30) == 1
    assert await db.get(Submission, newest) is None

    assert await _submit(client, pub, "P3") == 4
    assert await _counter(db, pub.id) == 4

    # Erasing straight from the trash ("Delete permanently") does not free it either.
    four = await db.scalar(
        select(Submission.id).where(Submission.form_id == uuid.UUID(pub.id), Submission.seq == 4)
    )
    await client.post(bulk, json={"ids": [str(four)], "action": "delete"})
    res = await client.post(bulk, json={"ids": [str(four)], "action": "purge"})
    assert res.json() == {"changed": 1}
    assert await _submit(client, pub, "P4") == 5


async def test_concurrent_submits_get_unique_numbers(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    settings.rate_limits = ["public_submit=100/60"]
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name", label="Name")])
    seqs = await asyncio.gather(*(_submit(client, pub, f"P{i}") for i in range(12)))
    assert sorted(seqs) == list(range(1, 13))
    assert await _counter(db, pub.id) == 12


async def test_allocate_is_safe_across_sessions(
    client: AsyncClient,
    db: AsyncSession,
    db_engine: Any,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name", label="Name")])
    form_id = uuid.UUID(pub.id)
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def take(count: int) -> list[int]:
        async with maker() as session:
            first = await numbering.allocate(session, form_id, count)
            await asyncio.sleep(0.01)  # hold the row lock a moment
            await session.commit()
            return list(range(first, first + count))

    async def rolled_back() -> None:
        async with maker() as session:
            await numbering.allocate(session, form_id, 5)
            await session.rollback()

    results = await asyncio.gather(*(take(n) for n in (1, 3, 1, 2, 1, 4)), rolled_back())
    taken = sorted(n for r in results if r for n in r)
    assert taken == list(range(1, 13))  # no duplicates, no gaps; the rollback gave its back
    assert await _counter(db, pub.id) == 12


async def test_import_numbers_after_the_counter(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    form_id = await _imported_form(client, me, "registration_form.html")
    await _publish(client, form_id)
    # Numbers 1-7 were handed out once and have all been erased since.
    await db.execute(
        update(FormRecord).where(FormRecord.id == uuid.UUID(form_id)).values(last_seq=7)
    )
    await db.commit()

    res = await _upload(
        client, form_id, (FIXTURES / "registration_submissions.csv").read_bytes(), "export.csv"
    )
    up = res.json()
    await client.put(
        f"/api/v1/imports/{up['id']}/mapping",
        json={"columns": [c["target"] for c in up["columns"]]},
    )
    await client.post(f"/api/v1/imports/{up['id']}/start", json={})
    assert await service.run_submissions_import(db, file_storage, settings, uuid.UUID(up["id"]))
    seqs = (
        await db.scalars(
            select(Submission.seq)
            .where(Submission.form_id == uuid.UUID(form_id))
            .order_by(Submission.seq)
        )
    ).all()
    assert list(seqs) == [8, 9, 10]
    assert await _counter(db, form_id) == 10


def _migration() -> Any:
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20261030_0026_form_last_seq.py"
    )
    spec = importlib.util.spec_from_file_location("m0026", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_migration_starts_counters_at_highest_used_number(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    stored = await publish(client, me, [field("name", label="Name")], title="Stored")
    erased = await publish(client, me, [field("name", label="Name")], title="Erased")
    empty = await publish(client, me, [field("name", label="Name")], title="Empty")
    for _ in range(3):
        await _submit(client, stored, "x")
        await _submit(client, erased, "x")
    org_id = uuid.UUID(me["orgs"][0]["id"])
    # "Erased" now holds #0001-#0002 and its tombstones say #0004 and #0005 were erased; an
    # older erased number on "Stored" is below what it still holds; a malformed entry is ignored.
    await db.execute(
        delete(Submission).where(Submission.form_id == uuid.UUID(erased.id), Submission.seq == 3)
    )
    for meta in (
        {"form_id": erased.id, "seq": 5, "reason": "deleted"},
        {"form_id": erased.id, "seq": 4, "reason": "owner"},
        {"form_id": stored.id, "seq": 2, "reason": "retention"},
        {"form_id": empty.id, "seq": "n/a", "reason": "deleted"},
    ):
        db.add(
            AuditLog(
                org_id=org_id,
                action="submission.erased",
                target_type="submission",
                target_id=uuid.uuid4(),
                meta=meta,
            )
        )
    # Another action naming a higher number does not count.
    db.add(
        AuditLog(org_id=org_id, action="submission.delete", meta={"form_id": stored.id, "seq": 99})
    )
    await db.execute(update(FormRecord).values(last_seq=0))
    await db.commit()

    await db.execute(text(_migration().BACKFILL))
    await db.commit()
    assert await _counter(db, stored.id) == 3
    assert await _counter(db, erased.id) == 5
    assert await _counter(db, empty.id) == 0
    assert await _submit(client, erased, "next") == 6
