"""Respondent-chosen approvers: allowed domains and no self-approval (DESIGN 15.3)."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.config import ApprovalConfig, Form, approver_problems, same_person_key
from app.config import Settings
from app.models import ApprovalStep, Submission
from tests.conftest import RecordingQueue
from tests.helpers import admin_client
from tests.test_approvals import RESPONDENT, _config, _form
from tests.test_signatures import signature_value


def _data(supervisor: str, my_email: str = RESPONDENT) -> dict[str, Any]:
    return {
        "full_name": "Aminath Ali",
        "my_email": my_email,
        "national_id": "A123456",
        "sign": signature_value(),
        "supervisor": supervisor,
    }


async def test_respondent_cannot_choose_themselves(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    res = await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config())
    assert res.status_code == 200, res.text
    for own in ("Applicant@Example.org", "applicant+boss@example.org"):
        res = await client.post(f"{pub.base}/submissions", json=pub.submit_body(_data(own)))
        assert res.status_code == 422, res.text
        assert {"field": "supervisor", "code": "approver_is_respondent"} in res.json()["errors"]
    assert (await db.scalar(select(Submission.id))) is None


async def test_allowed_domains(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    config = _config()
    config["steps"][0]["allowedDomains"] = ["Example.org", "@corp.example"]
    res = await client.put(f"/api/v1/forms/{pub.id}/approvals", json=config)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["config"]["steps"][0]["allowedDomains"] == ["example.org", "corp.example"]
    assert "approver_any_domain" not in [i["code"] for i in body["issues"]]
    res = await client.post(
        f"{pub.base}/submissions", json=pub.submit_body(_data("me@mailbox.example"))
    )
    assert res.status_code == 422
    errors = res.json()["errors"]
    assert errors == [
        {
            "field": "supervisor",
            "code": "approver_domain",
            "params": {"domains": "example.org, corp.example"},
        }
    ]
    res = await client.post(
        f"{pub.base}/submissions", json=pub.submit_body(_data("boss@corp.example"))
    )
    assert res.status_code == 201, res.text
    step = await db.scalar(select(ApprovalStep).where(ApprovalStep.step == 1))
    assert step is not None and step.approver_email == "boss@corp.example"


def test_problems_and_start_defence() -> None:
    form = Form.model_validate(
        {
            "schemaVersion": "1",
            "settings": {"title": "T"},
            "pages": [
                {
                    "id": "p",
                    "elements": [
                        {"kind": "field", "id": "boss", "type": "email", "label": "Boss"},
                        {"kind": "field", "id": "mine", "type": "email", "label": "Mine"},
                    ],
                }
            ],
        }
    )
    config = ApprovalConfig.model_validate(
        {"enabled": True, "steps": [{"name": "B", "source": "field", "fieldId": "boss"}]}
    )
    # The confirmed address (email code or staff sign-in) counts as the respondent's.
    assert approver_problems(config, form, {"boss": "Me@X.org"}, "me@x.org") == [
        {"field": "boss", "code": "approver_is_respondent"}
    ]
    assert approver_problems(config, form, {"boss": "b@x.org", "mine": "B+1@X.org"}, None)
    assert approver_problems(config, form, {"boss": "b@x.org", "mine": "m@x.org"}, None) == []
    assert same_person_key(" A+tag@Example.ORG ") == "a@example.org"


async def test_staff_respondent_cannot_approve_own(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.patch(f"/api/v1/forms/{pub.id}", json={"accessMode": "staff"})
    await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config())
    live = (await client.get(pub.base)).json()
    res = await client.post(
        f"{pub.base}/submissions",
        json={
            "versionId": live["versionId"],
            "data": _data("admin@example.org", my_email="someone@example.net"),
            "uploadNonce": live["uploadNonce"],
        },
    )
    assert res.status_code == 422
    assert res.json()["errors"][0]["code"] == "approver_is_respondent"
