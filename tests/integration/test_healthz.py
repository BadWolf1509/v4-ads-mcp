import pytest
from httpx import ASGITransport, AsyncClient

from src.app import create_app


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app(skip_db_init=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_healthz_returns_200(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
