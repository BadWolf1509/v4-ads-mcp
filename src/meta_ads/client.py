"""Constantes e erros do lado Meta — sem SDK, sem I/O.

Este módulo já foi a fábrica do `FacebookAdsApi`. Depois do F190 o transporte
Meta é `httpx` direto (`reports.py::run_meta_graph_get`, token em
`Authorization: Bearer`), e **nenhum caminho de request constrói cliente do
SDK `facebook_business`**. Sobraram aqui os três nomes que o resto do código
importa:

- `META_GRAPH_API_VERSION` — a versão do Graph usada por `reports.py` e
  `partnership.py`;
- `MetaSystemUserTokenMissingError` e `MetaAccessDeniedError` — erros do gate
  do Modelo B, levantados por `reports.py` e tratados em `src/mcp/server.py`.

`build_meta_api` e `build_facebook_ads_api` foram **removidos** (F190, Tasks 6 e
onda final): depois da troca de transporte os dois ficaram com **zero
consumidores em `src/`** — medido, não estimado —, e código morto com teste
verde é pior que código morto, porque parece cobertura. A convenção do F48
(nunca `FacebookAdsApi.init()`, sempre a ponte `FacebookSession`) fica
registrada no catálogo: ela vale se alguém algum dia trouxer o SDK de volta,
mas não há mais call site que a aplique.
"""

# Meta Graph API version used across all Meta Graph call sites.
META_GRAPH_API_VERSION = "v22.0"


class MetaSystemUserTokenMissingError(Exception):
    """Raised when the shared system-user token secret isn't configured."""


class MetaAccessDeniedError(Exception):
    """Raised when a manager has no grant for the requested Meta ad account."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
