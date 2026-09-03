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
        today=date(2026, 9, 3),
    )
    assert r["status"] == "confiavel"
    assert r["warning"] is None


def test_conta_atrasada_derruba_a_confianca_mesmo_com_linhas() -> None:
    """O caso do campo: janela pedida mais nova que o ultimo evento indexado."""
    r = assess_freshness(
        account_frontier=datetime(2026, 8, 31, 10, 52),
        slice_frontier=datetime(2026, 8, 30, 9, 0),
        window_end=date(2026, 9, 2),
        today=date(2026, 9, 3),
    )
    assert r["status"] == "nao_coberto"
    assert r["warning"] is not None
    assert "2026-08-31" in r["warning"]


def test_conta_fresca_com_recorte_vazio_e_ambiguo_e_declarado() -> None:
    """O ganho central: parar de parecer com 'nao houve mudanca'."""
    r = assess_freshness(
        account_frontier=datetime(2026, 9, 2, 18, 0),
        slice_frontier=None,
        window_end=date(2026, 9, 2),
        today=date(2026, 9, 3),
    )
    assert r["status"] == "ambiguo"
    assert r["warning"] is not None


def test_sonda_vazia_nao_afirma_frescor() -> None:
    """Sem fronteira, a resposta honesta e 'nao sei' — nunca 'esta fresco'."""
    r = assess_freshness(
        account_frontier=None,
        slice_frontier=None,
        window_end=date(2026, 9, 2),
        today=date(2026, 9, 3),
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
        today=date(2026, 9, 3),
    )
    assert r["account_frontier"] == "2026-08-31 10:52:36"
    assert r["slice_frontier"] == "2026-08-30 09:00:00"


def test_janela_terminada_antes_da_fronteira_e_confiavel_mesmo_sendo_antiga() -> None:
    """Consultar semana passada numa conta indexada ate hoje e confiavel."""
    r = assess_freshness(
        account_frontier=datetime(2026, 9, 2, 18, 0),
        slice_frontier=datetime(2026, 8, 20, 9, 0),
        window_end=date(2026, 8, 21),
        today=date(2026, 9, 3),
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

    async def _hoje(customer_id: str, *, now=None):
        return date(2026, 9, 2)

    with (
        patch("src.mcp.tools.get_change_history.run_report", run),
        patch("src.mcp.tools.get_change_history.resolve_account_today", _hoje),
    ):
        result = await get_change_history({"customer_id": "1234567890", "date_range": "TODAY"})

    assert result["summary"]["total_changes"] == 0
    assert result["freshness"]["account_frontier"] == "2026-08-31 10:52:36"
    assert result["freshness"]["status"] == "nao_coberto"
    assert result["freshness"]["warning"] is not None
    assert any(q.rstrip().endswith("LIMIT 1") for q in queries), "sonda nao foi emitida"


@pytest.mark.asyncio
async def test_detect_drift_propaga_a_fronteira(_ctx) -> None:
    """`detect_drift` e tool de seguranca: nao pode dizer 'zero drift' calado."""
    from unittest.mock import patch

    from src.mcp.tools.detect_drift import detect_drift

    run, _q = _fake_run_report(main_rows=[], frontier_dt="2026-08-31 10:52:36.708927")

    async def _hoje(customer_id: str, *, now=None):
        return date(2026, 9, 2)

    with (
        patch("src.mcp.tools.get_change_history.run_report", run),
        patch("src.mcp.tools.detect_drift.resolve_account_today", _hoje),
    ):
        result = await detect_drift({"customer_id": "1234567890", "date_range": "TODAY"})

    assert result["freshness"]["status"] == "nao_coberto"
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


# --- F143 + F144: os rotulos passam a nomear o fato, nao a causa ---------------
#
# F143: `atrasado` afirmava "o trecho final ainda nao indexou". A evidencia so
# sustenta o fato (fronteira anterior ao fim da janela) — e em conta de baixa
# atividade a explicacao dominante e "nao houve o que indexar". Vira
# `nao_coberto`, com as duas hipoteses no texto.
#
# F144: `confiavel` era alcancavel com a janela incluindo o dia corrente da
# conta — comparacao em granularidade de DIA, e fronteira de 20:44 "cobria"
# ate 23:59. Uma remocao de campanha real ficou de fora da resposta com
# `status: confiavel`. Vira `em_curso`: o dia nao fechou, por construcao nao e
# indexavel. E "dia corrente" e o DA CONTA (F141), nao o do servidor.


def test_janela_que_alcanca_o_dia_corrente_da_conta_nunca_e_confiavel() -> None:
    """O caso do campo: remocao de campanha as ~23h, fronteira das 20:44, status confiavel."""
    r = assess_freshness(
        account_frontier=datetime(2026, 9, 2, 20, 44, 5),
        slice_frontier=datetime(2026, 9, 2, 20, 44, 5),
        window_end=date(2026, 9, 2),
        today=date(2026, 9, 2),
    )
    assert r["status"] == "em_curso"
    assert r["warning"] is not None
    assert "2026-09-02 20:44:05" in r["warning"], "o texto tem que dizer ate onde esta indexado"


def test_janela_no_futuro_tambem_e_em_curso() -> None:
    r = assess_freshness(
        account_frontier=datetime(2026, 9, 2, 20, 44, 5),
        slice_frontier=None,
        window_end=date(2026, 9, 5),
        today=date(2026, 9, 2),
    )
    assert r["status"] == "em_curso"


def test_fronteira_anterior_ao_fim_da_janela_e_nao_coberto_e_nomeia_as_duas_hipoteses() -> None:
    """Camacari: fronteira 01/09 00:18, janela ate 02/09. Nao afirma causa."""
    r = assess_freshness(
        account_frontier=datetime(2026, 9, 1, 0, 18, 46),
        slice_frontier=None,
        window_end=date(2026, 9, 2),
        today=date(2026, 9, 3),
    )
    assert r["status"] == "nao_coberto"
    w = r["warning"] or ""
    assert "lag" in w.lower(), "tem que admitir a hipotese de lag"
    assert "atividade" in w.lower(), "tem que admitir a hipotese de conta parada"
    assert "ainda nao indexou" not in w.lower(), "afirmar causa era o F143"


def test_fronteira_velha_vence_dia_corrente() -> None:
    """Ordem deliberada: fronteira de ontem + janela ate hoje -> nao_coberto, nao em_curso.

    `em_curso` fica sendo o caso estreito "tao fresco quanto da, mas o dia esta
    aberto". Fronteira velha e o fato mais grave e tem que ganhar o rotulo.
    """
    r = assess_freshness(
        account_frontier=datetime(2026, 9, 1, 0, 18, 46),
        slice_frontier=datetime(2026, 9, 1, 0, 18, 46),
        window_end=date(2026, 9, 2),
        today=date(2026, 9, 2),
    )
    assert r["status"] == "nao_coberto"


def test_janela_fechada_no_passado_com_linhas_segue_confiavel() -> None:
    """Regressao: o caso legitimo medido na Camacari (06/08..01/09 -> confiavel)."""
    r = assess_freshness(
        account_frontier=datetime(2026, 9, 1, 0, 18, 46),
        slice_frontier=datetime(2026, 9, 1, 0, 18, 46),
        window_end=date(2026, 9, 1),
        today=date(2026, 9, 3),
    )
    assert r["status"] == "confiavel"
    assert r["warning"] is None


def test_o_rotulo_atrasado_nao_existe_mais() -> None:
    """Propriedade, nao grep: sobre uma grade de entradas, `atrasado` nunca sai."""
    from itertools import product

    fronteiras = [None, datetime(2026, 8, 30, 9, 0), datetime(2026, 9, 2, 20, 44)]
    recortes = [None, datetime(2026, 8, 30, 9, 0)]
    fins = [date(2026, 8, 29), date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 9)]
    vistos = {
        assess_freshness(
            account_frontier=f, slice_frontier=s, window_end=e, today=date(2026, 9, 2)
        )["status"]
        for f, s, e in product(fronteiras, recortes, fins)
    }
    assert "atrasado" not in vistos
    assert vistos <= {"confiavel", "ambiguo", "nao_coberto", "em_curso", "indeterminado"}
    assert {"nao_coberto", "em_curso", "confiavel", "indeterminado"} <= vistos, (
        "a grade tem que exercitar os quatro estados principais"
    )


def test_assess_freshness_exige_today() -> None:
    """Sem `today` nao ha como saber se a janela alcanca o dia corrente da conta."""
    import pytest

    with pytest.raises(TypeError):
        assess_freshness(  # type: ignore[call-arg]
            account_frontier=datetime(2026, 9, 2, 18, 0),
            slice_frontier=None,
            window_end=date(2026, 9, 2),
        )
