"""F190: o token de system user nao pode alcancar NENHUM sink de erro.

O SDK `facebook_business` assa o token na query string de toda requisicao
(`FacebookSession.__init__` faz `self.requests.params.update({'access_token': ...})`,
sem opt-out). `errors.py::to_friendly_meta_error` interpola `str(e)` cru no ramo
de fallback, que e justamente o ramo de TODA falha de transporte. O `str()` de uma
excecao de `requests`/`httpx` carrega a URL inteira.

Resultado: um soluco de rede manda o token para TRES destinos de uma vez —
`audit_log` (coluna TEXT no Postgres), Cloud Logging, e o envelope de erro que
chega ao contexto do LLM e a transcricao do chat. E o token que NAO expira e
alcanca ~24 contas de anuncio.

**Por que tres asserções e nao uma:** os tres sinks recebem o mesmo
`friendly.message` hoje, mas isso e coincidencia de implementacao, nao contrato.
Um refactor que formate o log separadamente reabriria o vazamento por um lado so
— e cobrir um lado so foi exatamente como o F82 ficou meio fechado.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

SENTINELA = "SENTINELA_TOKEN_NAO_E_SEGREDO"


def _pool() -> MagicMock:
    conn = AsyncMock()
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool


async def _falha_de_transporte_carregando_o_token() -> tuple[str, list[Any], list[Any]]:
    """Roda o executor contra um transporte que levanta com o token na mensagem.

    Devolve `(mensagem_amigavel, kwargs_do_audit, eventos_de_log)`.
    """
    from src.meta_ads import reports

    # A forma REAL da excecao: o transporte falha e a URL — com a query string —
    # vem dentro da mensagem. E assim que requests e httpx reportam.
    url_com_token = (
        f"https://graph.facebook.com/v22.0/act_1/insights?access_token={SENTINELA}&level=campaign"
    )
    erro = ConnectionError(f"Max retries exceeded with url: {url_com_token}")

    audit_chamadas: list[Any] = []
    eventos: list[Any] = []

    async def _audit(_conn: Any, **kwargs: Any) -> int:
        audit_chamadas.append(kwargs)
        return 1

    def _warning(evento: str, **kwargs: Any) -> None:
        eventos.append({"evento": evento, **kwargs})

    log_falso = MagicMock()
    log_falso.warning = _warning
    log_falso.info = MagicMock()

    api_falso = MagicMock()
    api_falso.call = MagicMock(side_effect=erro)

    with (  # noqa: SIM117
        patch.object(reports, "build_meta_api", MagicMock(return_value=api_falso)),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.connection, "get_pool", return_value=_pool()),
        patch.object(reports.audit_log, "record", _audit),
        patch.object(reports, "log", log_falso),
    ):
        with pytest.raises(Exception) as capturado:  # noqa: PT011 — tipo vem do modulo
            await reports.run_meta_graph_get(
                manager_id=uuid4(),
                session_id=uuid4(),
                ad_account_id="act_1",
                edge="/act_1/insights",
                params={"level": "campaign"},
                operation_name="meta_get_campaign_performance",
                audit_this_call=True,
            )

    mensagem = getattr(capturado.value, "message", str(capturado.value))
    return mensagem, audit_chamadas, eventos


@pytest.mark.asyncio
async def test_o_token_nao_aparece_na_mensagem_do_gestor() -> None:
    mensagem, _, _ = await _falha_de_transporte_carregando_o_token()
    assert SENTINELA not in mensagem, (
        "o token vazou na mensagem que chega ao gestor e ao contexto do LLM. "
        "`to_friendly_meta_error` interpola `str(e)` cru, e o `str()` de uma falha "
        "de transporte carrega a URL com a query string (F190)."
    )


@pytest.mark.asyncio
async def test_o_token_nao_aparece_no_audit_log() -> None:
    """Sink SEPARADO da mensagem, e o mais duradouro: coluna TEXT no Postgres."""
    _, audit_chamadas, _ = await _falha_de_transporte_carregando_o_token()
    assert audit_chamadas, (
        "piso de nao-vacuidade: o audit nao foi chamado, entao este teste nao "
        "afirmou nada sobre ele. Com `audit_this_call=True` e um erro, tem de haver "
        "exatamente uma escrita."
    )
    texto = repr(audit_chamadas)
    assert SENTINELA not in texto, (
        "o token vazou para o `audit_log` — a coluna e TEXT e a linha fica. "
        "Redigir so a mensagem do gestor nao fecha este sink (F190)."
    )


@pytest.mark.asyncio
async def test_o_token_nao_aparece_no_log_estruturado() -> None:
    """Terceiro sink: Cloud Logging, onde a retencao e longa e o acesso e amplo."""
    _, _, eventos = await _falha_de_transporte_carregando_o_token()
    assert eventos, (
        "piso de nao-vacuidade: nenhum evento de log foi emitido, entao este teste "
        "nao afirmou nada. O caminho de erro tem de logar."
    )
    texto = repr(eventos)
    assert SENTINELA not in texto, (
        "o token vazou para o log estruturado (Cloud Logging). Terceiro sink (F190)."
    )
