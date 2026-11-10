"""`montar_bloco`: o bloco de orcamento compartilhado das duas tools de mutate."""

from __future__ import annotations

from src.google_ads.orcamento_compartilhado import montar_bloco

_CHAVES = {
    "budget_id",
    "budget_resource_name",
    "explicitly_shared",
    "amount_brl",
    "campaigns_in_batch",
    "campaigns_outside_batch",
    "ativas_fora_do_lote",
    "warning_pt",
}

_IRMAS = [
    {"campaign_id": "1", "campaign_name": "alvo", "status": "ENABLED"},
    {"campaign_id": "2", "campaign_name": "irma ativa", "status": "ENABLED"},
    {"campaign_id": "3", "campaign_name": "irma pausada", "status": "PAUSED"},
]


def _bloco(sufixo: str = "SUFIXO.") -> dict:
    return montar_bloco(
        budget_id="9",
        budget_resource_name="customers/1/campaignBudgets/9",
        amount_brl=310.0,
        irmas=_IRMAS,
        no_lote=lambda cid: cid == "1",
        sufixo_aviso=sufixo,
    )


def test_tem_as_oito_chaves() -> None:
    assert set(_bloco()) == _CHAVES


def test_conta_so_ativas_fora_do_lote() -> None:
    b = _bloco()
    assert b["campaigns_in_batch"] == ["1"]
    assert [c["campaign_id"] for c in b["campaigns_outside_batch"]] == ["2", "3"]
    # A pausada fora do lote entra na lista mas nao conta; a alvo (ativa) esta dentro.
    assert b["ativas_fora_do_lote"] == 1
    assert b["explicitly_shared"] is True
    assert b["amount_brl"] == 310.0


def test_warning_e_prefixo_mais_o_sufixo_dado() -> None:
    b = _bloco("Texto da consequencia.")
    assert b["warning_pt"] == (
        "Orcamento compartilhado 9 (R$ 310.00/dia) e de 3 campanha(s), 2 ativa(s); "
        "1 no lote, 2 fora (1 ativa(s)). Texto da consequencia."
    )
