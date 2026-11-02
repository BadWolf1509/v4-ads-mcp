"""meta_ads.historico: mapeamento de uma linha de `activities` e chamada da edge."""

from __future__ import annotations

from datetime import date

from src.meta_ads import historico

_LINHA = {
    "actor_id": "123",
    "actor_name": "Ana",
    "application_id": "9",
    "application_name": "Ads Manager",
    "date_time_in_timezone": "11/01/2026 at 9:15 AM",
    "event_time": "2026-11-01T12:15:00+0000",
    "event_type": "update_campaign_budget",
    "extra_data": '{"old_value":1000,"new_value":2000}',
    "object_id": "555",
    "object_name": "Camp A",
    "object_type": "CAMPAIGN_GROUP",
    "translated_event_type": "Orçamento da campanha atualizado",
}


def test_mapeia_a_forma_medida() -> None:
    r = historico.parse_atividade(_LINHA)
    assert r["ocorrido_em"] == "2026-11-01T12:15:00+0000"
    assert r["ator_id"] == "123" and r["ator_nome"] == "Ana"
    assert r["tipo"] == "update_campaign_budget"
    assert r["objeto_id"] == "555"
    assert r["objeto_tipo"] == "campanha"
    assert r["detalhe"] == {"old_value": 1000, "new_value": 2000}
    assert r["ocorrido_em_fuso_conta"] == "11/01/2026 at 9:15 AM"
    assert r["objeto_nome"] == "Camp A"
    assert set(r) == {
        "ocorrido_em",
        "ocorrido_em_fuso_conta",
        "ator_id",
        "ator_nome",
        "tipo",
        "objeto_id",
        "objeto_nome",
        "objeto_tipo",
        "detalhe",
    }


def test_ator_ausente_e_null_nunca_vazio() -> None:
    r = historico.parse_atividade({"event_time": "x", "event_type": "t", "object_type": "ADGROUP"})
    assert r["ator_id"] is None and r["ator_nome"] is None
    assert r["objeto_id"] is None and r["detalhe"] is None
    assert r["objeto_tipo"] == "anuncio"


def test_extra_data_nao_json_volta_como_texto() -> None:
    r = historico.parse_atividade({**_LINHA, "extra_data": "texto solto"})
    assert r["detalhe"] == "texto solto"


def test_tipos_de_objeto_traduzidos_e_desconhecido_passa() -> None:
    for bruto, esperado in [
        ("CAMPAIGN_GROUP", "campanha"),
        ("CAMPAIGN", "conjunto"),
        ("ADGROUP", "anuncio"),
        ("ACCOUNT", "conta"),
        ("PIXEL", "PIXEL"),
    ]:
        assert (
            historico.parse_atividade({**_LINHA, "object_type": bruto})["objeto_tipo"] == esperado
        )


def test_chamada_manda_since_e_until_sempre() -> None:
    edge, params = historico.build_activities_call(
        "act_1", since=date(2026, 10, 26), until=date(2026, 11, 1), limit=100
    )
    assert edge == "/act_1/activities"
    assert params["since"] == "2026-10-26"
    assert params["until"] == "2026-11-01"
    assert params["limit"] == 100  # teto de pagina; o resto vem por paging.next
    assert "event_time" in params["fields"] and "extra_data" in params["fields"]
