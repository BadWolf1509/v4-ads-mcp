"""Decorator-based tool registry. Each tool module imports `register_tool` and
declares its handler + JSON schema in one place.

The MCP server (server.py) iterates `_TOOLS` to power list_tools and call_tool.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

# Each handler receives the parsed-input dict and returns a JSON-serializable result.
ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(slots=True, frozen=True)
class RegisteredTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    bucket: Literal["always", "defer"] = "defer"


_TOOLS: dict[str, RegisteredTool] = {}


def register_tool(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    bucket: Literal["always", "defer"] = "defer",
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator: registers the function as the handler for `name`.

    Args:
        name: Tool name (unique identifier).
        description: Tool description for list_tools.
        input_schema: JSON schema for tool inputs.
        bucket: Loading strategy. 'defer' (default) = opt-in via client parameter;
                'always' = core/warm tools that should be available immediately.
                Used for server-side metadata and grepability.

    Raises:
        ValueError: If bucket is not 'always' or 'defer'.
        RuntimeError: If tool name is already registered.
    """
    if bucket not in ("always", "defer"):
        raise ValueError(
            f"bucket must be 'always' or 'defer', got {bucket!r}"
        )

    def decorator(fn: ToolHandler) -> ToolHandler:
        if name in _TOOLS:
            raise RuntimeError(f"Tool '{name}' already registered")
        _TOOLS[name] = RegisteredTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=fn,
            bucket=bucket,
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
    """Import every tool module so its register_tool decorator runs.

    Auto-discovery via pkgutil — iterates non-private modules in this package.
    Avoids the manual import-list maintenance burden that bit Sprints 3b.12,
    3b.13, 3b.14 (new tools shipped but absent from old hardcoded list,
    dead in production despite passing unit tests via pytest import side
    effects).
    """
    import importlib
    import pkgutil

    from src.mcp import tools as tools_pkg

    for _, mod_name, _ in pkgutil.iter_modules(tools_pkg.__path__):
        if mod_name.startswith("_"):
            continue  # skip _registry, __init__, etc
        importlib.import_module(f"src.mcp.tools.{mod_name}")
