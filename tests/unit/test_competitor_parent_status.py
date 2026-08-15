"""F90: `audit_competitor_keywords` nao expunha o status do ad_group pai.

Classe F52. A query filtra `ad_group_criterion.status = 'ENABLED'` mas NUNCA
seleciona `ad_group.status` — e o `status` devolvido ao gestor era a constante
`"ENABLED"` hardcoded no parser, nao um dado lido do row.

Consequencia: keyword ENABLED dentro de ad_group REMOVED nao compete em leilao,
mas entrava no "gasto em concorrencia" e nos `suggested_negatives` como se
competisse. E a mesma inflacao de narrativa que a F52 mediu em **60,7%** num
caso real (280 zumbis reportadas, 170 orfas cosmeticas) — o gestor age sobre
item inerte e conta pro cliente uma vitoria que nao existe.

Os dois irmaos de familia (`audit_zombie_keywords`, `audit_quality_score`) ja
citam a licao na description desde a 3b.38; este ficou de fora do retrofit.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.google_ads.competitor_analysis import KeywordRow, match_competitor_brands
from src.google_ads.queries.audit_competitor_keywords import (
    build_positive_keywords_query,
    dict_to_keyword_row,
    parse_positive_keyword_row,
)


def _row_sdk(ad_group_status: str) -> Any:
    """Row do SDK no formato proto-plus (enums expõem `.name`)."""
    return SimpleNamespace(
        ad_group=SimpleNamespace(
            id=123,
            name="AG Marcas",
            status=SimpleNamespace(name=ad_group_status),
        ),
        campaign=SimpleNamespace(name="Camp 1"),
        ad_group_criterion=SimpleNamespace(
            criterion_id=999,
            keyword=SimpleNamespace(
                text="concorrente x",
                match_type=SimpleNamespace(name="BROAD"),
            ),
        ),
    )


def test_query_seleciona_o_status_do_ad_group() -> None:
    """F90: sem o campo no SELECT, nao ha o que propagar."""
    query = build_positive_keywords_query()
    assert "ad_group.status" in query


def test_parser_le_o_status_do_pai_em_vez_de_inventar() -> None:
    """F90: `.name` do enum (nao `str(enum)` — lição UX-2 do proto-plus)."""
    parsed = parse_positive_keyword_row(_row_sdk("REMOVED"))
    assert parsed["ad_group_status"] == "REMOVED"


def test_keyword_row_carrega_o_status_ate_o_matcher() -> None:
    """F90: o dado tem que sobreviver a travessia dict -> dataclass."""
    parsed = parse_positive_keyword_row(_row_sdk("PAUSED"))
    row = dict_to_keyword_row(parsed)
    assert row.ad_group_status == "PAUSED"


def test_keyword_casada_expoe_o_status_do_pai() -> None:
    """F90 — o ponto que interessa: o gestor precisa distinguir o que compete.

    Antes, as duas keywords abaixo saiam identicas (`status="ENABLED"`), e a que
    esta num ad_group REMOVED nao gasta um centavo.
    """
    linhas = [
        KeywordRow(
            ad_group_id="1",
            ad_group_name="AG viva",
            campaign_name="C",
            keyword_id="10",
            keyword_text="marca concorrente",
            match_type="BROAD",
            ad_group_status="ENABLED",
        ),
        KeywordRow(
            ad_group_id="2",
            ad_group_name="AG morta",
            campaign_name="C",
            keyword_id="20",
            keyword_text="marca concorrente",
            match_type="BROAD",
            ad_group_status="REMOVED",
        ),
    ]

    # A função devolve uma tupla; a 1ª posição são as keywords casadas.
    casadas, *_ = match_competitor_brands(
        competitor_brands=["marca concorrente"],
        keyword_rows=linhas,
        search_term_rows=[],
        limit=200,
    )

    por_ag = {k.ad_group_name: k.ad_group_status for k in casadas}
    assert por_ag == {"AG viva": "ENABLED", "AG morta": "REMOVED"}


def test_description_avisa_sobre_ad_group_pai() -> None:
    """F90: os dois irmãos avisam desde a 3b.38; este precisa avisar igual."""
    from src.mcp.tools.audit_competitor_keywords import _DESCRIPTION

    assert "ad_group_status" in _DESCRIPTION
