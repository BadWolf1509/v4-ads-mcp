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

    Imports are wrapped in contextlib.suppress(ImportError) defensively
    so a missing builder module doesn't crash apply_change at startup.
    """
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import campaigns  # noqa: F401
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import ad_groups  # noqa: F401
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import ads  # noqa: F401
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import bulk  # noqa: F401
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import keywords  # noqa: F401
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import negatives  # noqa: F401
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import recommendations  # noqa: F401
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import audiences  # noqa: F401
    with contextlib.suppress(ImportError):
        from src.google_ads.mutates import conversion_actions  # noqa: F401
