"""Exact submit times from Jotform's API, reference numbers oldest first, and rebuilding
untouched imported rows (DESIGN 13.3, "Correcting an import")."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.importers import service
from app.importers.jotform import api_source
from app.importers.rebuild import RebuildRefused, rebuild_imported
from app.models import AuditLog, Submission, SubmissionEvent
from app.storage import Storage
from tests.conftest import RecordingQueue
from tests.helpers import admin_client
from tests.test_imports_api import FIXTURES, _imported_form, _publish, _upload

IDS = ["6100000000000000001", "6100000000000000002", "6100000000000000003"]


# -- the API ---------------------------------------------------------------------------------


async def test_submission_times_paged_and_converted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_source, "PAGE", 2)
    pages = {
        "0": [
            # Eastern summer time (UTC-4) and winter time (UTC-5).
            {"id": "1", "created_at": "2025-07-01 06:00:00", "status": "ACTIVE"},
            {"id": "2", "created_at": "2025-12-01 06:00:00", "status": "ACTIVE"},
        ],
        "2": [
            {"id": "3", "created_at": "not a time", "status": "ACTIVE"},
            {"id": "4", "created_at": "2025-12-02 06:00:00", "status": "DELETED"},
        ],
        "4": [],
    }
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/form/123/submissions"
        return httpx.Response(200, json={"content": pages[request.url.params["offset"]]})

    times = await api_source.submission_times(
        "us", "k" * 32, "123", transport=httpx.MockTransport(handler)
    )
    assert times == {
        "1": datetime(2025, 7, 1, 10, 0, tzinfo=UTC),
        "2": datetime(2025, 12, 1, 11, 0, tzinfo=UTC),
    }
    assert [r.url.params["offset"] for r in seen] == ["0", "2", "4"]
    assert all(r.headers["apikey"] == "k" * 32 and "k" * 32 not in str(r.url) for r in seen)
    with pytest.raises(api_source.JotformApiError):
        await api_source.submission_times("us", "k" * 32, "../x")


# -- the import ------------------------------------------------------------------------------


def _fake_times(
    monkeypatch: pytest.MonkeyPatch, times: dict[str, datetime], calls: list[str]
) -> None:
    async def fake(region: str, key: str, form_id: str, **_kw: Any) -> dict[str, datetime]:
        calls.append(form_id)
        return times

    monkeypatch.setattr(api_source, "submission_times", fake)


async def _import(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    storage: Storage,
) -> tuple[str, dict[str, Any]]:
    me = await admin_client(client, db, settings, queue)
    form_id = await _imported_form(client, me, "registration_form.html")
    await _publish(client, form_id)
    csv_bytes = (FIXTURES / "registration_submissions.csv").read_bytes()
    up = (await _upload(client, form_id, csv_bytes, "x.csv")).json()
    await client.put(
        f"/api/v1/imports/{up['id']}/mapping",
        json={"columns": [c["target"] for c in up["columns"]]},
    )
    await client.post(f"/api/v1/imports/{up['id']}/start", json={})
    assert await service.run_submissions_import(db, storage, settings, uuid.UUID(up["id"]))
    return form_id, (await client.get(f"/api/v1/imports/{up['id']}")).json()["report"]


async def _rows(db: AsyncSession, form_id: str) -> list[Submission]:
    return list(
        (
            await db.scalars(
                select(Submission)
                .where(Submission.form_id == uuid.UUID(form_id))
                .order_by(Submission.seq)
            )
        ).all()
    )


async def test_import_numbers_oldest_first_with_api_times(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "jotform_api_key", SecretStr("k" * 32))
    # The API says the last row of the file came first.
    exact = {
        IDS[0]: datetime(2025, 3, 14, 9, 12, 44, tzinfo=UTC),
        IDS[2]: datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC),
    }
    calls: list[str] = []
    _fake_times(monkeypatch, exact, calls)
    form_id, report = await _import(client, db, settings, queue, file_storage)
    assert calls == ["200000000000001"]  # the Jotform form id kept from the form import
    assert report["exactTimes"] == {"source": "jotform_api", "found": 2, "used": 2}
    rows = await _rows(db, form_id)
    assert [r.seq for r in rows] == [1, 2, 3]
    assert rows[0].external_id == IDS[2] and rows[0].submitted_at == exact[IDS[2]]
    times = [r.submitted_at for r in rows]
    assert times == sorted(times)
    first = await db.scalar(
        select(SubmissionEvent).where(
            SubmissionEvent.submission_id == rows[0].id, SubmissionEvent.seq == 1
        )
    )
    assert first is not None and first.payload["timeSource"] == "jotform_api"
    assert first.payload["seq"] == 1


async def test_import_without_key_keeps_file_times(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    monkeypatch.setattr(settings, "jotform_api_key", None)
    form_id, report = await _import(client, db, settings, queue, file_storage)
    assert report["exactTimes"] == {"source": "file", "reason": "no_key", "used": 0}
    times = [r.submitted_at for r in await _rows(db, form_id)]
    assert times == sorted(times)


# -- rebuilding ------------------------------------------------------------------------------


async def test_rebuild_retimes_and_renumbers(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    monkeypatch.setattr(settings, "jotform_api_key", None)
    form_id, _report = await _import(client, db, settings, queue, file_storage)
    fid = uuid.UUID(form_id)
    before = {r.external_id: r for r in await _rows(db, form_id)}
    old_ids = {r.id for r in before.values()}
    exact = {
        IDS[0]: datetime(2025, 5, 1, 8, 0, tzinfo=UTC),
        IDS[2]: datetime(2025, 1, 1, 8, 0, tzinfo=UTC),
    }

    dry = await rebuild_imported(db, fid, exact, time_source="jotform_api", dry_run=True)
    assert (dry.rows, dry.retimed, dry.missing_time) == (3, 2, 1)
    await db.rollback()

    report = await rebuild_imported(db, fid, exact, time_source="jotform_api")
    await db.commit()
    assert report.retimed == 2 and report.renumbered >= 2
    rows = await _rows(db, form_id)
    assert [r.seq for r in rows] == [1, 2, 3]
    assert [r.submitted_at for r in rows] == sorted(r.submitted_at for r in rows)
    by_ext = {r.external_id: r for r in rows}
    assert by_ext[IDS[2]].seq == 1 and by_ext[IDS[2]].submitted_at == exact[IDS[2]]
    # Answers and links carried over; every row verifies with its new hash and chain.
    for ext, row in by_ext.items():
        assert row.data == before[ext].data and row.imported_links == before[ext].imported_links
        verify = (await client.get(f"/api/v1/submissions/{row.id}/verify")).json()
        assert verify["ok"] is True
    rebuilt = by_ext[IDS[2]]
    assert rebuilt.id not in old_ids
    event = await db.scalar(
        select(SubmissionEvent).where(SubmissionEvent.submission_id == rebuilt.id)
    )
    assert event is not None
    assert event.payload["rebuiltFrom"] == str(before[IDS[2]].id)
    assert event.payload["previousSeq"] == before[IDS[2]].seq
    assert event.payload["timeSource"] == "jotform_api" and event.payload["imported"] is True
    logs = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "submission.import_rebuilt"))
    ).all()
    assert len(logs) == len(report.changes)

    # Running it again changes nothing.
    again = await rebuild_imported(db, fid, exact, time_source="jotform_api")
    assert (again.retimed, again.renumbered, again.changes) == (0, 0, [])


async def test_rebuild_refuses_rows_with_activity(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    monkeypatch.setattr(settings, "jotform_api_key", None)
    form_id, _report = await _import(client, db, settings, queue, file_storage)
    first = (await _rows(db, form_id))[0]
    res = await client.post(f"/api/v1/submissions/{first.id}/comments", json={"text": "Seen"})
    assert res.status_code in (200, 201), res.text
    with pytest.raises(RebuildRefused) as out:
        await rebuild_imported(
            db,
            uuid.UUID(form_id),
            {IDS[2]: datetime(2025, 1, 1, tzinfo=UTC)},
            time_source="jotform_api",
        )
    assert out.value.blocked == {"activity": 1}
    await db.rollback()
    assert (await _rows(db, form_id))[0].id == first.id
