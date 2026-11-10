"""Constantes e erros do lado Meta — sem SDK, sem I/O.

Este módulo já foi a fábrica do `FacebookAdsApi`. Depois do F190 o transporte
Meta é `httpx` direto (`reports.py::run_meta_graph_get`, token em
`Authorization: Bearer`), e o SDK `facebook_business` saiu das
dependências: nenhum caminho de request o usa. Sobraram aqui os nomes que o resto do código
importa:

- `META_GRAPH_API_VERSION` — a versão do Graph;
- `META_GRAPH_BASE_URL` — host + versão, a base que `reports.py`,
  `partnership.py` e `alcance.py` usam (o host só é escrito aqui);
- `MetaSystemUserTokenMissingError` e `MetaAccessDeniedError` — erros do gate
  do Modelo B, levantados por `reports.py`. As tools os capturam primeiro
  (`meta_erro`, em `src/mcp/tools/_meta_common.py`); `src/mcp/server.py` é só o
  fallback central e trata apenas o `MetaAccessDeniedError` (o de token ausente,
  que é um `MetaAdsFriendlyError`, ali cairia no erro genérico).

`build_meta_api` e `build_facebook_ads_api` foram **removidos** (F190, Tasks 6 e
onda final): depois da troca de transporte os dois ficaram com **zero
consumidores em `src/`** — medido, não estimado —, e código morto com teste
verde é pior que código morto, porque parece cobertura. A convenção do F48
(nunca `FacebookAdsApi.init()`, sempre a ponte `FacebookSession`) fica
registrada no catálogo: ela vale se alguém algum dia trouxer o SDK de volta,
mas não há mais call site que a aplique.
"""

from dataclasses import dataclass

from src.meta_ads.errors import MetaAdsFriendlyError

# Meta Graph API version used across all Meta Graph call sites.
META_GRAPH_API_VERSION = "v25.0"

# A base da Graph, montada UMA vez aqui (guard `test_host_da_graph_so_no_client`):
# `alcance.py`, `partnership.py` e `reports.py` importam esta constante em vez de
# remontar o host com a versão.
META_GRAPH_BASE_URL = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}"


@dataclass(slots=True, frozen=True)
class MetaSystemUserTokenMissingError(MetaAdsFriendlyError):
    """Raised when the shared system-user token secret isn't configured.

    É um `MetaAdsFriendlyError`: a mensagem PT-BR (acionável pro admin) chega ao
    gestor como `error` pelas tools Meta, em vez de "Erro interno". Não é transitório.
    """

    retryable: bool = False


class MetaAccessDeniedError(Exception):
    """Raised when a manager has no grant for the requested Meta ad account."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
