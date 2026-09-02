"""F131: `change_event` nao diz ate quando esta indexado, e o silencio mente.

`get_change_history` e `detect_drift` devolvem "zero" com a mesma cara para
duas realidades opostas: nao houve mudanca, e houve mudanca que ainda nao
indexou. `detect_drift` e tool de SEGURANCA e roda inteiramente sobre essa
fonte — pode dizer "zero drift" numa conta que um terceiro acabou de mexer.

Medido na conta 786-223-0676 em 2026-09-02: writes as 11:28-11:43, consulta as
~11:50 devolveu ZERO, e no fim da tarde as 30 linhas estavam la, reconciliando
item a item. A janela foi de ~3-4 horas. O registro de campo de 25/05 tem o
outro extremo, >4 dias.

**E a variabilidade que obriga a medir.** Se o lag fosse fixo, uma nota na
description resolveria. Indo de ~3h a >4 dias na mesma conta, sem contrato, a
unica saida honesta e a fronteira medida a cada chamada.

## Duas fronteiras, nao uma

- **Fronteira da conta**: sonda propria, SEM os filtros do usuario. Herdar
  `resource_types` reproduziria a cegueira que ela mede — conta sem historico
  daquele tipo responderia vazio pelo mesmo silencio.
- **Fronteira do recorte**: `max` das linhas que a query principal ja devolveu.
  Custo zero de quota; o dado ja esta na resposta.

Juntas, tornam os tres estados distinguiveis — e o ganho real e o estado
AMBIGUO deixar de se parecer com o confiavel.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

import pytest

from src.google_ads.change_freshness import assess_freshness


def test_conta_fresca_com_linhas_e_confiavel() -> None:
    r = assess_freshness(
        account_frontier=datetime(2026, 9, 2, 18, 0),
        slice_frontier=datetime(2026, 9, 2, 11, 43),
        window_end=date(2026, 9, 2),
    )
    assert r["status"] == "confiavel"
    assert r["warning"] is None


def test_conta_atrasada_derruba_a_confianca_mesmo_com_linhas() -> None:
    """O caso do campo: janela pedida mais nova que o ultimo evento indexado."""
    r = assess_freshness(
        account_frontier=datetime(2026, 8, 31, 10, 52),
        slice_frontier=datetime(2026, 8, 30, 9, 0),
        window_end=date(2026, 9, 2),
    )
    assert r["status"] == "atrasado"
    assert r["warning"] is not None
    assert "2026-08-31" in r["warning"]


def test_conta_fresca_com_recorte_vazio_e_ambiguo_e_declarado() -> None:
    """O ganho central: parar de parecer com 'nao houve mudanca'."""
    r = assess_freshness(
        account_frontier=datetime(2026, 9, 2, 18, 0),
        slice_frontier=None,
        window_end=date(2026, 9, 2),
    )
    assert r["status"] == "ambiguo"
    assert r["warning"] is not None


def test_sonda_vazia_nao_afirma_frescor() -> None:
    """Sem fronteira, a resposta honesta e 'nao sei' — nunca 'esta fresco'."""
    r = assess_freshness(
        account_frontier=None,
        slice_frontier=None,
        window_end=date(2026, 9, 2),
    )
    assert r["status"] == "indeterminado"
    assert r["warning"] is not None
    assert r["account_frontier"] is None


def test_fronteiras_saem_serializadas_para_o_payload() -> None:
    """O gestor le a data; o consumidor programatico compara string ISO."""
    r = assess_freshness(
        account_frontier=datetime(2026, 8, 31, 10, 52, 36),
        slice_frontier=datetime(2026, 8, 30, 9, 0, 0),
        window_end=date(2026, 9, 2),
    )
    assert r["account_frontier"] == "2026-08-31 10:52:36"
    assert r["slice_frontier"] == "2026-08-30 09:00:00"


def test_janela_terminada_antes_da_fronteira_e_confiavel_mesmo_sendo_antiga() -> None:
    """Consultar semana passada numa conta indexada ate hoje e confiavel."""
    r = assess_freshness(
        account_frontier=datetime(2026, 9, 2, 18, 0),
        slice_frontier=datetime(2026, 8, 20, 9, 0),
        window_end=date(2026, 8, 21),
    )
    assert r["status"] == "confiavel"
    assert r["warning"] is None


# --- Builder da sonda de fronteira -------------------------------------------


def test_sonda_de_fronteira_nao_herda_filtro_do_usuario() -> None:
    """A invariante que da sentido a sonda.

    Herdar `resource_types` faria a sonda responder vazio pelo MESMO silencio
    que ela existe pra medir — conta sem historico daquele tipo pareceria
    "nao indexado". A sonda mede a conta, nao o recorte.
    """
    from src.google_ads.queries.change_history import change_event_frontier_query

    q = change_event_frontier_query(today=date(2026, 9, 2))
    assert "change_resource_type" not in q
    assert "user_email" not in q
    assert "client_type" not in q
    assert "resource_change_operation" not in q


def test_sonda_de_fronteira_pede_a_linha_mais_nova_com_limit() -> None:
    """O Google RECUSA change_event sem LIMIT: "must specify a LIMIT"."""
    from src.google_ads.queries.change_history import change_event_frontier_query

    q = change_event_frontier_query(today=date(2026, 9, 2))
    assert "ORDER BY change_event.change_date_time DESC" in q
    assert q.rstrip().endswith("LIMIT 1")


# --- Fiacao nas duas tools ----------------------------------------------------


@pytest.fixture()
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _fake_run_report(*, main_rows, frontier_dt):
    """Despacha por query: a sonda e a unica que termina em LIMIT 1."""
    queries: list[str] = []

    async def _run(**kwargs):
        q = kwargs["query"]
        queries.append(q)
        if q.rstrip().endswith("LIMIT 1"):
            return [] if frontier_dt is None else [{"change_date_time": frontier_dt}]
        if "FROM change_event" in q:
            return main_rows
        return []

    return _run, queries


@pytest.mark.asyncio
async def test_zero_linhas_ainda_traz_veredito_de_frescor(_ctx) -> None:
    """O caso que originou o F131: vazio sem selo e indistinguivel de intacto."""
    from unittest.mock import patch

    from src.mcp.tools.get_change_history import get_change_history

    run, queries = _fake_run_report(main_rows=[], frontier_dt="2026-08-31 10:52:36.708927")
    with patch("src.mcp.tools.get_change_history.run_report", run):
        result = await get_change_history({"customer_id": "1234567890", "date_range": "TODAY"})

    assert result["summary"]["total_changes"] == 0
    assert result["freshness"]["account_frontier"] == "2026-08-31 10:52:36"
    assert result["freshness"]["status"] == "atrasado"
    assert result["freshness"]["warning"] is not None
    assert any(q.rstrip().endswith("LIMIT 1") for q in queries), "sonda nao foi emitida"


@pytest.mark.asyncio
async def test_detect_drift_propaga_a_fronteira(_ctx) -> None:
    """`detect_drift` e tool de seguranca: nao pode dizer 'zero drift' calado."""
    from unittest.mock import patch

    from src.mcp.tools.detect_drift import detect_drift

    run, _q = _fake_run_report(main_rows=[], frontier_dt="2026-08-31 10:52:36.708927")
    with patch("src.mcp.tools.get_change_history.run_report", run):
        result = await detect_drift({"customer_id": "1234567890", "date_range": "TODAY"})

    assert result["freshness"]["status"] == "atrasado"
    assert result["freshness"]["warning"] is not None


def test_sonda_de_fronteira_nao_herda_a_janela_do_usuario() -> None:
    """F131 bis: o guard anterior enumerou filtros e perdeu o que eu passava.

    O teste antigo assertava que a sonda nao carrega `resource_types`,
    `user_email`, `client_type` nem `operation` — quatro filtros que eu
    conseguia listar. A janela de data entrava como ARGUMENTO, entao nunca foi
    candidata a "filtro herdado", e passou.

    O efeito em producao: `account_frontier` mudava conforme a janela pedida.
    Consultar 31/08-01/09 devolvia fronteira 31/08 e status `atrasado`, com a
    conta indexada ate 02/09 — e o warning dispara em condicao NORMAL, porque
    toda janela terminando em dia sem write vira "atrasado". Warning que
    dispara sem defeito treina a ignorar o warning.

    Este teste assere a PROPRIEDADE em vez de enumerar: duas janelas
    diferentes tem de produzir a MESMA query de sonda.
    """
    from src.google_ads.queries.change_history import change_event_frontier_query

    hoje = date(2026, 9, 2)
    assert change_event_frontier_query(today=hoje) == change_event_frontier_query(today=hoje)

    # E a sonda nao aceita mais janela do chamador — nao ha por onde herdar.
    import inspect

    params = set(inspect.signature(change_event_frontier_query).parameters)
    assert params == {"today"}, f"a sonda voltou a aceitar janela do chamador: {params}"


def test_sonda_cobre_a_janela_de_retencao_e_nao_o_pedido() -> None:
    """A fronteira e da CONTA, entao varre a retencao inteira."""
    from src.google_ads.queries.change_history import change_event_frontier_query

    q = change_event_frontier_query(today=date(2026, 9, 2))
    assert "'2026-08-05'" in q, "inicio deve ser hoje-28 (margem de retencao)"
    assert "'2026-09-03'" in q, "fim deve ser hoje+1 (F46: BETWEEN e midnight-exclusive)"
