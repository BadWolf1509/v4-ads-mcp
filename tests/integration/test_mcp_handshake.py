from httpx import AsyncClient


async def test_mcp_initialize(client: AsyncClient) -> None:
    """Server responds to MCP initialize handshake."""
    response = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    assert "result" in body
    assert body["result"]["protocolVersion"] == "2024-11-05"
    assert body["result"]["serverInfo"]["name"] == "v4-ads-mcp"


async def test_mcp_tools_list_empty(client: AsyncClient) -> None:
    """tools/list returns an empty array at Phase 0."""
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["tools"] == []
