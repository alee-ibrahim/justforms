"""Server-side answer validation: shared cases (also run by vitest) and whole submissions."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.schemas.form import FieldElement, Form
from app.validation.answers import Problem, check_answer, validate_submission
from tests.conftest import RecordingQueue
from tests.helpers import admin_client, field, publish

SPEC = Path(__file__).resolve().parents[2] / "spec" / "validation" / "answers.json"
DOC = json.loads(SPEC.read_text(encoding="utf-8"))
TODAY = date.fromisoformat(DOC["today"])
FIELD = TypeAdapter(FieldElement)


@pytest.mark.parametrize("case", DOC["cases"], ids=[c["name"] for c in DOC["cases"]])
def test_shared_answer_cases(case: dict[str, Any]) -> None:
    f = FIELD.validate_python({"kind": "field", "id": "q", "label": "Q", **case["field"]})
    got = check_answer(f, case.get("value"), case.get("required", False), TODAY)
    want = case["expect"]
    if want is None:
        assert got is None
    else:
        assert got == Problem(want["code"], want.get("params", {}))


def test_relative_dates_allow_a_day_of_time_zone_slack() -> None:
    f = FIELD.validate_python(
        {"kind": "field", "id": "q", "label": "Q", "type": "date", "maxDate": "today"}
    )
    assert check_answer(f, "2026-10-24", False, TODAY) is not None
    assert check_answer(f, "2026-10-24", False, TODAY, date_slack_days=1) is None
    fixed = FIELD.validate_python(
        {"kind": "field", "id": "q", "label": "Q", "type": "date", "maxDate": "2026-10-23"}
    )
    assert check_answer(fixed, "2026-10-24", False, TODAY, date_slack_days=1) is not None


def test_catastrophic_pattern_times_out_as_a_mismatch() -> None:
    f = FIELD.validate_python(
        {"kind": "field", "id": "q", "label": "Q", "type": "short_text", "pattern": "^(a+)+$"}
    )
    problem = check_answer(f, "a" * 40 + "!", False, TODAY)
    assert problem == Problem("pattern")


def _form(elements: list[dict[str, Any]]) -> Form:
    return Form.model_validate(
        {
            "schemaVersion": "1",
            "settings": {"title": "T"},
            "pages": [{"id": "p1", "elements": elements}],
        }
    )


def test_submission_strips_hidden_and_checks_visible() -> None:
    form = _form(
        [
            field("age", "number", required=True, min=15, integer=True),
            field(
                "guardian",
                required=True,
                visibleIf={"field": "age", "op": "lt", "value": 18},
            ),
        ]
    )
    # Hidden answers are dropped even when they are invalid.
    v = validate_submission(form, {"age": 30, "guardian": 12, "junk": "x"}, TODAY)
    assert v.errors == [] and v.data == {"age": 30}
    # Visible answers are type-checked.
    v = validate_submission(form, {"age": "16"}, TODAY)
    assert v.errors == [{"field": "age", "code": "number"}]
    v = validate_submission(form, {"age": 16, "guardian": ["x"]}, TODAY)
    assert v.errors == [{"field": "guardian", "code": "invalid"}]
    v = validate_submission(form, {"age": 10}, TODAY)
    assert v.errors == [
        {"field": "age", "code": "at_least", "params": {"min": 15}},
        {"field": "guardian", "code": "required"},
    ]


def test_repeaters_are_padded_to_min_rows_and_capped() -> None:
    form = _form(
        [
            {
                "kind": "repeater",
                "id": "people",
                "label": "People",
                "minRows": 1,
                "maxRows": 2,
                "elements": [field("name", required=True), field("age", "number", max=120)],
            }
        ]
    )
    # A tampered client that leaves out the row still has to answer the required question.
    v = validate_submission(form, {}, TODAY)
    assert v.errors == [{"field": "name", "code": "required", "repeater": "people", "row": 0}]
    v = validate_submission(form, {"people": [{"name": "A", "age": 200}]}, TODAY)
    assert v.errors == [
        {
            "field": "age",
            "code": "at_most",
            "params": {"max": 120},
            "repeater": "people",
            "row": 0,
        }
    ]
    v = validate_submission(form, {"people": [{"name": "A"}] * 3}, TODAY)
    assert v.errors == [{"field": "people", "code": "rows_max", "params": {"n": 2}}]
    v = validate_submission(form, {"people": "lots"}, TODAY)
    assert v.errors == [{"field": "people", "code": "invalid"}]
    v = validate_submission(form, {"people": [{"name": "A", "junk": 1}]}, TODAY)
    assert v.errors == [] and v.data == {"people": [{"name": "A"}]}


async def test_public_submit_rejects_tampered_answers(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(
        client,
        me,
        [
            field("email", "email", required=True),
            field(
                "track",
                "single_choice",
                options=[{"value": "civic", "label": "Civic"}, {"value": "tech", "label": "Tech"}],
            ),
            field("when", "date", minDate="2026-01-01"),
        ],
    )
    url = f"{pub.base}/submissions"
    res = await client.post(
        url,
        json=pub.submit_body({"email": "nope", "track": "hacking", "when": "2025-05-05"}),
    )
    assert res.status_code == 422
    assert res.json()["errors"] == [
        {"field": "email", "code": "email"},
        {"field": "track", "code": "option"},
        {"field": "when", "code": "date_from", "params": {"date": "2026-01-01"}},
    ]
    res = await client.post(
        url, json=pub.submit_body({"email": "a@example.org", "track": "tech", "when": "2026-02-01"})
    )
    assert res.status_code == 201, res.text
