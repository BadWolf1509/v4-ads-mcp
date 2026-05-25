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


def _build_tool_meta(bucket: str) -> dict[str, Any]:
    """Build _meta dict for a tool based on its bucket classification.

    Returns:
        - V4-specific: 'com.v4company/bucket' = 'always' or 'defer' (always present)
        - Anthropic standard: 'anthropic/alwaysLoad' = True (ONLY when bucket='always')

    The anthropic/alwaysLoad field is the standard MCP mechanism for opting
    individual tools out of Claude Code's default tool-search deferral
    (ENABLE_TOOL_SEARCH=true default in Claude Code v2.x). Tools without this
    field default to deferred — exactly what we want for bucket='defer'.

    D3 finding (Sprint 3b.39): D2 originally assumed defer_loading was
    client-side settings.json. Real mechanism is server-side per-tool _meta
    via anthropic/alwaysLoad. Docs reference:
    https://code.claude.com/docs/en/mcp#scale-with-mcp-tool-search
    """
    meta: dict[str, Any] = {"com.v4company/bucket": bucket}
    if bucket == "always":
        meta["anthropic/alwaysLoad"] = True
    return meta


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
        # Expose bucket classification via 2 _meta fields:
        #
        # 1. `com.v4company/bucket` (always present) — reverse-DNS namespacing
        #    per MCP spec, value "always" or "defer". V4-specific introspection.
        #
        # 2. `anthropic/alwaysLoad` (only when bucket="always") — Anthropic Claude
        #    Code standard MCP field (D3 finding 3b.39). With ENABLE_TOOL_SEARCH
        #    default-on in Claude Code v2.x, all MCP tools default to deferred
        #    (on-demand via tool search). Setting `alwaysLoad: true` per-tool
        #    promotes specific tools to always-loaded in context. This is the
        #    correct mechanism for Sprint 3b.39 F1 — NOT client-side settings.json
        #    config (that schema doesn't exist in Claude Code, D2 was wrong about
        #    location). Defer tools (bucket="defer") get no anthropic/alwaysLoad
        #    field → Claude Code defaults to deferred (via Tool Search).
        #
        # Docs ref: https://code.claude.com/docs/en/mcp#scale-with-mcp-tool-search
        return [
            Tool(
                name=t.name,
                description=t.description,
                inputSchema=t.input_schema,
                _meta=_build_tool_meta(t.bucket),
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
