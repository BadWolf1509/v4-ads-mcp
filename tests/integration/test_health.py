import pytest
from httpx import AsyncClient


@pytest.mark.integration
async def test_health_returns_200(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.integration
async def test_health_deep_checks_db(client: AsyncClient) -> None:
    """?deep=1 faz SELECT 1 no pool; com o DB de teste up → 200 + db=ok.

    Antes /health era estático: um deploy com DB inacessível passava no smoke.
    O deep dá readiness real (503 'degraded' quando o SELECT 1 falha)."""
    response = await client.get("/health?deep=1")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
