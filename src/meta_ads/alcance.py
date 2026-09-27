"""O alcance do system user, medido pela leitura — não pelo índice (F154).

`/me/adaccounts` lista o inventário PRÓPRIO do system user, e em 27/09 omitia a CHUTE 07,
que o SU lê (`/insights` 200). O sinal `su_reachable` passou a vir de uma leitura mínima de
cada conta da parceria, na forma exata das tools (`build_insights_call`): a capacidade que
o painel promete, não um índice que a aproxima (spec 2026-09-27).

Três estados. Assinaturas medidas em 27/09 contra a Graph API: conta lida → 200; conta sem
acesso ou id inexistente → 403 com `error.code == 200`; token inválido → 401 com
`code == 190`. Só a recusa medida vira "recusa"; todo o resto é "não medido", que não grava:
ausência de medição não é resposta (F191/F194).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx
import structlog

from src.clock import account_today
from src.meta_ads.client import META_GRAPH_API_VERSION
from src.meta_ads.insights import build_insights_call

log = structlog.get_logger(__name__)

_GRAPH = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}"

# O cliente do job usa 60 s; 25 contas penduradas seriam 25 minutos de job.
TIMEOUT_DA_SONDA = 15.0

# A única recusa medida (27/09): "(#200) Ad account owner has NOT grant ads_management or
# ads_read permission". Um código de recusa que ainda não vimos sai como não medido — não
# marca conta como inalcançável sem prova.
_CODIGO_DA_RECUSA = 200

Estado = Literal["le", "recusa", "nao_medido"]


def classificar_sonda(status_code: int, corpo: Any) -> Estado:
    """Resposta da sonda → lê | recusa | não medido."""
    if status_code == 200:
        return "le"
    erro = corpo.get("error") if isinstance(corpo, dict) else None
    if (
        400 <= status_code < 500
        and isinstance(erro, dict)
        and erro.get("code") == _CODIGO_DA_RECUSA
    ):
        return "recusa"
    return "nao_medido"


@dataclass(frozen=True, slots=True)
class Alcance:
    le: frozenset[str] = frozenset()
    recusa: frozenset[str] = frozenset()
    nao_medido: frozenset[str] = frozenset()


async def sondar_alcance(
    http: httpx.AsyncClient,
    *,
    access_token: str,
    contas: list[tuple[str, str | None]],
    agora: datetime,
) -> Alcance:
    """Uma leitura mínima por conta — `(ad_account_id, fuso)` → o estado de cada uma.

    "Ontem" é no fuso da conta, sobre o instante que o job lê uma vez (F141). Conta sem
    entrega ontem devolve 200 com `data` vazia: continua sendo "lê" — a pergunta é o
    acesso, não o gasto.
    """
    cabecalho = {"Authorization": f"Bearer {access_token}"}
    por_estado: dict[Estado, set[str]] = {"le": set(), "recusa": set(), "nao_medido": set()}
    for ad_account_id, fuso in contas:
        ontem = account_today(fuso, now=agora) - timedelta(days=1)
        edge, params = build_insights_call(
            level="account", ad_account_id=ad_account_id, start=ontem, end=ontem, limit=1
        )
        try:
            resposta = await http.get(
                _GRAPH + edge, params=params, headers=cabecalho, timeout=TIMEOUT_DA_SONDA
            )
            try:
                corpo = resposta.json()
            except ValueError:
                corpo = None
            estado = classificar_sonda(resposta.status_code, corpo)
        except httpx.HTTPError:
            estado = "nao_medido"
        por_estado[estado].add(ad_account_id)
    if por_estado["nao_medido"]:
        log.warning(
            "meta_alcance_nao_medido",
            total=len(por_estado["nao_medido"]),
            ad_account_ids=sorted(por_estado["nao_medido"]),
        )
    return Alcance(
        le=frozenset(por_estado["le"]),
        recusa=frozenset(por_estado["recusa"]),
        nao_medido=frozenset(por_estado["nao_medido"]),
    )
