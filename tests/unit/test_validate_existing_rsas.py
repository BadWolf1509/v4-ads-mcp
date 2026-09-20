"""Unit tests for validate_existing_rsas_for_update (Sprint 3b.18)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries._common import validate_existing_rsas_for_update


@pytest.mark.asyncio
async def test_returns_none_when_all_valid(monkeypatch) -> None:
    """RSA ad em SEARCH campaign ENABLED ad_group → no error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_id": "100",
                "ad_type": "RESPONSIVE_SEARCH_AD",
                "system_managed_source": "UNSPECIFIED",
                "ad_group_id": "1",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "10",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "100", "headlines": ["H1", "H2", "H3"]}],
    )
    assert result is None


@pytest.mark.asyncio
async def test_rejects_missing_ad(monkeypatch) -> None:
    """Ad not in lookup → error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return []

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "999", "path1": "abc"}],
    )
    assert result is not None
    assert "999" in result
    assert "nao encontrado" in result.lower()


@pytest.mark.asyncio
async def test_rejects_non_rsa_type(monkeypatch) -> None:
    """ad.type != RESPONSIVE_SEARCH_AD → error mencionando type."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_id": "100",
                "ad_type": "EXPANDED_TEXT_AD",
                "system_managed_source": "UNSPECIFIED",
                "ad_group_id": "1",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "10",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "100", "path1": "x"}],
    )
    assert result is not None
    assert "EXPANDED_TEXT_AD" in result
    assert "RESPONSIVE_SEARCH_AD" in result


@pytest.mark.asyncio
async def test_rejects_removed_ad_group(monkeypatch) -> None:
    """Parent ad_group REMOVED → error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_id": "100",
                "ad_type": "RESPONSIVE_SEARCH_AD",
                "system_managed_source": "UNSPECIFIED",
                "ad_group_id": "1",
                "ad_group_name": "OldAG",
                "ad_group_status": "REMOVED",
                "campaign_id": "10",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "100", "path1": "x"}],
    )
    assert result is not None
    assert "REMOVED" in result
    assert "OldAG" in result


@pytest.mark.asyncio
async def test_recusa_ad_id_nao_numerico(monkeypatch) -> None:
    """`", ".join(ad_ids)` interpolava texto livre direto no GAQL.

    O `pattern` do schema a montante nao e defesa: helper e chamado de mais de
    um lugar, e o proximo chamador pode nao ter schema nenhum (F87). A funcao
    tem que recusar o id invalido ANTES de montar a query — run_report nao
    pode chegar a ser chamado.
    """

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        raise AssertionError("run_report chamado com ad_id nao-numerico")

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    with pytest.raises(ValueError):
        await validate_existing_rsas_for_update(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            updates=[{"ad_id": "1) OR 1=1 --", "path1": "x"}],
        )


@pytest.mark.asyncio
async def test_rejects_non_search_channel(monkeypatch) -> None:
    """Parent campaign channel != SEARCH/SEARCH_PARTNERS → error."""

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_id": "100",
                "ad_type": "RESPONSIVE_SEARCH_AD",
                "system_managed_source": "UNSPECIFIED",
                "ad_group_id": "1",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "10",
                "campaign_name": "ShopCamp",
                "channel_type": "SHOPPING",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "100", "path1": "x"}],
    )
    assert result is not None
    assert "SHOPPING" in result
    assert "SEARCH" in result


@pytest.mark.asyncio
async def test_rejeita_variacao_de_ad_variation(monkeypatch) -> None:
    """F181: anuncio system-managed passa em todos os outros filtros e tem que cair aqui.

    A variacao E um RESPONSIVE_SEARCH_AD, num ad_group ENABLED, numa campanha
    SEARCH — por isso ela atravessava o pre-flight inteiro.
    """

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_id": "825281476311",
                "ad_type": "RESPONSIVE_SEARCH_AD",
                "system_managed_source": "AD_VARIATIONS",
                "ad_group_id": "204135195030",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "21359547724",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "825281476311", "final_urls": ["https://exemplo.com.br"]}],
    )
    assert result is not None
    assert "825281476311" in result
    assert "variacao" in result.lower()
    # A mensagem tem que dizer O QUE FAZER, nao so que deu errado.
    assert "base" in result.lower()


@pytest.mark.asyncio
async def test_ad_normal_nao_e_confundido_com_variacao(monkeypatch) -> None:
    """Controle: sem o valor (anuncio comum) o pre-flight continua passando.

    Sem este teste, um predicado que rejeitasse TUDO passaria no teste anterior.
    """

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_id": "825140457725",
                "ad_type": "RESPONSIVE_SEARCH_AD",
                "system_managed_source": "UNSPECIFIED",
                "ad_group_id": "204135195030",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "21359547724",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "825140457725", "path1": "abc"}],
    )
    assert result is None


@pytest.mark.asyncio
async def test_query_do_preflight_pede_o_campo_de_system_managed(monkeypatch) -> None:
    """A rejeicao so funciona se o SELECT trouxer o campo. Guard da query, nao do parser."""
    capturado: dict[str, str] = {}

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        capturado["query"] = kwargs["query"]
        return []

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "100", "path1": "abc"}],
    )
    assert "ad_group_ad.ad.system_managed_resource_source" in capturado["query"]


def test_formatter_le_o_campo_pelo_caminho_certo_do_proto() -> None:
    """O formatter le `.name` do enum, nao o enum cru.

    ATENCAO ao que este teste NAO prova: que o caminho do proto existe no SDK.
    Isso foi provado empiricamente em 19/09 via `run_gaql` na MO-JP (ver F181),
    que e a unica prova possivel de superficie de API externa. Aqui provamos so
    que o formatter le `.name` e nao o objeto enum.
    """
    from types import SimpleNamespace

    from src.google_ads.queries._common import _format_rsa_preflight_row

    row = SimpleNamespace(
        ad_group_ad=SimpleNamespace(
            ad=SimpleNamespace(
                id=825281476311,
                type=SimpleNamespace(name="RESPONSIVE_SEARCH_AD"),
                system_managed_resource_source=SimpleNamespace(name="AD_VARIATIONS"),
            )
        ),
        ad_group=SimpleNamespace(
            id=204135195030, name="AG1", status=SimpleNamespace(name="ENABLED")
        ),
        campaign=SimpleNamespace(
            id=21359547724,
            name="C1",
            advertising_channel_type=SimpleNamespace(name="SEARCH"),
        ),
    )
    assert _format_rsa_preflight_row(row)["system_managed_source"] == "AD_VARIATIONS"


@pytest.mark.asyncio
async def test_mensagem_nomeia_o_ad_base_quando_ele_e_unico(monkeypatch) -> None:
    """F181: a mensagem que teria poupado a investigacao nomeia o anuncio a editar."""
    chamadas: list[str] = []

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        chamadas.append(kwargs["query"])
        if len(chamadas) == 1:
            return [
                {
                    "ad_id": "825281476311",
                    "ad_type": "RESPONSIVE_SEARCH_AD",
                    "system_managed_source": "AD_VARIATIONS",
                    "ad_group_id": "204135195030",
                    "ad_group_name": "AG1",
                    "ad_group_status": "ENABLED",
                    "campaign_id": "21359547724",
                    "campaign_name": "C1",
                    "channel_type": "SEARCH",
                }
            ]
        return [
            {"ad_id": "825140457725", "system_managed_source": "UNSPECIFIED"},
            {"ad_id": "825281476311", "system_managed_source": "AD_VARIATIONS"},
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "825281476311", "final_urls": ["https://exemplo.com.br"]}],
    )
    assert result is not None
    assert "825140457725" in result
    # A 2a query so acontece no caminho de falha.
    assert len(chamadas) == 2


@pytest.mark.asyncio
async def test_sem_base_unico_a_mensagem_nao_inventa_id(monkeypatch) -> None:
    """Dois nao-variacao no grupo: a mensagem cai pro generico em vez de chutar.

    Este e o teste que impede a correcao de virar afirmacao falsa: nomear o
    anuncio errado e pior que nao nomear nenhum.
    """

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        # O pre-flight TAMBEM pede system_managed_resource_source desde o F181,
        # entao o discriminador e o `ad_group.id =`, que so a busca do base tem.
        if "ad_group.id =" in kwargs["query"]:
            return [
                {"ad_id": "111", "system_managed_source": "UNSPECIFIED"},
                {"ad_id": "222", "system_managed_source": "UNSPECIFIED"},
                {"ad_id": "825281476311", "system_managed_source": "AD_VARIATIONS"},
            ]
        return [
            {
                "ad_id": "825281476311",
                "ad_type": "RESPONSIVE_SEARCH_AD",
                "system_managed_source": "AD_VARIATIONS",
                "ad_group_id": "204135195030",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "21359547724",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "825281476311", "final_urls": ["https://exemplo.com.br"]}],
    )
    assert result is not None
    assert "111" not in result
    assert "222" not in result
    assert "base" in result.lower()
