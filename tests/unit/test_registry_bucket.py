"""Unit tests for @register_tool bucket parameter (Sprint 3b.39)."""

import pytest

from src.mcp.tools._registry import (
    RegisteredTool,
    register_tool,
    get_tool,
    reset,
)


def test_register_tool_default_bucket_is_defer():
    """Default bucket = 'defer' (conservative — explicitly opt-in to always-loaded)."""
    reset()

    @register_tool(
        name="test_default",
        description="test",
        input_schema={"type": "object", "additionalProperties": False},
    )
    async def handler(args: dict) -> dict:
        return {}

    entry = get_tool("test_default")
    assert entry is not None
    assert entry.bucket == "defer"
    reset()


def test_register_tool_bucket_always():
    """bucket='always' marks tool as always-loaded (core/warm)."""
    reset()

    @register_tool(
        name="test_always",
        description="test",
        input_schema={"type": "object", "additionalProperties": False},
        bucket="always",
    )
    async def handler(args: dict) -> dict:
        return {}

    entry = get_tool("test_always")
    assert entry is not None
    assert entry.bucket == "always"
    reset()


def test_register_tool_bucket_invalid_raises():
    """Only 'always' OR 'defer' accepted."""
    reset()

    with pytest.raises(ValueError, match="bucket"):

        @register_tool(
            name="test_invalid",
            description="test",
            input_schema={"type": "object", "additionalProperties": False},
            bucket="other",  # type: ignore[arg-type]
        )
        async def handler(args: dict) -> dict:
            return {}

    reset()
