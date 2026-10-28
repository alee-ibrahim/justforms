"""Where people get stuck: anonymous friction counters from public forms."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.insights import friction
from app.models import FormFriction
from app.schemas.form import Form
from tests.conftest import RecordingQueue
from tests.helpers import Published, admin_client, field, publish

VISIT = "visit-abcdefghijklmnop"
PAGES = [
    {
        "id": "about",
        "elements": [field("full_name", required=True), field("nid", idPreset="mv_national_id")],
    },
    {"id": "contact", "elements": [field("email", "email", required=True)]},
]


async def _form(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> Published:
    me = await admin_client(client, db, settings, queue)
    return await publish(client, me, [], pages=PAGES)


def _report(pub: Published, events: list[dict[str, Any]], visit: str = VISIT) -> dict[str, Any]:
    return {"versionId": pub.live["versionId"], "visit": visit, "events": events}


async def test_counts_once_per_visit_without_values_or_cookies(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    pub = await _form(client, db, settings, queue)
    assert pub.live["friction"] is True
    events = [
        {"type": "page", "page": "about"},
        {"type": "start"},
        {"type": "error", "field": "nid", "code": "pattern"},
        {"type": "error", "field": "full_name", "code": "required"},
        # Dropped: unknown question, unknown code, unknown page, values never accepted.
        {"type": "error", "field": "nope", "code": "required"},
        {"type": "error", "field": "email", "code": "made_up"},
        {"type": "page", "page": "nowhere"},
    ]
    client.cookies.clear()
    for _ in range(3):  # retries and duplicates count once
        res = await client.post(f"{pub.base}/friction", json=_report(pub, events))
        assert res.status_code == 204
        assert "set-cookie" not in res.headers
    await client.post(
        f"{pub.base}/friction",
        json=_report(
            pub,
            [{"type": "page", "page": "about"}, {"type": "page", "page": "contact"}],
            "another-visit-0123456789",
        ),
    )
    res = await client.post(
        f"{pub.base}/friction",
        json={
            **_report(pub, []),
            "events": [{"type": "error", "field": "nid", "code": "pattern", "value": "A12"}],
        },
    )
    assert res.status_code == 422  # a value is never accepted
    rows = (await db.execute(select(FormFriction))).scalars().all()
    got = sorted((r.metric, r.page_id, r.field_id, r.code, r.count) for r in rows)
    assert got == [
        ("error", "about", "full_name", "required", 1),
        ("error", "about", "nid", "pattern", 1),
        ("start", "", "", "", 1),
        ("view", "about", "", "", 2),
        ("view", "contact", "", "", 1),
    ]


async def test_submissions_count_and_the_summary(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    pub = await _form(client, db, settings, queue)
    await client.post(
        f"{pub.base}/friction",
        json=_report(
            pub,
            [
                {"type": "page", "page": "about"},
                {"type": "error", "field": "email", "code": "email"},
            ],
        ),
    )
    res = await client.post(
        f"{pub.base}/submissions",
        json=pub.submit_body({"full_name": "Test", "nid": "a 123 456", "email": "t@example.org"}),
    )
    assert res.status_code == 201, res.text
    summary = (await client.get(f"/api/v1/forms/{pub.id}/insights/friction")).json()
    assert summary["enabled"] is True
    assert summary["days"] == 30
    assert summary["submitted"] == 1
    assert summary["pages"] == [{"page": "about", "visits": 1}]
    assert summary["fields"] == [
        {"field": "email", "page": "contact", "total": 1, "codes": {"email": 1}}
    ]
    assert summary["codes"] == [{"code": "email", "count": 1}]


async def test_owner_can_turn_it_off(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    pub = await _form(client, db, settings, queue)
    res = await client.patch(f"/api/v1/forms/{pub.id}", json={"frictionInsights": False})
    assert res.status_code == 200 and res.json()["frictionInsights"] is False
    live = (await client.get(pub.base)).json()
    assert live["friction"] is False
    res = await client.post(f"{pub.base}/friction", json=_report(pub, [{"type": "start"}]))
    assert res.status_code == 204
    await client.post(
        f"{pub.base}/submissions",
        json=pub.submit_body({"full_name": "Test", "email": "t@example.org"}),
    )
    assert (await db.execute(select(FormFriction))).scalars().all() == []


def test_counters_ignore_what_the_form_does_not_have() -> None:
    form = Form.model_validate({"settings": {"title": "T"}, "pages": PAGES})
    got = friction.counters(
        form,
        [
            {"type": "error", "field": "email", "code": "email"},
            {"type": "error", "field": "email", "code": "email"},
            {"type": "error", "field": "about", "code": "required"},  # a page, not a question
            {"type": "submit"},  # submissions are counted by the server only
        ],
    )
    assert [c.member for c in got] == ["error|contact|email|email"]
    assert (
        friction.enabled(None)
        and friction.enabled({})
        and not friction.enabled({"frictionInsights": False})
    )
