"""MCP server using the official Anthropic Python SDK with Streamable HTTP transport."""

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import anyio
import structlog
from fastapi import FastAPI, Request, Response
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.types import TextContent, Tool

from mcp.server import Server
from src.mcp.session import UnauthorizedError, resolve_session_to_context
from src.mcp.tools._registry import all_tools, get_tool, import_all_tools

SERVER_NAME = "v4-ads-mcp"
SERVER_VERSION = "0.1.0"

log = structlog.get_logger(__name__)

# ASGI callable types
_Scope = MutableMapping[str, Any]
_ASGIReceive = Callable[[], Awaitable[MutableMapping[str, Any]]]
_ASGISend = Callable[[MutableMapping[str, Any]], Awaitable[None]]

# Eagerly import all tool modules so their @register_tool decorators run.
import_all_tools()


def build_server() -> Any:
    """Construct the MCP Server with all registered tools."""
    server = Server(SERVER_NAME, version=SERVER_VERSION)

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[Tool]:
        # Expose bucket classification via MCP `_meta` field using reverse-DNS
        # namespacing per spec (com.v4company/bucket). Clients that introspect
        # tools/list response can route on this; the prefix tag in the
        # description (added by Task C) remains the primary signal for Claude's
        # client-side heuristic. `defer_loading` is a separate CLIENT-SIDE
        # Anthropic API parameter and is NOT exposed via MCP server metadata.
        return [
            Tool(
                name=t.name,
                description=t.description,
                inputSchema=t.input_schema,
                _meta={"com.v4company/bucket": t.bucket},
            )
            for t in all_tools()
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        import jsonschema  # noqa: PLC0415

        tool = get_tool(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        args = arguments or {}
        try:
            jsonschema.validate(args, tool.input_schema)
        except jsonschema.ValidationError as e:
            raise ValueError(
                f"Invalid arguments for tool '{name}': {e.message} "
                f"(at path: {'/'.join(str(p) for p in e.absolute_path) or '<root>'})"
            ) from e
        result = await tool.handler(args)
        # MCP requires tool result to be a list of content blocks; we return
        # a single TextContent with JSON-serialized payload.
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]

    return server


# Single shared MCP server instance (stateless — no per-session data)
_mcp_server = build_server()


def mount_mcp(app: FastAPI) -> None:
    """Mount the MCP server's Streamable HTTP transport at /mcp.

    Each request resolves the Bearer token to bind the manager context
    BEFORE the MCP handler runs. Phase 1a tightens this from Phase 0's
    no-auth stub — every /mcp request must carry a valid Bearer.
    """

    @app.post("/mcp")
    async def mcp_endpoint(request: Request) -> Response:
        # Resolve session → bind context. 401 on missing/invalid Bearer.
        try:
            await resolve_session_to_context(request.headers.get("authorization"))
        except UnauthorizedError as e:
            return Response(
                content=json.dumps({"error": "unauthorized", "message": str(e)}),
                status_code=401,
                headers={"content-type": "application/json"},
            )
        except Exception as e:
            log.warning("mcp_auth_error", error=str(e))
            return Response(
                content=json.dumps({"error": "internal_error", "message": str(e)}),
                status_code=500,
                headers={"content-type": "application/json"},
            )

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
