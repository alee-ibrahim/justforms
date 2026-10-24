"""Test fixtures.

Tests marked with the ``db`` fixture need PostgreSQL: set ``JUSTFORMS_TEST_DATABASE_URL``
(e.g. ``postgresql+asyncpg://justforms:justforms@localhost:5432/justforms_test``). The database is
wiped and migrated with Alembic once per run, and tables are truncated between tests.
Without the variable those tests are skipped; CI always sets it. Redis is faked.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_DB_URL = os.environ.get("JUSTFORMS_TEST_DATABASE_URL")
os.environ["JUSTFORMS_ENVIRONMENT"] = "test"
os.environ.pop("JUSTFORMS_OIDC_ISSUER", None)
if TEST_DB_URL:
    os.environ["JUSTFORMS_DATABASE_URL"] = TEST_DB_URL

from app.auth.deps import storage_dep  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.queue import get_queue  # noqa: E402
from app.redis import get_redis  # noqa: E402
from app.storage import LocalStorage, Storage  # noqa: E402

TABLES = [
    "ai_messages",
    "ai_sessions",
    "approval_steps",
    "webhook_deliveries",
    "webhooks",
    "email_deliveries",
    "notification_rules",
    "exports",
    "imports",
    "signing_keys",
    "signatures",
    "submission_events",
    "files",
    "submissions",
    "audit_log",
    "form_draft_history",
    "form_permissions",
    "form_versions",
    "forms",
    "org_invitations",
    "org_memberships",
    "users",
    "organizations",
]


@dataclass
class RecordingQueue:
    jobs: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def enqueue(self, function: str, **kwargs: Any) -> None:
        self.jobs.append((function, kwargs))

    def last_code(self, email: str) -> str:
        for function, kwargs in reversed(self.jobs):
            if function == "send_email" and kwargs["to"] == email:
                match = re.search(r"\b(\d{6})\b", kwargs["text"])
                assert match
                return match.group(1)
        raise AssertionError(f"no code sent to {email}")


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    if not TEST_DB_URL:
        pytest.skip("JUSTFORMS_TEST_DATABASE_URL is not set")
    import asyncio

    from alembic.config import Config

    from alembic import command

    async def reset() -> None:
        engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await engine.dispose()

    asyncio.run(reset())
    get_settings.cache_clear()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.upgrade(cfg, "head")
    yield TEST_DB_URL
    command.downgrade(cfg, "base")


@pytest.fixture
async def db_engine(migrated_db: str) -> AsyncIterator[Any]:
    engine = create_async_engine(migrated_db, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(db_engine: Any) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test", oidc_issuer=None, public_url="http://testserver")


@pytest.fixture
def redis() -> FakeAsyncRedis:
    return FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture
def file_storage(tmp_path: Any) -> Storage:
    """Storage the app uses in tests; override this fixture to test another backend."""
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def app(
    db_engine: Any,
    settings: Settings,
    redis: FakeAsyncRedis,
    queue: RecordingQueue,
    file_storage: Storage,
) -> Any:
    application = create_app()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    async def _redis() -> FakeAsyncRedis:
        return redis

    async def _queue() -> RecordingQueue:
        return queue

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_redis] = _redis
    application.dependency_overrides[get_queue] = _queue
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[storage_dep] = lambda: file_storage
    return application


def make_client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    async with make_client(app) as c:
        yield c


async def login(client: AsyncClient, queue: RecordingQueue, email: str) -> dict[str, Any]:
    """Log ``client`` in through the local code flow; returns /auth/me."""
    res = await client.post("/api/v1/auth/local/request", json={"email": email})
    assert res.status_code == 202, res.text
    res = await client.post(
        "/api/v1/auth/local/verify", json={"email": email, "code": queue.last_code(email)}
    )
    assert res.status_code == 200, res.text
    client.headers["X-CSRF-Token"] = client.cookies["justforms_csrf"]
    return res.json()


@pytest.fixture(autouse=True)
def _no_logo_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Form imports never reach the network in tests: the Jotform logo download fails unless
    a test fakes it (tests of the downloader import the real ``fetch_logo`` directly)."""
    from app.importers.jotform import logo

    async def refuse(*_args: Any, **_kwargs: Any) -> bytes:
        raise logo.LogoError("fetch")

    monkeypatch.setattr(logo, "fetch_logo", refuse)
