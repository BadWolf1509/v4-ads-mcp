"""M1: GAQL e parse do estado de revisao do RSA. Proto-plus omite default — "nao lido"
tem que ser None, nunca o nome de um enum (F145)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.google_ads.queries.rsa_estado import (
    ad_id_de_resource_name,
    parse_rsa_estado_row,
    rsa_estado_query,
)


def _enum(nome: str) -> SimpleNamespace:
    return SimpleNamespace(name=nome)


def _asset(texto: str, aprov: str | None = None, pin: str | None = None) -> SimpleNamespace:
    info = (
        SimpleNamespace()
        if aprov is None
        else SimpleNamespace(approval_status=_enum(aprov), review_status=_enum("REVIEWED"))
    )
    return SimpleNamespace(
        text=texto, pinned_field=_enum(pin or "UNSPECIFIED"), policy_summary_info=info
    )


def _row(
    ps: SimpleNamespace,
    headlines: list[SimpleNamespace] | None = None,
    descriptions: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    rsa = SimpleNamespace(headlines=headlines or [], descriptions=descriptions or [])
    return SimpleNamespace(
        ad_group_ad=SimpleNamespace(
            ad=SimpleNamespace(id=99, responsive_search_ad=rsa), policy_summary=ps
        ),
    )


def test_ad_id_dos_dois_formatos() -> None:
    assert ad_id_de_resource_name("customers/1/ads/99") == "99"
    assert ad_id_de_resource_name("customers/1/adGroupAds/5~99") == "99"
    with pytest.raises(ValueError):
        ad_id_de_resource_name("x")


def test_query_sem_segments_date() -> None:
    q = rsa_estado_query(["1"])
    assert "segments.date" not in q
    assert "FROM ad_group_ad" in q
    assert "policy_summary.approval_status" in q


def test_query_recusa_lista_vazia_e_id_nao_numerico() -> None:
    with pytest.raises(ValueError):
        rsa_estado_query([])
    with pytest.raises(ValueError):
        rsa_estado_query(["1 OR 1=1"])


def test_parse_default_omitido_vira_none() -> None:
    out = parse_rsa_estado_row(_row(SimpleNamespace()))
    assert out["approval_status"] is None
    assert out["review_status"] is None
    assert out["topicos"] == []
    assert out["ad_id"] == "99"


def test_parse_enum_por_nome() -> None:
    ps = SimpleNamespace(
        approval_status=_enum("DISAPPROVED"),
        review_status=_enum("REVIEWED"),
        policy_topic_entries=[SimpleNamespace(topic="DESTINATION_NOT_WORKING")],
    )
    out = parse_rsa_estado_row(_row(ps))
    assert out["approval_status"] == "DISAPPROVED"
    assert out["review_status"] == "REVIEWED"
    assert out["topicos"] == ["DESTINATION_NOT_WORKING"]


def test_parse_asset_reprovado() -> None:
    out = parse_rsa_estado_row(
        _row(
            SimpleNamespace(approval_status=_enum("APPROVED_LIMITED")),
            headlines=[_asset("ok", "APPROVED"), _asset("ruim", "DISAPPROVED")],
            descriptions=[_asset("desc ruim", "DISAPPROVED"), _asset("sem info")],
        )
    )
    assert out["assets_reprovados"] == [
        {"campo": "headline", "texto": "ruim", "approval_status": "DISAPPROVED"},
        {"campo": "description", "texto": "desc ruim", "approval_status": "DISAPPROVED"},
    ]


def test_parse_pinos() -> None:
    out = parse_rsa_estado_row(
        _row(
            SimpleNamespace(),
            headlines=[_asset("a", pin="HEADLINE_1"), _asset("b")],
            descriptions=[_asset("d", pin="DESCRIPTION_2")],
        )
    )
    assert out["pinos"] == {"HEADLINE_1": ["a"], "DESCRIPTION_2": ["d"]}


def test_parse_enum_unspecified_vira_none() -> None:
    """Proto-plus real devolve o enum default com .name == "UNSPECIFIED", nao omite."""
    ps = SimpleNamespace(approval_status=_enum("UNSPECIFIED"), review_status=_enum("UNSPECIFIED"))
    out = parse_rsa_estado_row(_row(ps))
    assert out["approval_status"] is None
    assert out["review_status"] is None
