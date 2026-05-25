"""Unit tests for MCP server exposing bucket as _meta field (Sprint 3b.39 Task D).

MCP SDK 1.22.0 Tool type supports `meta: dict | None = Field(alias="_meta", default=None)`.
We expose the registry's bucket classification as `_meta["com.v4company/bucket"]` per MCP
namespacing convention (reverse DNS prefix, slash separator). See:
https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/draft/basic/index.mdx

Note: `defer_loading` is a CLIENT-SIDE Anthropic API parameter, NOT MCP server metadata.
This _meta exposure is structured metadata for clients that want to introspect bucket
classification (nice-to-have; the prefix tag in description from Task C remains the
primary signal for Claude's heuristic).
"""

from collections.abc import Iterator
from typing import Any

import pytest
from mcp.types import Tool

from src.mcp.tools._registry import _TOOLS, register_tool


@pytest.fixture
def _isolated_registry() -> Iterator[None]:
    """Snapshot the registry, yield empty, then restore on teardown.

    Avoids `reset()` clearing all real tools and breaking tests that run after
    this one (e.g. test_tools_schemas relies on the auto-imported registry).
    """
    snapshot = dict(_TOOLS)
    _TOOLS.clear()
    try:
        yield
    finally:
        _TOOLS.clear()
        _TOOLS.update(snapshot)


def test_list_tools_exposes_bucket_via_meta_field(_isolated_registry: None) -> None:
    """build_server().list_tools() must include _meta["com.v4company/bucket"] = entry.bucket.

    Verifies:
    - meta dict is populated (not None)
    - reverse-DNS namespaced key matches MCP spec
    - value matches the registered bucket ("always" or "defer")
    - JSON serialization uses "_meta" alias on the wire
    """

    @register_tool(
        name="test_always_meta",
        description="test always",
        input_schema={"type": "object", "additionalProperties": False},
        bucket="always",
    )
    async def _h1(args: dict[str, Any]) -> dict[str, Any]:
        return {}

    @register_tool(
        name="test_defer_meta",
        description="test defer",
        input_schema={"type": "object", "additionalProperties": False},
        bucket="defer",
    )
    async def _h2(args: dict[str, Any]) -> dict[str, Any]:
        return {}

    # Build Tool objects the same way server.build_server() does.
    # We test the Tool construction directly to avoid spinning up the
    # full MCP Server + ASGI machinery in a unit test.
    tools = [
        Tool(
            name=t.name,
            description=t.description,
            inputSchema=t.input_schema,
            _meta={"com.v4company/bucket": t.bucket},
        )
        for t in _TOOLS.values()
    ]

    by_name = {t.name: t for t in tools}

    # meta attribute populated correctly
    assert by_name["test_always_meta"].meta == {"com.v4company/bucket": "always"}
    assert by_name["test_defer_meta"].meta == {"com.v4company/bucket": "defer"}

    # Wire serialization uses "_meta" alias (the MCP spec field name)
    always_dumped = by_name["test_always_meta"].model_dump(by_alias=True, exclude_none=True)
    assert "_meta" in always_dumped
    assert always_dumped["_meta"] == {"com.v4company/bucket": "always"}
    # Sanity: NOT serialized under the Python attr name
    assert "meta" not in always_dumped


def test_build_server_list_tools_includes_meta_for_all_registered_tools() -> None:
    """End-to-end: build_server() wires bucket -> _meta for every registered tool."""
    # Import the real server module — it auto-imports all tools on module load.
    # We don't reset() here because we want to assert real production tools have meta.
    from src.mcp.server import build_server  # noqa: PLC0415

    server = build_server()

    # The Server class registers the list_tools handler internally. We exercise
    # it via the request_handlers dispatch table.
    from mcp.types import ListToolsRequest  # noqa: PLC0415

    handler = server.request_handlers.get(ListToolsRequest)
    assert handler is not None, "list_tools handler must be registered"

    # Invoke the handler directly. It's an async function; run via anyio.
    import anyio  # noqa: PLC0415

    request = ListToolsRequest(method="tools/list", params=None)

    async def _run() -> Any:
        return await handler(request)

    server_result = anyio.run(_run)
    # server_result is a ServerResult wrapping ListToolsResult
    tools_list = server_result.root.tools

    assert len(tools_list) > 0, "registry must have at least one tool"

    # Every tool must have _meta populated with the v4 bucket key
    for tool in tools_list:
        assert tool.meta is not None, f"tool {tool.name} missing _meta"
        assert "com.v4company/bucket" in tool.meta, (
            f"tool {tool.name} missing com.v4company/bucket in _meta"
        )
        assert tool.meta["com.v4company/bucket"] in ("always", "defer"), (
            f"tool {tool.name} has invalid bucket value {tool.meta['com.v4company/bucket']!r}"
        )


def test_build_tool_meta_always_includes_anthropic_alwaysload() -> None:
    """D3 finding (Sprint 3b.39 fix): bucket='always' tools must include
    'anthropic/alwaysLoad': True in _meta. This is Claude Code's standard
    mechanism for opting tools out of default Tool Search deferral.

    Without this field, Claude Code defaults all MCP tools to deferred
    (ENABLE_TOOL_SEARCH=true default in v2.x). Tools with the field are
    promoted to always-loaded in context.
    """
    from src.mcp.server import _build_tool_meta  # noqa: PLC0415

    meta_always = _build_tool_meta("always")
    assert meta_always == {
        "com.v4company/bucket": "always",
        "anthropic/alwaysLoad": True,
    }


def test_build_tool_meta_defer_omits_anthropic_alwaysload() -> None:
    """D3 finding: bucket='defer' tools must NOT include anthropic/alwaysLoad.
    Absence of the field tells Claude Code to use default behavior (deferred
    via Tool Search). Explicit False would still allow Claude to load them.
    """
    from src.mcp.server import _build_tool_meta  # noqa: PLC0415

    meta_defer = _build_tool_meta("defer")
    assert meta_defer == {"com.v4company/bucket": "defer"}
    assert "anthropic/alwaysLoad" not in meta_defer


def test_list_tools_anthropic_alwaysload_count_matches_always_bucket() -> None:
    """End-to-end D3 regression: number of tools with 'anthropic/alwaysLoad': True
    in list_tools response must equal number of bucket='always' tools in registry.

    Verifies the fix is plumbed end-to-end through Tool construction + serialization.
    """
    import anyio  # noqa: PLC0415
    from mcp.types import ListToolsRequest  # noqa: PLC0415

    from src.mcp.server import build_server  # noqa: PLC0415
    from src.mcp.tools._registry import _TOOLS  # noqa: PLC0415

    expected_always = sum(1 for t in _TOOLS.values() if t.bucket == "always")

    server = build_server()
    handler = server.request_handlers[ListToolsRequest]
    request = ListToolsRequest(method="tools/list", params=None)

    async def _run() -> Any:
        return await handler(request)

    result = anyio.run(_run)
    tools_list = result.root.tools

    actual_alwaysload = sum(
        1 for t in tools_list if t.meta and t.meta.get("anthropic/alwaysLoad") is True
    )

    assert actual_alwaysload == expected_always, (
        f"Expected {expected_always} tools with anthropic/alwaysLoad=True, "
        f"got {actual_alwaysload}. Registry/list_tools out of sync."
    )
