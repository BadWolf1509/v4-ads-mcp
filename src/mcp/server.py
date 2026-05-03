"""MCP server stub. Real implementation in Task 8."""

from fastapi import FastAPI


def mount_mcp(app: FastAPI) -> None:
    """Mount the MCP transport at /mcp. Stubbed in Task 7, completed in Task 8."""

    @app.post("/mcp")
    async def mcp_stub() -> dict[str, list[str]]:
        return {"tools": []}
