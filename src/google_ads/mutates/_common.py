"""Operation dispatcher — maps operation_type strings to mutate builders.

Each mutate builder takes (client, customer_id, payload) and returns
a list of MutateOperation messages ready to send via GoogleAdsService.mutate.

Tools register their builders here at import time so the apply_change
tool can dispatch by operation_type without coupling to specific tools.
"""

import importlib
import pathlib
import pkgutil
from collections.abc import Callable
from typing import Any

import structlog

log = structlog.get_logger(__name__)

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
    """Importa TODO modulo do pacote para que seus `register_builder` rodem.

    Varre o pacote em vez de listar (F150). A versao anterior mantinha uma lista
    de imports escrita a mao, e ela DIVERGIU: `mutates/ad_schedule.py` declarava
    `@register_builder("update_ad_schedule")` mas nao estava na lista, entao o
    decorator nunca rodava. A tool foi para producao capaz de PREVER e incapaz de
    APLICAR — `apply_change` respondia "No mutate builder registered", e o gestor
    via so "Erro interno". Lista paralela mantida por memoria humana diverge; a
    unica fonte que nao diverge do pacote e o proprio pacote.

    Falha de import de UM modulo nao derruba os outros — mas tambem nao passa em
    silencio, que era a outra metade do problema: `contextlib.suppress` engolia
    tudo sem deixar rastro. Agora vira `log.exception`, alertavel.
    """
    for info in pkgutil.iter_modules([str(pathlib.Path(__file__).parent)]):
        if info.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{__package__}.{info.name}")
        except Exception:
            log.exception("mutate_builder_import_failed", modulo=info.name)
