"""Per-request MCP context — manager_id and session_id available to tool handlers.

Stored in contextvars so async tool handlers (which don't get the request
object directly) can access it.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True, frozen=True)
class McpRequestContext:
    manager_id: UUID
    session_id: UUID


_current: ContextVar[McpRequestContext | None] = ContextVar("mcp_request_context", default=None)


def set_current(ctx: McpRequestContext) -> None:
    _current.set(ctx)


def clear_current() -> None:
    _current.set(None)


def get_current() -> McpRequestContext:
    """Return the current request context. Raises if not set (programmer error)."""
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError(
            "No MCP request context bound — middleware must run before tool handlers"
        )
    return ctx
