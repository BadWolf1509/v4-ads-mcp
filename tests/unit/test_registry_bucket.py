"""Unit tests for @register_tool bucket parameter (Sprint 3b.39).

Isolation guard: cada test adiciona seu tool com nome único + pop só esse
nome ao final. NUNCA chamar reset() — global _TOOLS é populated por
import_all_tools() module-load + reset destroys it pra outros tests
(test_tools_schemas.py count check breaks).
"""

import pytest

from src.mcp.tools._registry import (
    _TOOLS,
    get_tool,
    register_tool,
)


def test_register_tool_default_bucket_is_defer():
    """Default bucket = 'defer' (conservative — explicitly opt-in to always-loaded)."""
    name = "test_default_bucket_defer"
    try:

        @register_tool(
            name=name,
            description="test",
            input_schema={"type": "object", "additionalProperties": False},
        )
        async def handler(args: dict) -> dict:
            return {}

        entry = get_tool(name)
        assert entry is not None
        assert entry.bucket == "defer"
    finally:
        _TOOLS.pop(name, None)


def test_register_tool_bucket_always():
    """bucket='always' marks tool as always-loaded (core/warm)."""
    name = "test_bucket_always_explicit"
    try:

        @register_tool(
            name=name,
            description="test",
            input_schema={"type": "object", "additionalProperties": False},
            bucket="always",
        )
        async def handler(args: dict) -> dict:
            return {}

        entry = get_tool(name)
        assert entry is not None
        assert entry.bucket == "always"
    finally:
        _TOOLS.pop(name, None)


def test_register_tool_bucket_invalid_raises():
    """Only 'always' OR 'defer' accepted."""
    name = "test_bucket_invalid_value"
    try:
        with pytest.raises(ValueError, match="bucket"):

            @register_tool(
                name=name,
                description="test",
                input_schema={"type": "object", "additionalProperties": False},
                bucket="other",  # type: ignore[arg-type]
            )
            async def handler(args: dict) -> dict:
                return {}
    finally:
        # Defensive cleanup — should never be in registry due to ValueError before insertion
        _TOOLS.pop(name, None)
