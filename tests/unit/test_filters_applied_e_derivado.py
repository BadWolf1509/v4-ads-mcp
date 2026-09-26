"""Nomear ALGUNS filtros faz a lista ler como A lista."""

import ast
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from src.google_ads.queries.audit_orphan_smart_actions import (
    build_audit_orphan_smart_actions_query,
)
from src.google_ads.queries.audit_quality_score import build_audit_quality_score_query
from src.google_ads.queries.audit_zombie_keywords import build_audit_zombie_keywords_query
from tests.unit import _guard_harness as h


def test_zombie_declara_os_cortes_server_side() -> None:
    _gaql, filtros = build_audit_zombie_keywords_query(
        start_date="2026-09-01", end_date="2026-09-30", ad_group_ids=None
    )
    assert filtros["criterion_status"] == "ENABLED"
    assert filtros["negative"] is False


def test_quality_score_declara_o_corte_de_qs_nulo() -> None:
    _gaql, filtros = build_audit_quality_score_query(start_date="2026-09-01", end_date="2026-09-30")
    assert filtros["criterion_status"] == "ENABLED"
    assert filtros["quality_score_nao_nulo"] is True


def test_orphan_declara_o_corte_de_status() -> None:
    _gaql, filtros = build_audit_orphan_smart_actions_query(
        start_date="2026-09-01", end_date="2026-09-30", category=None
    )
    assert filtros["conversion_action_status"] == "ENABLED"


# Mapa campo-do-WHERE -> chave em `filters_applied`. Existe para que um filtro
# NOVO numa query QUEBRE este teste: campo fora do mapa falha com instrucao, nao
# com silencio. Asserir chaves nomeadas uma a uma nao faria isso — passaria
# feliz com um sexto filtro escondido, que e o defeito de origem.
CAMPO_PARA_CHAVE = {
    "ad_group_criterion.status": "criterion_status",
    "ad_group_criterion.negative": "negative",
    "ad_group.id": "ad_group_ids",
    "segments.date": "date_range",
    "ad_group_criterion.quality_info.quality_score": "quality_score_nao_nulo",
    "conversion_action.status": "conversion_action_status",
    "conversion_action.category": "category",
    # plano 2026-09-26 (respostas Google)
    "campaign.status": "campaign_status",
    "ad_group.status": "ad_group_status",
    "ad_group_ad.status": "ad_status",
    "metrics.cost_micros": "min_cost_brl",
    "metrics.clicks": "min_clicks",
    "metrics.conversions": "min_conversions",
    "campaign_criterion.negative": "negative",
    "campaign_criterion.type": "criterion_type",
}


_CAMPO = re.compile(
    r"^([a-z_]+(?:\.[a-z_]+)+)\s*"
    r"(?:>=|<=|!=|=|>|<|\bNOT IN\b|\bIN\b|\bBETWEEN\b|\bIS\b|\bDURING\b|\bLIKE\b)"
)


def _condicoes_do_where(gaql: str) -> list[str]:
    """Condicoes do WHERE, uma por item. `BETWEEN 'a' AND 'b'` conta como uma so."""
    m = re.search(r"\bWHERE\b(.*?)(?:\bORDER BY\b|\bLIMIT\b|$)", gaql, re.S)
    if not m:
        return []
    where = re.sub(r"\bBETWEEN\s+'[^']*'\s+AND\s+'[^']*'", "BETWEEN _", m.group(1))
    return [c.strip() for c in re.split(r"\bAND\b", where) if c.strip()]


def _campos_do_where(gaql: str) -> set[str]:
    """O campo de CADA condicao. Condicao que o parser nao entende FALHA.

    O parser anterior lia so `=`, `!=`, `IN`, `BETWEEN` e `IS`: a metrica minima
    (`metrics.cost_micros >= X`) e a janela `DURING` passavam invisiveis, e a
    completude ficava verde sem elas (medido em 2026-09-25).
    """
    campos = set()
    for cond in _condicoes_do_where(gaql):
        m = _CAMPO.match(cond)
        assert m, f"condicao do WHERE que o parser nao entende: {cond!r}"
        campos.add(m.group(1))
    return campos


def test_todo_campo_cortado_aparece_em_filters_applied() -> None:
    """A assercao DERIVADA: nao confere uma lista, confere a propriedade."""
    construidos = [
        build_audit_zombie_keywords_query(
            start_date="2026-09-01", end_date="2026-09-30", ad_group_ids=["1"]
        ),
        build_audit_quality_score_query(
            start_date="2026-09-01", end_date="2026-09-30", ad_group_ids=["1"]
        ),
        build_audit_orphan_smart_actions_query(
            start_date="2026-09-01", end_date="2026-09-30", category="PURCHASE"
        ),
    ]
    assert len(construidos) == 3, "piso: as tres tools que publicam filters_applied"
    for gaql, filtros in construidos:
        campos = _campos_do_where(gaql)
        assert campos, f"nenhum campo lido do WHERE — o parser quebrou:\n{gaql}"
        for campo in campos:
            chave = CAMPO_PARA_CHAVE.get(campo)
            assert chave is not None, (
                f"`{campo}` corta no WHERE e este teste nao o conhece. Filtro novo: "
                "decida a chave em `filters_applied`, declare-a no builder, e "
                "acrescente o mapeamento aqui."
            )
            assert chave in filtros, f"`{campo}` corta e nao aparece em filters_applied"


_S, _E = date(2026, 9, 1), date(2026, 9, 30)
_ESTE_ARQUIVO = Path(__file__).resolve()

# Modulos em que TODA funcao `*_query` publica devolve (gaql, filtros). Cresce a
# cada task do plano 2026-09-26; a Task 5 fecha em 5 modulos e poe o piso de 17.
_MODULOS_CONVERTIDOS: tuple[Path, ...] = (
    h.SRC / "google_ads" / "queries" / "performance.py",
    h.SRC / "google_ads" / "queries" / "tactical.py",
    h.SRC / "google_ads" / "queries" / "client_report.py",
    h.SRC / "google_ads" / "queries" / "overview.py",
    h.SRC / "google_ads" / "queries" / "bulk_pause.py",
)


def _chamadas() -> dict[str, Callable[[], tuple[str, dict[str, Any]]]]:
    """Uma chamada de exemplo por funcao convertida, com args que exercitam os
    ramos COM corte opcional (status != 'all', minimos de metrica preenchidos).

    So cobre esses ramos — `_chamadas_sem_corte()` cobre o resto (status='all',
    minimos ausentes ou zero), que o guard de completude tambem precisa ver.
    """
    from src.google_ads.queries import client_report as c
    from src.google_ads.queries import overview as o
    from src.google_ads.queries import performance as p
    from src.google_ads.queries import tactical as t
    from src.google_ads.queries.bulk_pause import bulk_pause_query

    return {
        "campaign_performance_query": lambda: p.campaign_performance_query(_S, _E, "enabled", 10),
        "ad_group_performance_query": lambda: p.ad_group_performance_query(_S, _E, "enabled", 10),
        "device_performance_query": lambda: p.device_performance_query(_S, _E),
        "geo_performance_query": lambda: p.geo_performance_query(_S, _E, 10),
        "hourly_performance_query": lambda: p.hourly_performance_query(_S, _E),
        "ad_performance_query": lambda: t.ad_performance_query(_S, _E, "enabled", 10),
        "keyword_performance_query": lambda: t.keyword_performance_query(
            _S, _E, "enabled", 10, min_cost_brl=10.0, min_clicks=5, min_conversions=1.0
        ),
        "audience_performance_query": lambda: t.audience_performance_query(_S, _E, 10),
        "search_terms_query": lambda: t.search_terms_query(
            _S, _E, 10, min_cost_brl=10.0, min_clicks=5, min_conversions=1.0
        ),
        "negative_keywords_audit_query": lambda: t.negative_keywords_audit_query(),
        "conversion_actions_query": lambda: t.conversion_actions_query(limit=10),
        "funnel_query": lambda: c.funnel_query(_S, _E),
        "top_keywords_query": lambda: c.top_keywords_query(_S, _E, 10, metric="cost"),
        "top_creatives_query": lambda: c.top_creatives_query(_S, _E, 10, metric="cost"),
        "overview_query": lambda: o.overview_query(_S, _E),
        "budget_pacing_query": lambda: o.budget_pacing_query(limit=10),
        "bulk_pause_query": lambda: bulk_pause_query(
            target_type="keyword",
            filter_clause="ad_group_criterion.status = 'ENABLED'",
            start=_S,
            end=_E,
        ),
    }


# Chaves do eco que nao sao campo do WHERE: `nivel` declara o escopo (Task 3,
# negativas so de campanha); `filtro_do_gestor` e o texto livre do gestor (Task 5).
_CHAVES_SEM_CAMPO = frozenset({"nivel", "filtro_do_gestor"})


def _chamadas_sem_corte() -> list[tuple[str, Callable[[], tuple[str, dict[str, Any]]]]]:
    """Os ramos em que o corte opcional NAO entra (status="all", minimos None), e o
    minimo zero, que E corte (o ramo e `is not None`, nao truthiness)."""
    from src.google_ads.queries import performance as p
    from src.google_ads.queries import tactical as t
    from src.google_ads.queries.bulk_pause import bulk_pause_query

    return [
        ("campaign_performance_query", lambda: p.campaign_performance_query(_S, _E, "all", 10)),
        ("ad_group_performance_query", lambda: p.ad_group_performance_query(_S, _E, "all", 10)),
        ("ad_performance_query", lambda: t.ad_performance_query(_S, _E, "all", 10)),
        ("keyword_performance_query", lambda: t.keyword_performance_query(_S, _E, "all", 10)),
        (
            "keyword_performance_query",
            lambda: t.keyword_performance_query(
                _S, _E, "enabled", 10, min_cost_brl=0.0, min_clicks=0, min_conversions=0.0
            ),
        ),
        ("search_terms_query", lambda: t.search_terms_query(_S, _E, 10)),
        (
            "search_terms_query",
            lambda: t.search_terms_query(
                _S, _E, 10, min_cost_brl=0.0, min_clicks=0, min_conversions=0.0
            ),
        ),
        (
            "bulk_pause_query",
            lambda: bulk_pause_query(
                target_type="campaign",
                filter_clause="segments.date DURING LAST_7_DAYS AND metrics.cost_micros > 0",
                start=_S,
                end=_E,
            ),
        ),
    ]


def _funcoes_publicas(mod: Path) -> set[str]:
    """Toda funcao publica do modulo que devolve algo (anotacao diferente de `-> None`).

    O nome nao entra no criterio: funcao nova que devolva GAQL sem se chamar
    `*_query` tambem cai aqui (spec 2026-09-25, §3.3 — populacao por varredura).
    """
    return {
        fn.name
        for fn in h.funcoes(h.arvore(mod))
        if not fn.name.startswith("_")
        and not (isinstance(fn.returns, ast.Constant) and fn.returns.value is None)
    }


def test_toda_funcao_publica_dos_modulos_convertidos_tem_chamada_de_exemplo() -> None:
    nos_modulos = {nome for mod in _MODULOS_CONVERTIDOS for nome in _funcoes_publicas(mod)}
    assert nos_modulos, "controle: nenhuma funcao achada — o escopo quebrou"
    faltam = sorted(nos_modulos - set(_chamadas()))
    assert not faltam, (
        f"funcao publica sem chamada de exemplo aqui: {faltam}. Acrescente em "
        "`_chamadas()` com args que exercitem todo ramo do WHERE."
    )


def test_o_parser_novo_ve_o_que_o_antigo_nao_via() -> None:
    """Controle: metrica minima e janela DURING sao cortes."""
    assert _campos_do_where("SELECT a FROM b WHERE metrics.cost_micros >= 10 LIMIT 5") == {
        "metrics.cost_micros"
    }
    assert _campos_do_where("SELECT a FROM b WHERE segments.date DURING THIS_MONTH") == {
        "segments.date"
    }


def _valor_no_gaql(chave: str, valor: Any, gaql: str) -> bool:
    """O valor ecoado e o que o WHERE aplica (os minimos numericos saem da mesma
    funcao que escreve a clausula, `_clausula_e_eco_de_metrica`)."""
    if chave == "date_range":
        if "during" in valor:
            return f"DURING {valor['during']}" in gaql
        return f"BETWEEN '{valor['start']}' AND '{valor['end']}'" in gaql
    if isinstance(valor, bool):
        return f"= {str(valor).lower()}" in gaql
    if isinstance(valor, str):
        return f"'{valor}'" in gaql
    return True


def test_toda_funcao_convertida_ecoa_cada_corte_do_where() -> None:
    for nome, chamar in [*_chamadas().items(), *_chamadas_sem_corte()]:
        resultado = chamar()
        assert isinstance(resultado, tuple) and len(resultado) == 2, (
            f"{nome} tem de devolver (gaql, filtros), com filtros montado junto da "
            "clausula do WHERE que ele descreve (spec 2026-09-25, §3.1)."
        )
        gaql, filtros = resultado
        if "filtro_do_gestor" in filtros:
            # texto livre do gestor: ecoado INTEIRO, e fora da analise campo a campo
            assert filtros["filtro_do_gestor"] in gaql
            gaql = gaql.replace(filtros["filtro_do_gestor"], "")
        esperadas = set()
        for campo in _campos_do_where(gaql):
            chave = CAMPO_PARA_CHAVE.get(campo)
            assert chave is not None, (
                f"{nome}: `{campo}` corta no WHERE e este teste nao o conhece. Decida a "
                "chave em `filters_applied`, declare-a na funcao e mapeie aqui."
            )
            esperadas.add(chave)
        declaradas = set(filtros) - _CHAVES_SEM_CAMPO
        assert declaradas == esperadas, (
            f"{nome}: o WHERE corta {sorted(esperadas)} e o eco declara {sorted(declaradas)}. "
            "Chave sem corte afirma um recorte que a query nao aplicou; corte sem chave o esconde."
        )
        for chave in declaradas:
            assert _valor_no_gaql(chave, filtros[chave], gaql), (
                f"{nome}: filtros[{chave!r}] = {filtros[chave]!r} nao e o que o WHERE aplica"
            )


def test_o_escopo_final_tem_as_17_funcoes_nos_5_modulos() -> None:
    """Piso: sem ele, um modulo que saisse da tupla deixaria os guards menores e verdes."""
    assert len(_MODULOS_CONVERTIDOS) >= 5, (
        f"piso medido em 26/09: 5 modulos; achou {len(_MODULOS_CONVERTIDOS)}"
    )
    assert len(_chamadas()) >= 17, f"piso medido em 26/09: 17 funcoes; achou {len(_chamadas())}"
    assert {n for m in _MODULOS_CONVERTIDOS for n in _funcoes_publicas(m)} == set(_chamadas())


def test_o_breakdown_repassa_o_recorte_da_funcao_que_despacha() -> None:
    from src.google_ads.performance_breakdown import build_performance_breakdown_query
    from src.google_ads.queries import performance as p
    from src.google_ads.queries import tactical as t

    esperados = {
        ("campaign", None): lambda: p.campaign_performance_query(_S, _E, "enabled", 10),
        ("ad_group", None): lambda: p.ad_group_performance_query(_S, _E, "enabled", 10),
        ("ad", None): lambda: t.ad_performance_query(_S, _E, "enabled", 10),
        ("keyword", None): lambda: t.keyword_performance_query(_S, _E, "enabled", 10),
        ("audience", None): lambda: t.audience_performance_query(_S, _E, 10),
        ("account", "device"): lambda: p.device_performance_query(_S, _E),
        ("account", "geo"): lambda: p.geo_performance_query(_S, _E, 10),
        ("account", "hourly"): lambda: p.hourly_performance_query(_S, _E),
    }
    for (level, breakdown), direto in esperados.items():
        assert (
            build_performance_breakdown_query(level, breakdown, "enabled", _S, _E, 10) == direto()
        ), f"{level}/{breakdown}"


def _nomes_em_escopo() -> set[str]:
    return set(_chamadas()) | {"build_performance_breakdown_query"}


def _chamadas_sem_desempacotar(arv: ast.Module, nomes: set[str]) -> list[int]:
    """Chamada de funcao de query que NAO desempacota a tupla na hora.

    So duas formas passam: `a, b = f(...)` e `f(...)[i]`. Qualquer outra entrega a
    TUPLA a quem espera texto — e `assert "x" not in q` contra uma tupla fica verde
    sem afirmar nada (31 asserts `not in` nos arquivos consumidores, medido em 25/09).
    `nomes` ja e o conjunto de nomes LOCAIS a casar (aliases inclusive) — quem chama
    resolve alias com `h.nomes_locais` antes de passar pra ca. Limite: chamada por
    nome local dinamico (`builder(...)` num parametrize) nao e vista.
    """
    pais = {filho: no for no in ast.walk(arv) for filho in ast.iter_child_nodes(no)}
    ruins = []
    for no in ast.walk(arv):
        if not isinstance(no, ast.Call):
            continue
        nome = no.func.id if isinstance(no.func, ast.Name) else getattr(no.func, "attr", None)
        if nome not in nomes:
            continue
        pai = pais.get(no)
        desempacota = (
            isinstance(pai, ast.Assign)
            and len(pai.targets) == 1
            and isinstance(pai.targets[0], ast.Tuple)
            and len(pai.targets[0].elts) == 2
        )
        indexa = isinstance(pai, ast.Subscript) and pai.value is no
        if not (desempacota or indexa):
            ruins.append(no.lineno)
    return sorted(ruins)


def test_o_detector_de_desempacotamento_enxerga_as_formas_proibidas() -> None:
    """Controle positivo, com a fronteira exata do que passa — inclusive alias
    de import (`from m import f as apelido`), que so e visto porque `nomes` aqui
    ja vem expandido por `h.nomes_locais`."""
    fonte = (
        "q = f(1)\n"
        "assert 'x' in f(1)\n"
        "for q in (f(1),):\n"
        "    pass\n"
        "g, h = f(1)\n"
        "g = f(1)[0]\n"
        "from m import f as apelido\n"
        "q = apelido(1)\n"
    )
    arv = ast.parse(fonte)
    assert _chamadas_sem_desempacotar(arv, h.nomes_locais(arv, "f")) == [1, 2, 3, 8]


def test_chamada_de_funcao_de_query_em_teste_desempacota_a_tupla() -> None:
    nomes = _nomes_em_escopo()
    ofensores: list[str] = []
    for p in h.testes_py():
        if p.resolve() == _ESTE_ARQUIVO:
            continue
        arv = h.arvore(p)
        # Alias de import (`from ... import f as apelido`) e um nome LOCAL
        # diferente do escrito na funcao — sem expandir por arquivo, `q =
        # apelido(1)` nao casa contra `nomes` e o detector acusa `[]` (achado 3
        # da revisao, sonda medida 2026-09-26).
        nomes_do_arquivo = {alias for n in nomes for alias in h.nomes_locais(arv, n)}
        ofensores.extend(
            f"{h.rel(p)}:{linha}" for linha in _chamadas_sem_desempacotar(arv, nomes_do_arquivo)
        )
    assert not ofensores, (
        f"chamada de funcao de query sem desempacotar `(gaql, filtros)`: {ofensores}. "
        "Use `gaql, _ = f(...)` ou `f(...)[0]`."
    )
