from httpx import ASGITransport, AsyncClient

from app import __version__
from app.main import app


async def test_health() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "version": __version__}
