"""Phase 4: respondent email codes, staff-only forms, CAPTCHA, rate limits and headers."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import captcha, ratelimit
from app.config import Settings
from app.models import Submission
from tests.conftest import RecordingQueue, make_client
from tests.helpers import Published, admin_client, field, publish


def last_code(queue: RecordingQueue, email: str) -> str:
    for function, kwargs in reversed(queue.jobs):
        if function == "send_email" and kwargs["to"] == email:
            return next(w for w in kwargs["text"].split() if w.rstrip(".").isdigit()).rstrip(".")
    raise AssertionError(f"no code sent to {email}")


async def _otp_form(client: AsyncClient, me: dict[str, Any], **settings: Any) -> Published:
    pub = await publish(
        client, me, [field("name", label="Name", required=True)], title="Members only"
    )
    res = await client.patch(f"/api/v1/forms/{pub.id}", json={"accessMode": "otp", **settings})
    assert res.status_code == 200, res.text
    return pub


async def test_rate_limiter_sliding_window(settings: Settings) -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    for _ in range(10):
        assert await ratelimit.hit(redis, settings, "public_submit", "1.2.3.4:f") is None
    wait = await ratelimit.hit(redis, settings, "public_submit", "1.2.3.4:f")
    assert wait is not None and 1 <= wait <= 61
    # Other keys are independent; overrides and the off switch work.
    assert await ratelimit.hit(redis, settings, "public_submit", "5.6.7.8:f") is None
    custom = settings.model_copy(update={"rate_limits": ["public_submit=1/60"]})
    assert ratelimit.limits(custom)["public_submit"] == ratelimit.Limit(1, 60)
    off = settings.model_copy(update={"rate_limit_enabled": False})
    assert await ratelimit.hit(redis, off, "public_submit", "1.2.3.4:f") is None


async def test_security_headers_on_api(client: AsyncClient) -> None:
    res = await client.get("/api/v1/meta")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in res.headers["content-security-policy"]
    assert res.headers["referrer-policy"] == "no-referrer"


async def test_frame_ancestors_follow_embed_origins(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    uri = f"/{pub.form['slug']}?embed=1"
    res = await client.get("/api/v1/public/frame-ancestors", headers={"X-Original-URI": uri})
    assert res.status_code == 204 and res.headers["x-justforms-frame-ancestors"] == "*"
    await client.patch(
        f"/api/v1/forms/{pub.id}", json={"embedOrigins": ["https://www.example.org"]}
    )
    res = await client.get("/api/v1/public/frame-ancestors", headers={"X-Original-URI": uri})
    assert res.headers["x-justforms-frame-ancestors"] == "'self' https://www.example.org"
    res = await client.get(
        "/api/v1/public/frame-ancestors", headers={"X-Original-URI": "/no-such-form"}
    )
    assert res.headers["x-justforms-frame-ancestors"] == "'self'"


async def test_otp_form_end_to_end(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _otp_form(client, me, otpOneResponse=True)
    public = make_client(app)  # a respondent: no staff cookie

    locked = (await public.get(pub.base)).json()
    assert locked["accessMode"] == "otp" and locked["schema"] is None
    assert locked["title"] == "Members only" and "uploadNonce" not in locked
    body = {"versionId": locked["versionId"], "data": {"name": "A"}}
    assert (await public.post(f"{pub.base}/submissions", json=body)).status_code == 401

    res = await public.post(f"{pub.base}/otp/request", json={"email": "Aisha@Example.org"})
    assert res.status_code == 202
    code = last_code(queue, "aisha@example.org")
    job = next(k for f, k in queue.jobs if f == "send_email" and k["to"] == "aisha@example.org")
    assert "Members only" in job["subject"] and job["html"] and code in job["html"]

    res = await public.post(
        f"{pub.base}/otp/verify", json={"email": "aisha@example.org", "code": code}
    )
    assert res.status_code == 200, res.text
    token = res.json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    live = (await public.get(pub.base, headers=auth)).json()
    assert live["schema"]["pages"] and live["respondentEmail"] == "aisha@example.org"
    body = {
        "versionId": live["versionId"],
        "data": {"name": "A"},
        "uploadNonce": live["uploadNonce"],
    }
    res = await public.post(f"{pub.base}/submissions", json=body, headers=auth)
    assert res.status_code == 201, res.text
    sub = await db.scalar(select(Submission).where(Submission.form_id == pub.form["id"]))
    assert sub is not None and sub.respondent_email == "aisha@example.org"
    assert ("dispatch_event", {"event": "submission.created", "submission_id": str(sub.id)}) in (
        queue.jobs
    )
    # One response per email: the form, a new code and a second submit are refused.
    assert (await public.get(pub.base, headers=auth)).status_code == 409
    assert (
        await public.post(f"{pub.base}/submissions", json=body, headers=auth)
    ).status_code == 409
    # A token for another form doesn't work here.
    other = await _otp_form(client, me)
    res = await public.post(f"{other.base}/otp/request", json={"email": "b@example.org"})
    code_b = last_code(queue, "b@example.org")
    tok_b = (
        await public.post(
            f"{other.base}/otp/verify", json={"email": "b@example.org", "code": code_b}
        )
    ).json()["token"]
    res = await public.get(pub.base, headers={"Authorization": f"Bearer {tok_b}"})
    assert res.json()["schema"] is None

    # Staff list and detail show the confirmed address; search finds it.
    listed = (await client.get(f"/api/v1/forms/{pub.id}/submissions?q=aisha")).json()
    assert [i["respondentEmail"] for i in listed["items"]] == ["aisha@example.org"]
    detail = (await client.get(f"/api/v1/submissions/{sub.id}")).json()
    created = next(e for e in detail["events"] if e["type"] == "created")
    assert created["payload"]["respondentVia"] == "code"


async def test_otp_brute_force_is_blocked(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _otp_form(client, me)
    public = make_client(app)
    await public.post(f"{pub.base}/otp/request", json={"email": "x@example.org"})
    code = last_code(queue, "x@example.org")
    wrong = "000000" if code != "000000" else "111111"
    results = []
    for _ in range(5):
        res = await public.post(
            f"{pub.base}/otp/verify", json={"email": "x@example.org", "code": wrong}
        )
        results.append(res.json()["detail"])
    assert results == ["code_wrong"] * 4 + ["code_expired"]
    # The real code no longer works after 5 wrong tries.
    res = await public.post(f"{pub.base}/otp/verify", json={"email": "x@example.org", "code": code})
    assert res.json()["detail"] == "code_expired"
    # Requests per email are limited (3 per 10 minutes).
    statuses = [
        (await public.post(f"{pub.base}/otp/request", json={"email": "x@example.org"})).status_code
        for _ in range(3)
    ]
    assert statuses == [202, 202, 429]
    # Verify attempts per IP are limited (30 per hour) whatever the address.
    codes = []
    for i in range(30):
        res = await public.post(
            f"{pub.base}/otp/verify", json={"email": f"y{i}@example.org", "code": "123456"}
        )
        codes.append(res.status_code)
    assert codes[-1] == 429 and "retry-after" in res.headers


async def test_otp_domains(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _otp_form(client, me, otpAllowedDomains=["Example.org"])
    assert pub.form["id"]
    form = (await client.get(f"/api/v1/forms/{pub.id}")).json()
    assert form["otpAllowedDomains"] == ["example.org"] and form["accessMode"] == "otp"
    public = make_client(app)
    res = await public.post(f"{pub.base}/otp/request", json={"email": "a@other.org"})
    assert res.status_code == 422 and res.json()["detail"] == "domain_not_allowed"
    res = await public.post(f"{pub.base}/otp/request", json={"email": "a@example.org"})
    assert res.status_code == 202
    bad = await client.patch(
        f"/api/v1/forms/{pub.id}", json={"otpAllowedDomains": ["not a domain"]}
    )
    assert bad.status_code == 422


async def test_staff_only_form(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    await client.patch(f"/api/v1/forms/{pub.id}", json={"accessMode": "staff"})
    anon = make_client(app)
    res = await anon.get(pub.base)
    assert res.status_code == 401 and res.json()["detail"] == "login_required"
    live = (await client.get(pub.base)).json()
    assert live["respondentEmail"] == "admin@example.org" and live["schema"]
    body = {
        "versionId": live["versionId"],
        "data": {"name": "S"},
        "uploadNonce": live["uploadNonce"],
    }
    csrf = client.headers.pop("X-CSRF-Token")
    assert (await client.post(f"{pub.base}/submissions", json=body)).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    res = await client.post(f"{pub.base}/submissions", json=body)
    assert res.status_code == 201, res.text
    sub = await db.scalar(select(Submission).where(Submission.form_id == pub.form["id"]))
    assert sub is not None and sub.respondent_email == "admin@example.org"


def solve(challenge: dict[str, Any]) -> str:
    for n in range(challenge["maxnumber"] + 1):
        if hashlib.sha256(f"{challenge['salt']}{n}".encode()).hexdigest() == challenge["challenge"]:
            payload = {
                "algorithm": "SHA-256",
                "challenge": challenge["challenge"],
                "number": n,
                "salt": challenge["salt"],
                "signature": challenge["signature"],
            }
            return base64.b64encode(json.dumps(payload).encode()).decode()
    raise AssertionError("unsolvable")


async def test_altcha_captcha(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    settings.captcha_provider = "altcha"
    settings.altcha_max_number = 2000
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    meta = (await client.get("/api/v1/meta")).json()["features"]
    assert meta["captcha"] == "altcha"
    assert (await client.get(pub.base)).json()["captcha"] is None  # form setting: off
    res = await client.patch(f"/api/v1/forms/{pub.id}", json={"captcha": "always"})
    assert res.json()["captcha"] == "always"
    live = (await client.get(pub.base)).json()
    challenge = live["captcha"]["challenge"]
    assert live["captcha"]["provider"] == "altcha"
    body = {
        "versionId": live["versionId"],
        "data": {"name": "A"},
        "uploadNonce": live["uploadNonce"],
    }
    res = await client.post(f"{pub.base}/submissions", json=body)
    assert res.status_code == 422 and res.json()["detail"] == "captcha_required"
    bad = dict(json.loads(base64.b64decode(solve(challenge))), number=-1)
    res = await client.post(
        f"{pub.base}/submissions",
        json={**body, "captchaToken": base64.b64encode(json.dumps(bad).encode()).decode()},
    )
    assert res.json()["detail"] == "captcha_failed"
    token = solve(challenge)
    res = await client.post(f"{pub.base}/submissions", json={**body, "captchaToken": token})
    assert res.status_code == 201, res.text
    # A solved challenge works once.
    res = await client.post(f"{pub.base}/submissions", json={**body, "captchaToken": token})
    assert res.json()["detail"] == "captcha_failed"
    fresh = (await client.get(f"{pub.base}/captcha")).json()
    assert fresh["challenge"] != challenge["challenge"]


async def test_captcha_when_busy(settings: Settings) -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    s = settings.model_copy(update={"captcha_provider": "altcha", "captcha_busy_threshold": 3})
    assert not await captcha.required(redis, s, "f1", {"captcha": "auto"})
    for _ in range(3):
        await ratelimit.record(redis, captcha.BUSY_COUNTER, "f1", 3600)
    assert await captcha.required(redis, s, "f1", {"captcha": "auto"})
    assert not await captcha.required(redis, s, "f1", {"captcha": "off"})
    assert not await captcha.required(redis, settings, "f1", {"captcha": "always"})  # no provider


def test_captcha_provider_needs_keys() -> None:
    with pytest.raises(ValueError, match="CAPTCHA"):
        Settings(environment="test", captcha_provider="turnstile")
    ok = Settings(
        environment="test",
        captcha_provider="hcaptcha",
        captcha_site_key="site",
        captcha_secret_key="secret",
    )
    assert ok.captcha_provider == "hcaptcha"


async def test_public_submit_rate_limit(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    statuses = []
    for _ in range(11):
        res = await client.post(f"{pub.base}/submissions", json=pub.submit_body({"name": "x"}))
        statuses.append(res.status_code)
    assert statuses[:10] == [201] * 10 and statuses[10] == 429
    statuses = []
    for _ in range(31):
        res = await client.post(
            f"{pub.base}/uploads",
            json={
                "fieldId": "nope",
                "name": "a.txt",
                "size": 1,
                "mime": "text/plain",
                "uploadNonce": pub.live["uploadNonce"],
            },
        )
        statuses.append(res.status_code)
    assert statuses[-1] == 429 and set(statuses[:30]) != {429}
