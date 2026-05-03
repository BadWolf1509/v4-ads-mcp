"""MCP server using the official Anthropic Python SDK with Streamable HTTP transport."""

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import anyio
from fastapi import FastAPI, Request, Response
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.types import Tool

from mcp.server import Server

SERVER_NAME = "v4-ads-mcp"
SERVER_VERSION = "0.1.0"

# ASGI callable types
_Scope = MutableMapping[str, Any]
_ASGIReceive = Callable[[], Awaitable[MutableMapping[str, Any]]]
_ASGISend = Callable[[MutableMapping[str, Any]], Awaitable[None]]


def build_server() -> Any:
    """Construct the MCP Server. At Phase 0, no tools are registered."""
    server = Server(SERVER_NAME, version=SERVER_VERSION)

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[Tool]:
        return []

    return server


# Single shared MCP server instance (stateless — no per-session data)
_mcp_server = build_server()


def mount_mcp(app: FastAPI) -> None:
    """Mount the MCP server's Streamable HTTP transport at /mcp.

    Each request gets its own fresh StreamableHTTPServerTransport (stateless mode).
    JSON responses are enabled so callers get application/json back directly.
    No lifespan integration needed — anyio.create_task_group() scopes each request.
    """

    @app.post("/mcp")
    async def mcp_endpoint(request: Request) -> Response:
        """Handle MCP JSON-RPC requests via Streamable HTTP transport."""
        http_transport = StreamableHTTPServerTransport(
            mcp_session_id=None,
            is_json_response_enabled=True,
        )

        # Collect ASGI response parts
        response_status = 200
        response_headers: list[tuple[bytes, bytes]] = []
        response_body = bytearray()

        async def receive() -> MutableMapping[str, Any]:
            body = await request.body()
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: MutableMapping[str, Any]) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = int(message["status"])
                response_headers.extend(message.get("headers", []))
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))

        # Run the server and handle the HTTP request concurrently within one task group
        async with anyio.create_task_group() as tg:

            async def run_server(
                *, task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED
            ) -> None:
                async with http_transport.connect() as streams:
                    read_stream, write_stream = streams
                    task_status.started()
                    await _mcp_server.run(
                        read_stream,
                        write_stream,
                        _mcp_server.create_initialization_options(),
                        stateless=True,
                    )

            await tg.start(run_server)
            await http_transport.handle_request(request.scope, receive, send)
            await http_transport.terminate()
            tg.cancel_scope.cancel()

        return Response(
            content=bytes(response_body),
            status_code=response_status,
            headers={k.decode(): v.decode() for k, v in response_headers},
        )
