"""Compatibilidade de campos GAQL via GoogleAdsFieldService (M3).

`selectable_with` do Google e a fonte autoritativa de quais segments/metrics
combinam com um resource; o catalogo curado nao a replica (duas fontes
divergem). O metadado nao depende da conta, mas o acesso a esta consulta passa
pelo hard-gate de leitura (`ensure_account_access`) em TODA chamada, inclusive cache
hit, dentro de `compatibilidade` — e onde o guard F57 o enxerga. So a chamada ao
Google e cacheada.
"""

import re
from typing import Any
from uuid import UUID

from src.blocking import run_blocking
from src.db import connection
from src.google_ads.access import ensure_account_access
from src.google_ads.client import build_client_for_manager

try:  # a versao que o SDK usa por padrao e a que `build_client` instancia
    from google.ads.googleads.client import _DEFAULT_VERSION as _VERSAO_SDK
except ImportError:  # pragma: no cover - SDK sem o simbolo privado
    _VERSAO_SDK = "v25"

VERSAO_API: str = _VERSAO_SDK
FONTE: str = f"GoogleAdsFieldService {VERSAO_API}"

_RESOURCE_RE = re.compile(r"^[a-z_]+$")

# (versao da API, resource) -> compatibilidade. So resultado de sucesso entra.
_CACHE: dict[tuple[str, str], dict[str, list[str]]] = {}


def limpar_cache() -> None:
    _CACHE.clear()


def do_cache(resource: str) -> dict[str, list[str]] | None:
    return _CACHE.get((VERSAO_API, resource))


def _separar(selectable_with: list[str]) -> dict[str, list[str]]:
    segments = sorted(s for s in selectable_with if s.startswith("segments."))
    metrics = sorted(s for s in selectable_with if s.startswith("metrics."))
    resto = sorted(s for s in selectable_with if not s.startswith(("segments.", "metrics.")))
    return {"segments": segments, "metrics": metrics, "resources_atribuidos": resto}


async def compatibilidade(
    resource: str, *, manager_id: UUID, customer_id: str, session_id: UUID
) -> dict[str, list[str]] | None:
    """Campos que combinam com `resource`; None se o Google nao conhece o resource.

    Levanta em falha de API/credencial (o chamador converte em `compativel: None`
    com motivo, nunca em lista vazia). Resultado de sucesso e cacheado.
    """
    if not _RESOURCE_RE.fullmatch(resource):
        raise ValueError("resource invalido")
    # F57: o gate roda em TODA chamada (inclusive cache hit); so a chamada ao Google
    # e cacheada. O metadado nao depende da conta, o acesso a esta tool sim.
    await connection.run_with_reconnect(
        lambda conn: ensure_account_access(
            conn,
            manager_id=manager_id,
            customer_id=customer_id,
            session_id=session_id,
            operation_name="list_gaql_resources",
            level="read",
        )
    )
    em_cache = do_cache(resource)
    if em_cache is not None:
        return em_cache

    client = await build_client_for_manager(manager_id=manager_id)
    service = client.get_service("GoogleAdsFieldService")
    query = f"SELECT name, selectable_with WHERE name = '{resource}'"

    def _buscar() -> list[Any]:
        return list(service.search_google_ads_fields(query=query))

    linhas = await run_blocking(_buscar)
    for linha in linhas:
        if linha.name == resource:
            resultado = _separar(list(linha.selectable_with))
            _CACHE[(VERSAO_API, resource)] = resultado
            return resultado
    return None
