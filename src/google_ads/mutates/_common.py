"""Operation dispatcher — maps operation_type strings to mutate builders.

Each mutate builder takes (client, customer_id, payload) and returns
a list of MutateOperation messages ready to send via GoogleAdsService.mutate.

Tools register their builders here at import time so the apply_change
tool can dispatch by operation_type without coupling to specific tools.
"""

import contextlib
from collections.abc import Callable
from typing import Any

# Builder signature: (client, customer_id, payload) -> list of MutateOperations
MutateBuilder = Callable[[Any, str, dict[str, Any]], list[Any]]

_BUILDERS: dict[str, MutateBuilder] = {}


def register_builder(operation_type: str) -> Callable[[MutateBuilder], MutateBuilder]:
    """Decorator: registers a mutate builder for an operation type."""

    def decorator(fn: MutateBuilder) -> MutateBuilder:
        if operation_type in _BUILDERS:
            raise RuntimeError(f"Builder '{operation_type}' already registered")
        _BUILDERS[operation_type] = fn
        return fn

    return decorator


def get_builder(operation_type: str) -> MutateBuilder | None:
    return _BUILDERS.get(operation_type)


def reset() -> None:
    """Test helper."""
    _BUILDERS.clear()


def import_all_builders() -> None:
    """Eagerly import every mutate module so its register_builder runs.

    NOTE: at this stage only the module structure is in place; later tasks
    add the actual builder modules (campaigns, ad_groups, keywords,
    negatives, recommendations). Imports are wrapped in contextlib.suppress
    so incomplete state during build-out doesn't crash apply_change.
    """
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import campaigns  # type: ignore[attr-defined]  # noqa: F401
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import ad_groups  # type: ignore[attr-defined]  # noqa: F401
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import keywords  # type: ignore[attr-defined]  # noqa: F401
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import negatives  # type: ignore[attr-defined]  # noqa: F401
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import (  # type: ignore[attr-defined]
            recommendations,  # noqa: F401
        )
