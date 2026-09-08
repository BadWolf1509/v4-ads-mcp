"""Teto INTERNO do `detect_drift`: a varredura tem que declarar o que nao viu.

Ate a Task 5 a tool chamava `get_change_history` com `limit: 500` fixo — teto
que o gestor nunca pediu e que a resposta nunca mencionava. Numa janela com
mais de 500 eventos o excedente sumia ANTES de qualquer classificacao: a tool
que existe para responder "mudou algo que nao devia?" respondia sobre uma
amostra, e o `truncated` que ela devolvia falava de outra coisa (o `limit` do
gestor sobre `changes[]`).

Fatos MEDIDOS do recurso `change_event` (2026-09-07, conta 786-223-0676, via
`validate_gaql`) — sao eles que decidem o desenho testado aqui:

1. `LIMIT` e OBRIGATORIO e o teto e 10k ("Change event requests must specify a
   LIMIT in query and LIMIT should be less than or equal to 10k").
2. NAO existe OFFSET nem cursor para o recurso. A unica forma de passar de 10k
   e particionar o TEMPO (`change_event.change_date_time BETWEEN ...`).
3. `get_change_history` recebe data em granularidade de DIA — entao a particao
   mais fina alcancavel por este caminho e UM DIA. Dia que sozinho estoura o
   cap e limite da API, e limite declarado nao e mentira.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current

_HOJE = date(2026, 9, 8)

# Espelha o contrato do `get_change_history` (F131). Os testes daqui nao falam
# de frescor, mas a `detect_drift` propaga o bloco e quebraria sem ele.
_FRESHNESS = {
    "account_frontier": "2026-09-07 18:00:00",
    "slice_frontier": "2026-09-07 11:43:39",
    "status": "confiavel",
    "warning": None,
}


async def _hoje_fixo(customer_id: str, *, now: Any = None) -> date:
    return _HOJE


def _evento(dia: date, i: int) -> dict[str, Any]:
    """Uma linha no formato que `get_change_history` devolve.

    `i` conta segundos PARA TRAS a partir de 23:59:59, entao a lista de um dia
    ja nasce DESC por `change_date_time` — a mesma ordem em que o Google
    devolve (`ORDER BY change_event.change_date_time DESC`). Sem isso, um teste
    de "o corte cai no passado" nao teria como distinguir corte de embaralho.
    """
    hora, resto = divmod(86_399 - i, 3600)
    minuto, segundo = divmod(resto, 60)
    return {
        "change_date_time": f"{dia.isoformat()} {hora:02d}:{minuto:02d}:{segundo:02d}",
        "user_email": "intruso@external.com",
        "client_type": "GOOGLE_ADS_WEB_CLIENT",
        "resource_type": "CAMPAIGN",
        "resource_id": f"{dia.isoformat()}-{i}",
        "resource_name": "C",
        "operation": "UPDATE",
        "changed_fields": ["campaign.name"],
        "campaign_id": "22169885957",
        "ad_group_id": None,
        "old_status": None,
        "new_status": None,
    }


class _HistoricoFalso:
    """Duble do `get_change_history` DEPOIS da Task 2.

    Respeita `limit`, corta pelas linhas MAIS RECENTES e declara `truncated` —
    esse e o contrato real da tool, nao uma conveniencia deste teste. Guarda as
    chamadas: e por elas que se ve QUAL teto a `detect_drift` pediu e em quantas
    sub-janelas ela leu.
    """

    def __init__(self, universo: dict[date, int]) -> None:
        self._por_dia = {d: [_evento(d, i) for i in range(n)] for d, n in universo.items()}
        self.chamadas: list[tuple[str, str, int]] = []

    async def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
        inicio = date.fromisoformat(args["start_date"])
        fim = date.fromisoformat(args["end_date"])
        limite = args["limit"]
        self.chamadas.append((args["start_date"], args["end_date"], limite))
        linhas = [
            linha
            for dia in sorted(self._por_dia, reverse=True)
            if inicio <= dia <= fim
            for linha in self._por_dia[dia]
        ]
        return {
            "customer_id": args["customer_id"],
            "period": {"from": inicio.isoformat(), "to": fim.isoformat()},
            "rows": linhas[:limite],
            "truncated": len(linhas) > limite,
            "summary": {},
            "freshness": dict(_FRESHNESS),
        }


@pytest.fixture
def _ctx() -> Iterator[McpRequestContext]:
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


async def _rodar(historico: _HistoricoFalso, args: dict[str, Any]) -> dict[str, Any]:
    from src.mcp.tools.detect_drift import detect_drift

    with (
        patch("src.mcp.tools.detect_drift.get_change_history", historico),
        patch("src.mcp.tools.detect_drift.resolve_account_today", _hoje_fixo),
    ):
        return await detect_drift(args)


def _dias(resultado: dict[str, Any]) -> list[str]:
    return [c["change_date_time"][:10] for c in resultado["changes"]]


@pytest.mark.asyncio
async def test_pagina_alem_do_teto_de_500(_ctx: McpRequestContext) -> None:
    """1200 eventos na janela: antes do fix, 700 sumiam sem ninguem dizer.

    O que o gestor via: um veredito de drift calculado sobre 500 das 1200
    mudancas — e um `truncated` que falava do `limit` DELE, nao das 700 que a
    tool nunca leu.
    """
    historico = _HistoricoFalso({date(2026, 9, 7): 700, date(2026, 9, 6): 500})

    resultado = await _rodar(historico, {"customer_id": "7862230676", "date_range": "LAST_2_DAYS"})

    assert resultado["summary"]["total_changes_in_window"] == 1200
    assert resultado["summary"]["total_drift_changes"] == 1200
    assert resultado["cobertura"]["eventos_examinados"] == 1200
    assert resultado["cobertura"]["janelas_consultadas"] == 1
    assert resultado["cobertura"]["varredura_truncada"] is False
    # O teto interno saiu de 500: uma unica leitura, pedindo o cap do recurso.
    assert historico.chamadas == [("2026-09-06", "2026-09-07", 10_000)]
    # E os DOIS truncados dizem coisas diferentes na MESMA resposta: a lista do
    # gestor foi cortada em 100, a varredura nao perdeu nada.
    assert resultado["truncated"] is True
    assert resultado["returned_count"] == 100


@pytest.mark.asyncio
async def test_particiona_por_dia_quando_a_janela_inteira_nao_cabe(
    _ctx: McpRequestContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem cursor, a particao e do TEMPO: 3 dias viram 3 sub-janelas.

    Os tetos reais (10k/20k) sao trocados por 10/100 para exercitar o caminho
    sem materializar 10 mil linhas — o valor real dos dois fica prendido em
    `test_os_tetos_sao_constantes_nomeadas_e_maiores_que_o_defeito`.
    """
    monkeypatch.setattr("src.mcp.tools.detect_drift._TETO_POR_JANELA", 10)
    monkeypatch.setattr("src.mcp.tools.detect_drift._TETO_EXAMINADO", 100)
    historico = _HistoricoFalso({date(2026, 9, 7): 8, date(2026, 9, 6): 8, date(2026, 9, 5): 8})

    resultado = await _rodar(
        historico,
        {"customer_id": "7862230676", "start_date": "2026-09-05", "end_date": "2026-09-07"},
    )

    assert resultado["cobertura"]["eventos_examinados"] == 24
    assert resultado["cobertura"]["janelas_consultadas"] == 3
    assert resultado["cobertura"]["varredura_truncada"] is False
    assert resultado["cobertura"]["dias_no_teto_da_api"] == []
    assert resultado["summary"]["total_changes_in_window"] == 24
    # A sonda da janela inteira primeiro; depois um dia por vez, do mais
    # RECENTE para o mais antigo (a ordem e contrato: o corte tem que cair no
    # passado, nao no que acabou de mudar).
    assert historico.chamadas == [
        ("2026-09-05", "2026-09-07", 10),
        ("2026-09-07", "2026-09-07", 10),
        ("2026-09-06", "2026-09-06", 10),
        ("2026-09-05", "2026-09-05", 10),
    ]


@pytest.mark.asyncio
async def test_teto_total_para_a_varredura_e_declara_o_numero(
    _ctx: McpRequestContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Teto total atingido: `varredura_truncada` sobe E o numero aparece.

    Contagem sem numero seria a mesma opacidade do teto de 500.
    """
    monkeypatch.setattr("src.mcp.tools.detect_drift._TETO_POR_JANELA", 10)
    monkeypatch.setattr("src.mcp.tools.detect_drift._TETO_EXAMINADO", 15)
    historico = _HistoricoFalso({date(2026, 9, 7): 8, date(2026, 9, 6): 8, date(2026, 9, 5): 8})

    resultado = await _rodar(
        historico,
        {"customer_id": "7862230676", "start_date": "2026-09-05", "end_date": "2026-09-07"},
    )

    assert resultado["cobertura"]["varredura_truncada"] is True
    assert resultado["cobertura"]["eventos_examinados"] == 15
    assert resultado["cobertura"]["janelas_consultadas"] == 2
    assert resultado["cobertura"]["teto_examinado"] == 15
    # O que sobrou e o PASSADO, nunca o presente: o dia mais recente veio
    # inteiro e o mais antigo nem chegou a ser consultado.
    assert _dias(resultado).count("2026-09-07") == 8
    assert "2026-09-05" not in _dias(resultado)
    assert ("2026-09-05", "2026-09-05", 10) not in historico.chamadas


@pytest.mark.asyncio
async def test_dia_que_sozinho_estoura_o_cap_e_declarado(
    _ctx: McpRequestContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Janela de UM dia acima do cap: a particao chegou ao fim da granularidade.

    Nao ha sub-janela menor que um dia por este caminho, entao a resposta certa
    e dizer qual dia bateu no teto da API — e nao repetir a mesma consulta.
    """
    monkeypatch.setattr("src.mcp.tools.detect_drift._TETO_POR_JANELA", 5)
    historico = _HistoricoFalso({date(2026, 9, 8): 12})

    resultado = await _rodar(historico, {"customer_id": "7862230676", "date_range": "TODAY"})

    assert resultado["cobertura"]["dias_no_teto_da_api"] == ["2026-09-08"]
    assert resultado["cobertura"]["varredura_truncada"] is True
    assert resultado["cobertura"]["eventos_examinados"] == 5
    assert resultado["cobertura"]["janelas_consultadas"] == 1
    assert len(historico.chamadas) == 1


@pytest.mark.asyncio
async def test_dia_no_cap_dentro_de_janela_particionada(
    _ctx: McpRequestContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A particao ajudou e AINDA assim perdeu evento — os dois fatos convivem."""
    monkeypatch.setattr("src.mcp.tools.detect_drift._TETO_POR_JANELA", 5)
    monkeypatch.setattr("src.mcp.tools.detect_drift._TETO_EXAMINADO", 100)
    historico = _HistoricoFalso({date(2026, 9, 7): 3, date(2026, 9, 6): 12})

    resultado = await _rodar(historico, {"customer_id": "7862230676", "date_range": "LAST_2_DAYS"})

    assert resultado["cobertura"]["janelas_consultadas"] == 2
    assert resultado["cobertura"]["dias_no_teto_da_api"] == ["2026-09-06"]
    assert resultado["cobertura"]["varredura_truncada"] is True
    assert resultado["cobertura"]["eventos_examinados"] == 8


@pytest.mark.asyncio
async def test_a_varredura_segue_a_janela_efetiva_nao_a_pedida(
    _ctx: McpRequestContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O clamp de retencao (F23) move o inicio, e a particao tem que obedece-lo.

    `get_change_history` recusa dia inteiro fora da retencao de 30 dias com
    `ValueError`. Se a varredura derivasse os dias da janela PEDIDA, uma janela
    clampada quebraria a tool; derivando do `period` que a leitura devolveu, ela
    varre exatamente o que existe.
    """
    monkeypatch.setattr("src.mcp.tools.detect_drift._TETO_POR_JANELA", 10)

    class _ComClamp(_HistoricoFalso):
        async def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
            if args["start_date"] < "2026-09-06":
                args = {**args, "start_date": "2026-09-06"}
            return await super().__call__(args)

    clampado = _ComClamp({date(2026, 9, 7): 8, date(2026, 9, 6): 8})

    resultado = await _rodar(
        clampado,
        {"customer_id": "7862230676", "start_date": "2026-09-01", "end_date": "2026-09-07"},
    )

    assert resultado["cobertura"]["janela_efetiva"] == {"from": "2026-09-06", "to": "2026-09-07"}
    assert resultado["cobertura"]["janelas_consultadas"] == 2
    # Os dias varridos sao os da janela EFETIVA — nenhuma consulta a 01..05,
    # que estao fora da retencao e levantariam ValueError na tool real.
    assert [c[0] for c in clampado.chamadas[1:]] == ["2026-09-07", "2026-09-06"]


def test_os_tetos_sao_constantes_nomeadas_e_maiores_que_o_defeito() -> None:
    """Prende os VALORES reais: os testes acima rodam com tetos trocados.

    Sem esta assercao, alguem podia devolver o teto por janela para 500 e a
    suite inteira continuaria verde — que e exatamente o defeito que a Task 5
    fecha.
    """
    from src.mcp.tools.detect_drift import _TETO_EXAMINADO, _TETO_POR_JANELA
    from src.mcp.tools.get_change_history import _CAP_CHANGE_EVENT

    assert _TETO_POR_JANELA == _CAP_CHANGE_EVENT == 10_000
    assert _TETO_POR_JANELA > 500
    assert _TETO_EXAMINADO >= _TETO_POR_JANELA


def test_a_description_distingue_os_dois_truncados() -> None:
    """Dois campos com o mesmo significado aparente numa resposta de seguranca
    sao pior que um: o gestor le o `truncated` do `limit` dele e conclui que a
    varredura foi inteira. A description tem que nomear os dois."""
    import src.mcp.tools.detect_drift  # noqa: F401
    from src.mcp.tools._registry import get_tool

    tool = get_tool("detect_drift")
    assert tool is not None
    for termo in (
        "cobertura",
        "varredura_truncada",
        "eventos_examinados",
        "janelas_consultadas",
        "dias_no_teto_da_api",
    ):
        assert termo in tool.description, termo
