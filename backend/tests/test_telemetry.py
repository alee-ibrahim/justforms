"""Error tracking: scrubbing (shared cases), SDK settings, the browser tunnel and /meta."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient

from app.auth.deps import get_redis
from app.config import Settings, get_settings, parse_dsn
from app.main import create_app
from app.telemetry import init_sentry, scrub, tunnel
from app.telemetry.scrub import scrub_event, scrub_text, scrub_url

SPEC = json.loads(
    (Path(__file__).resolve().parents[2] / "spec" / "telemetry" / "scrub.json").read_text(
        encoding="utf-8"
    )
)
DSN = "http://pubkey123@tracker.internal:8000/7"

# What respondents typed in the fixtures below; none of it may ever leave in an event.
ANSWERS = ["Aminath Ali", "aminath@example.org", "+9607771234", "A123456", "Hulhumale"]


@pytest.mark.parametrize("case", SPEC["text"], ids=[c["name"] for c in SPEC["text"]])
def test_shared_text_cases(case: dict[str, Any]) -> None:
    assert scrub_text(case["input"]) == case["output"]


@pytest.mark.parametrize("case", SPEC["url"], ids=[c["name"] for c in SPEC["url"]])
def test_shared_url_cases(case: dict[str, Any]) -> None:
    assert scrub_url(case["input"]) == case["output"]


@pytest.mark.parametrize("case", SPEC["events"], ids=[c["name"] for c in SPEC["events"]])
def test_shared_event_cases(case: dict[str, Any]) -> None:
    assert scrub_event(case["input"]) == case["output"]


def _event_with_answers() -> dict[str, Any]:
    return {
        "event_id": "a" * 32,
        "message": "submit failed for aminath@example.org",
        "user": {"email": "aminath@example.org", "username": "Aminath Ali"},
        "extra": {"answers": {"name": "Aminath Ali", "island": "Hulhumale"}},
        "breadcrumbs": {"values": [{"message": "typed Aminath Ali"}]},
        "request": {
            "url": "https://forms.example.org/apply?name=Aminath%20Ali",
            "data": {"name": "Aminath Ali"},
            "headers": {"Cookie": "justforms_session=abc", "Authorization": "Bearer xyz"},
            "cookies": {"justforms_session": "abc"},
            "query_string": "island=Hulhumale",
        },
        "contexts": {"answers": {"island": "Hulhumale"}, "runtime": {"name": "CPython"}},
        "exception": {
            "values": [
                {
                    "type": "ValidationError",
                    "value": (
                        "input_value='Aminath Ali', input_type=str; phone +9607771234; A123456"
                    ),
                    "stacktrace": {
                        "frames": [
                            {
                                "function": "submit",
                                "vars": {"answers": {"name": "Aminath Ali", "island": "Hulhumale"}},
                            }
                        ]
                    },
                }
            ]
        },
    }


def test_no_answer_value_survives_scrubbing() -> None:
    out = json.dumps(scrub.before_send(_event_with_answers(), {}))
    for value in [*ANSWERS, "Aminath", "justforms_session", "Bearer xyz"]:
        assert value not in out
    assert "ValidationError" in out and "submit" in out


def test_parse_dsn() -> None:
    dsn = parse_dsn(DSN)
    assert dsn is not None
    assert dsn.envelope_url == "http://tracker.internal:8000/api/7/envelope/"
    prefixed = parse_dsn("https://k@h.example/sub/path/42")
    assert (
        prefixed is not None
        and prefixed.envelope_url == "https://h.example/sub/path/api/42/envelope/"
    )
    for bad in (
        "tracker.internal/7",
        "ftp://k@h/1",
        "https://h/1",
        "https://k@h/x",
        "https://k@h/1?a=b",
    ):
        assert parse_dsn(bad) is None


def test_settings_reject_a_bad_dsn_and_browser_follows_server() -> None:
    with pytest.raises(ValueError, match="not a Sentry DSN"):
        Settings(sentry_dsn="nonsense")
    assert Settings(sentry_dsn=DSN).sentry_browser == DSN
    assert Settings(sentry_dsn=DSN, sentry_browser_dsn="off").sentry_browser is None
    assert Settings().sentry_browser is None


def test_sdk_is_off_without_a_dsn() -> None:
    assert init_sentry(Settings(), "api") is False
    assert init_sentry(Settings(sentry_dsn="off"), "api") is False


def test_sdk_options_keep_personal_data_out(monkeypatch: pytest.MonkeyPatch) -> None:
    import sentry_sdk

    seen: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: seen.update(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a: None)
    assert init_sentry(Settings(sentry_dsn=DSN, environment="test"), "worker") is True
    assert seen["send_default_pii"] is False
    assert seen["include_local_variables"] is False
    assert seen["max_breadcrumbs"] == 0
    assert seen["max_request_body_size"] == "never"
    assert seen["traces_sample_rate"] == 0.0
    assert seen["before_send"] is scrub.before_send
    assert seen["environment"] == "test"


# -- tunnel ---------------------------------------------------------------------------------


def envelope(dsn: str = DSN, *items: tuple[dict[str, Any], dict[str, Any] | bytes]) -> bytes:
    lines = [json.dumps({"dsn": dsn, "sent_at": "2026-10-28T00:00:00Z", "trace": {"user": "x"}})]
    for header, payload in items:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        lines.append(json.dumps(header))
        lines.append(body.decode())
    return ("\n".join(lines) + "\n").encode()


def test_clean_envelope_keeps_events_scrubbed_and_drops_other_items() -> None:
    dsn = parse_dsn(DSN)
    assert dsn is not None
    raw = envelope(
        DSN,
        ({"type": "event"}, _event_with_answers()),
        ({"type": "replay_recording"}, b'{"typed":"Aminath Ali"}'),
        ({"type": "user_report"}, {"email": "aminath@example.org", "comments": "Hulhumale"}),
        ({"type": "session"}, {"sid": "1"}),
        ({"type": "client_report"}, {"discarded_events": []}),
    )
    out = tunnel.clean_envelope(raw, dsn)
    assert out.items == 2
    text = out.body.decode()
    for value in ANSWERS:
        assert value not in text
    assert '"trace"' not in text  # envelope header trimmed to dsn/sent_at/sdk/event_id
    lines = out.body.split(b"\n")
    item = json.loads(lines[1])
    assert item["type"] == "event" and item["length"] == len(lines[2])


def test_clean_envelope_honours_item_length() -> None:
    dsn = parse_dsn(DSN)
    assert dsn is not None
    payload = json.dumps({"message": "line\nbreak A123456"}).encode()
    raw = (
        json.dumps({"dsn": DSN}).encode()
        + b"\n"
        + json.dumps({"type": "event", "length": len(payload)}).encode()
        + b"\n"
        + payload
    )
    out = tunnel.clean_envelope(raw, dsn)
    assert out.items == 1 and b"A123456" not in out.body


@pytest.mark.parametrize(
    "raw",
    [
        envelope("http://pubkey123@tracker.internal:8000/8"),  # another project
        envelope("http://otherkey@tracker.internal:8000/7"),  # another key
        b"not json\n",
        envelope(DSN, ({"type": "event", "length": 999}, b"{}")),
        b'{"dsn": "' + DSN.encode() + b'"}\n' + b'{"type":"event"}\n{"x":1}\n' * 25,
    ],
)
def test_clean_envelope_refuses(raw: bytes) -> None:
    dsn = parse_dsn(DSN)
    assert dsn is not None
    with pytest.raises(tunnel.EnvelopeError):
        tunnel.clean_envelope(raw, dsn)


@pytest.fixture
def tunnel_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    sent: list[tuple[str, bytes, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((str(request.url), request.content, dict(request.headers)))
        return httpx.Response(200)

    real = httpx.AsyncClient

    def fake_client(**kwargs: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(tunnel.httpx, "AsyncClient", fake_client)
    settings = Settings(environment="test", sentry_dsn=DSN, public_url="https://forms.example.org")
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    redis = FakeAsyncRedis(decode_responses=True)

    async def _redis() -> FakeAsyncRedis:
        return redis

    application.dependency_overrides[get_redis] = _redis
    return application, sent, settings


async def test_tunnel_forwards_only_to_the_configured_host(tunnel_client: Any) -> None:
    application, sent, _ = tunnel_client
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://t") as c:
        res = await c.post(
            "/api/v1/telemetry/envelope",
            content=envelope(DSN, ({"type": "event"}, _event_with_answers())),
            headers={"Content-Type": "text/plain;charset=UTF-8", "Host": "evil.example"},
        )
    assert res.status_code == 200
    assert len(sent) == 1
    url, body, headers = sent[0]
    assert url == "http://tracker.internal:8000/api/7/envelope/"
    assert "sentry_key=pubkey123" in headers["x-sentry-auth"]
    for value in ANSWERS:
        assert value.encode() not in body


async def test_tunnel_refuses_other_dsns_large_bodies_and_floods(tunnel_client: Any) -> None:
    application, sent, _ = tunnel_client
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://t") as c:
        other = envelope("https://pubkey123@attacker.example/8", ({"type": "event"}, {"x": 1}))
        assert (await c.post("/api/v1/telemetry/envelope", content=other)).status_code == 400
        big = b"x" * (tunnel.MAX_ENVELOPE_BYTES + 1)
        assert (await c.post("/api/v1/telemetry/envelope", content=big)).status_code == 413
        gz = await c.post(
            "/api/v1/telemetry/envelope", content=b"x", headers={"Content-Encoding": "gzip"}
        )
        assert gz.status_code == 415
        codes = [
            (await c.post("/api/v1/telemetry/envelope", content=b"{}\n")).status_code
            for _ in range(40)
        ]
    assert 429 in codes
    assert sent == []


async def test_tunnel_is_off_without_a_browser_dsn(tunnel_client: Any) -> None:
    application, _, _ = tunnel_client
    application.dependency_overrides[get_settings] = lambda: Settings(
        environment="test", sentry_dsn=DSN, sentry_browser_dsn="off"
    )
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://t") as c:
        res = await c.post("/api/v1/telemetry/envelope", content=envelope())
    assert res.status_code == 404


async def test_meta_gives_browsers_a_dsn_on_this_host(tunnel_client: Any) -> None:
    application, _, _ = tunnel_client
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://t") as c:
        meta = (await c.get("/api/v1/meta")).json()
    assert meta["telemetry"]["dsn"] == "https://pubkey123@forms.example.org/7"
    assert meta["telemetry"]["tunnel"] == "/api/v1/telemetry/envelope"
    assert meta["telemetry"]["tracesSampleRate"] == 0.0
    assert "tracker.internal" not in json.dumps(meta)
