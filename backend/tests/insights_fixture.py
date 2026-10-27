"""A two-version registration form with submissions, written straight to the database, for
the Insights and "Ask your submissions" tests.

Version 1 asked for two members as fixed questions; version 2 turned them into a repeater
(with a version field mapping) and added an option to "Areas of work".
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FormRecord, FormVersion, Organization, Submission, SubmissionStatus
from tests.helpers import field

OPTIONS_V1 = [
    {"value": "disability", "label": "Disability rights"},
    {"value": "climate", "label": "Climate"},
    {"value": "youth", "label": "Youth"},
]
OPTIONS_V2 = [*OPTIONS_V1, {"value": "health", "label": "Health"}]

COMMON = [
    field("org_name", label="Organisation name"),
    field(
        "atoll",
        "single_choice",
        label="Atoll",
        allowOther=True,
        options=[
            {"value": "male", "label": "Malé"},
            {"value": "addu", "label": "Addu"},
        ],
    ),
    field("staff", "number", label="Number of staff"),
    field("founded", "date", label="Date founded"),
    field("registered", "yes_no", label="Registered"),
    field("rating", "rating", label="Rating", max=5),
    field("contact", "email", label="Contact email"),
    field("national_id", label="National ID", sensitive=True),
    field("mission", "long_text", label="Mission statement"),
    field("logo", "file", label="Logo"),
]


def schema(elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": "1",
        "settings": {"title": "CSO registration"},
        "pages": [{"id": "p1", "elements": elements}],
    }


V1 = schema(
    [
        *COMMON,
        field("areas", "multi_choice", label="Areas of work", allowOther=True, options=OPTIONS_V1),
        field("member1_name", label="Member name"),
        field("member1_age", "number", label="Member age"),
        field("member2_name", label="Member name"),
        field("member2_age", "number", label="Member age"),
    ]
)
V2 = schema(
    [
        *COMMON,
        field("areas", "multi_choice", label="Areas of work", allowOther=True, options=OPTIONS_V2),
        {
            "kind": "repeater",
            "id": "members",
            "label": "Members",
            "elements": [
                field("member_name", label="Member name"),
                field("member_age", "number", label="Member age"),
            ],
        },
    ]
)
MAPPING = [
    {
        "repeater": "members",
        "rows": [
            {"member_name": "member1_name", "member_age": "member1_age"},
            {"member_name": "member2_name", "member_age": "member2_age"},
        ],
    }
]


@dataclass
class Seeded:
    org: Organization
    form: FormRecord
    v1: FormVersion
    v2: FormVersion


def _when(day: str) -> datetime:
    return datetime.fromisoformat(f"{day}T06:00:00").replace(tzinfo=UTC)


async def seed(db: AsyncSession, *, settings: dict[str, Any] | None = None) -> Seeded:
    org = Organization(name="Org", slug=f"org-{uuid.uuid4().hex[:8]}")
    db.add(org)
    await db.flush()
    form = FormRecord(
        org_id=org.id,
        slug=f"cso-{uuid.uuid4().hex[:8]}",
        title="CSO registration",
        draft_schema=V2,
        settings={"versionMappings": MAPPING, **(settings or {})},
    )
    db.add(form)
    await db.flush()
    versions = []
    for n, sch in ((1, V1), (2, V2)):
        v = FormVersion(
            form_id=form.id,
            version=n,
            schema=sch,
            schema_hash=hashlib.sha256(json.dumps(sch).encode()).hexdigest(),
        )
        db.add(v)
        versions.append(v)
    await db.flush()
    form.current_version_id = versions[1].id
    v1, v2 = versions
    rows: list[tuple[FormVersion, str, SubmissionStatus, dict[str, Any]]] = [
        (
            v1,
            "2026-01-10",
            SubmissionStatus.NEW,
            {
                "org_name": "Reef Watch",
                "atoll": "male",
                "staff": 4,
                "founded": "2019-03-01",
                "registered": True,
                "rating": 5,
                "contact": "a@example.org",
                "national_id": "A111111",
                "mission": "Protect reefs and the climate",
                "areas": ["climate", "youth"],
                "member1_name": "Aisha",
                "member1_age": 30,
                "member2_name": "Ali",
                "member2_age": 41,
                "logo": [{"fileId": "f1", "name": "logo.png", "size": 10, "mime": "image/png"}],
            },
        ),
        (
            v1,
            "2026-01-20",
            SubmissionStatus.APPROVED,
            {
                "org_name": "Access For All",
                "atoll": "addu",
                "staff": 10,
                "founded": "2015-07-12",
                "registered": True,
                "rating": 4,
                "national_id": "A222222",
                "mission": "Disability rights in every island",
                "areas": ["disability"],
                "member1_name": "Hawwa",
                "member1_age": 25,
            },
        ),
        (
            v2,
            "2026-02-05",
            SubmissionStatus.NEW,
            {
                "org_name": "Island Youth",
                "atoll": "Fuvahmulah",
                "staff": 2,
                "founded": "2021-11-30",
                "registered": False,
                "rating": 3,
                "contact": "y@example.org",
                "mission": "Sports and climate clubs for young people",
                "areas": ["youth", "climate", "Fishing"],
                "members": [{"member_name": "Moosa", "member_age": 19}],
            },
        ),
        (
            v2,
            "2026-02-14",
            SubmissionStatus.IN_REVIEW,
            {
                "org_name": "Care Network",
                "atoll": "male",
                "staff": 7,
                "founded": "2010-01-05",
                "registered": True,
                "national_id": "A333333",
                "mission": "Health and disability support",
                "areas": ["disability", "health"],
                "members": [
                    {"member_name": "Mariyam", "member_age": 52},
                    {"member_name": "Ibrahim", "member_age": 47},
                    {"member_name": "Zahir"},
                ],
            },
        ),
        (
            v2,
            "2026-03-01",
            SubmissionStatus.REJECTED,
            {
                "org_name": "ޖަމްޢިއްޔާ",
                "atoll": "addu",
                "registered": False,
                "rating": 1,
                "mission": "ރަށުގެ ތަރައްޤީ",
                "areas": [],
            },
        ),
    ]
    for i, (version, day, status, data) in enumerate(rows, start=1):
        db.add(
            Submission(
                form_id=form.id,
                form_version_id=version.id,
                seq=i,
                status=status,
                data=data,
                submitted_at=_when(day),
                language="en",
                # Never sent to the AI (not an answer); the respondent email is.
                ip="198.51.100.7" if i == 1 else None,
                respondent_email="resp@example.org" if i == 1 else None,
            )
        )
    # A deleted submission never counts.
    db.add(
        Submission(
            form_id=form.id,
            form_version_id=v2.id,
            seq=99,
            data={"areas": ["disability"], "staff": 1000},
            submitted_at=_when("2026-03-02"),
            deleted_at=_when("2026-03-03"),
        )
    )
    await db.commit()
    return Seeded(org, form, v1, v2)
