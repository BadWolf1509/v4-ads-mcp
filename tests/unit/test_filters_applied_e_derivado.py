"""Nomear ALGUNS filtros faz a lista ler como A lista."""

from src.google_ads.queries.audit_orphan_smart_actions import (
    build_audit_orphan_smart_actions_query,
)
from src.google_ads.queries.audit_quality_score import build_audit_quality_score_query
from src.google_ads.queries.audit_zombie_keywords import build_audit_zombie_keywords_query


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
}


def _campos_do_where(gaql: str) -> set[str]:
    import re

    where = gaql.split("WHERE", 1)[1]
    return set(re.findall(r"([a-z_]+(?:\.[a-z_]+)+)\s*(?:=|!=|IN|BETWEEN|IS)", where))


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
