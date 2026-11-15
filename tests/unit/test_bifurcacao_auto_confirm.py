"""Caracterizacao da bifurcacao AUTO/CONFIRM das tools que usam `aplicar_ou_pedir_confirmacao`.

Escrita ANTES da troca (T5.1, 15/11) e vista em PASS contra o corpo antigo, em
que cada tool ramificava em `risk.level` a mao. Os dicts esperados foram
copiados do codigo de entao: o que vai ao `run_mutation` no ramo AUTO, o que
vai ao `emitir_preview` no ramo CONFIRM e o envelope devolvido.

Os fakes sao instalados nos DOIS lugares onde o nome pode ser resolvido — o
modulo da tool (corpo antigo) e `_mutate_common` (helper) — com
`raising=False`, para que a mesma caracterizacao rode antes e depois da troca.
O `run_mutation` gravado passa pela assinatura real (`bind` + defaults): chamar
com `params_summary=None` explicito ou omiti-lo e a mesma chamada.

O que fica de fora: o `run_mutation` e o `emitir_preview` reais (cobertos em
`test_mutate_common.py`, nos testes de cada tool e na integracao).
"""

import importlib
import inspect
from typing import Any

import pytest

from src.google_ads.mutations import run_mutation as _run_mutation_real
from src.governance.blast_radius import RiskClassification, RiskLevel
from src.mcp.context import McpRequestContext
from src.mcp.tools import _mutate_common
from src.mcp.tools._mutate_common import emitir_preview as _emitir_preview_real

_MOTIVO = "motivo-da-caracterizacao"
_CID = "1234567890"
_RESULTADO_MUTACAO = {
    "provider_request_id": "req-caract",
    "applied_count": 2,
    "partial_failures": [],
}
_SENTINELA_PREVIEW = {"status": "dry_run", "sentinela": True}

# (tool, args, params esperados no classify, payload, resumo)
_TOOLS: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any], str]] = [
    (
        "update_campaign_status",
        {"customer_id": _CID, "campaign_ids": ["111", "222"], "new_status": "PAUSED"},
        {"target_count": 2, "new_status": "PAUSED"},
        {"campaign_ids": ["111", "222"], "new_status": "PAUSED", "__target_count__": 2},
        "Mudar status de 2 campanha(s) (111, 222) para PAUSED.",
    ),
    (
        "update_ad_group_status",
        {
            "customer_id": _CID,
            "ad_group_ids": ["1", "2", "3", "4"],
            "new_status": "ENABLED",
        },
        {"target_count": 4, "new_status": "ENABLED"},
        {"ad_group_ids": ["1", "2", "3", "4"], "new_status": "ENABLED", "__target_count__": 4},
        "Mudar status de 4 grupo(s) (1, 2, 3...) para ENABLED.",
    ),
    (
        "update_ad_status",
        {
            "customer_id": _CID,
            "ads": [{"ad_group_id": "9", "ad_id": "71"}, {"ad_group_id": "9", "ad_id": "72"}],
            "new_status": "PAUSED",
        },
        {"target_count": 2, "new_status": "PAUSED"},
        {
            "ads": [{"ad_group_id": "9", "ad_id": "71"}, {"ad_group_id": "9", "ad_id": "72"}],
            "new_status": "PAUSED",
            "__target_count__": 2,
        },
        "Mudar status de 2 anuncio(s) (71, 72) para PAUSED.",
    ),
]


def _efetivos(funcao: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Os argumentos como a funcao real os veria: defaults aplicados."""
    ligados = inspect.signature(funcao).bind(**kwargs)
    ligados.apply_defaults()
    return dict(ligados.arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize("nivel", [RiskLevel.AUTO, RiskLevel.CONFIRM], ids=["auto", "confirm"])
@pytest.mark.parametrize(
    ("tool", "args", "params", "payload", "resumo"), _TOOLS, ids=[t[0] for t in _TOOLS]
)
async def test_bifurcacao_preserva_chamadas_e_envelope(
    monkeypatch: pytest.MonkeyPatch,
    ctx_mcp: McpRequestContext,
    tool: str,
    args: dict[str, Any],
    params: dict[str, Any],
    payload: dict[str, Any],
    resumo: str,
    nivel: RiskLevel,
) -> None:
    mod = importlib.import_module(f"src.mcp.tools.{tool}")
    risk = RiskClassification(level=nivel, reason=_MOTIVO)
    gravado: dict[str, list[dict[str, Any]]] = {"classify": [], "run_mutation": [], "preview": []}

    def _classify(**kw: Any) -> RiskClassification:
        gravado["classify"].append(kw)
        return risk

    async def _run_mutation(**kw: Any) -> dict[str, Any]:
        gravado["run_mutation"].append(_efetivos(_run_mutation_real, kw))
        return dict(_RESULTADO_MUTACAO)

    async def _emitir_preview(ctx: Any, **kw: Any) -> dict[str, Any]:
        gravado["preview"].append(_efetivos(_emitir_preview_real, {"ctx": ctx, **kw}))
        return dict(_SENTINELA_PREVIEW)

    monkeypatch.setattr(mod, "classify", _classify)
    for alvo in (mod, _mutate_common):
        monkeypatch.setattr(alvo, "run_mutation", _run_mutation, raising=False)
        monkeypatch.setattr(alvo, "emitir_preview", _emitir_preview, raising=False)

    envelope = await getattr(mod, tool)(args)

    assert gravado["classify"] == [{"operation": tool, "params": params}]
    if nivel is RiskLevel.AUTO:
        assert gravado["preview"] == []
        assert gravado["run_mutation"] == [
            {
                "manager_id": ctx_mcp.manager_id,
                "session_id": ctx_mcp.session_id,
                "customer_id": _CID,
                "operation_type": tool,
                "payload": payload,
                "target_count": params["target_count"],
                "partial_failure": False,
                "params_summary": None,
            }
        ]
        assert envelope == {
            "status": "applied",
            "operation": tool,
            "customer_id": _CID,
            "blast_summary": resumo,
            "applied_count": 2,
            "provider_request_id": "req-caract",
            "auto_applied_reason": _MOTIVO,
        }
    else:
        assert gravado["run_mutation"] == []
        assert gravado["preview"] == [
            {
                "ctx": ctx_mcp,
                "operation": tool,
                "customer_id": _CID,
                "payload": payload,
                "resumo": resumo,
                "risk": risk,
                "extra": {},
            }
        ]
        assert envelope == _SENTINELA_PREVIEW
