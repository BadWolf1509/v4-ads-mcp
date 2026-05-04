"""Decorator-based tool registry. Each tool module imports `register_tool` and
declares its handler + JSON schema in one place.

The MCP server (server.py) iterates `_TOOLS` to power list_tools and call_tool.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# Each handler receives the parsed-input dict and returns a JSON-serializable result.
ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(slots=True, frozen=True)
class RegisteredTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


_TOOLS: dict[str, RegisteredTool] = {}


def register_tool(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator: registers the function as the handler for `name`."""

    def decorator(fn: ToolHandler) -> ToolHandler:
        if name in _TOOLS:
            raise RuntimeError(f"Tool '{name}' already registered")
        _TOOLS[name] = RegisteredTool(
            name=name, description=description, input_schema=input_schema, handler=fn
        )
        return fn

    return decorator


def all_tools() -> list[RegisteredTool]:
    return list(_TOOLS.values())


def get_tool(name: str) -> RegisteredTool | None:
    return _TOOLS.get(name)


def reset() -> None:
    """Test helper — clear the registry between tests."""
    _TOOLS.clear()


def import_all_tools() -> None:
    """Import every tool module so its register_tool decorator runs."""
    from src.mcp.tools import (  # noqa: F401
        get_account_overview,
        get_ad_group_performance,
        get_budget_pacing,
        get_campaign_performance,
        get_device_performance,
        get_geo_performance,
        get_hourly_performance,
        get_recommendations,
        list_my_accounts,
    )
