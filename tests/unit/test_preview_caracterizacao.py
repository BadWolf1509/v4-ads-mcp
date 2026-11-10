"""Caracterizacao do envelope de dry-run de 3 tools que migram para `emitir_preview` (D3).

O envelope e CONTRATO (o cliente LLM le, o gestor confirma): chaves, valores e
ORDEM das chaves tem que sair identicos antes e depois da migracao. O token e
fixo (fake de `create_pending`); o relogio e congelado onde o preview o le.
Tambem grava o que chega no `create_pending` (operation_type, payload, resumo).

O fake de `create_pending` e instalado onde o nome e PROCURADO: no modulo da
tool (antes da migracao) e em `_mutate_common` (depois) — o teste vale nos dois.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from freezegun import freeze_time

import src.mcp.tools._mutate_common as mc
from src.mcp.context import McpRequestContext, clear_current, set_current

_AGORA = "2026-11-10 12:00:00"  # UTC; 09:00 em Sao Paulo

_CHAVES_BASE = [
    "status",
    "operation",
    "customer_id",
    "blast_summary",
    "confirmation_token",
    "expires_in_minutes",
    "to_apply",
    "confirmation_reason",
]


class _Pool:
    def acquire(self) -> _Pool:
        return self

    async def __aenter__(self) -> str:
        return "CONN"

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def captura(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    capturado: dict[str, Any] = {}

    async def _create_pending(conn: Any, **kwargs: Any) -> str:
        capturado.clear()
        capturado.update(kwargs)
        return "TOKEN-FIXO"

    monkeypatch.setattr("src.db.connection.get_pool", lambda: _Pool())
    monkeypatch.setattr(mc, "create_pending", _create_pending)
    for nome in (
        "create_and_link_assets",
        "import_offline_conversions",
        "upload_customer_match_list",
    ):
        mod = importlib.import_module(f"src.mcp.tools.{nome}")
        if hasattr(mod, "create_pending"):
            monkeypatch.setattr(mod, "create_pending", _create_pending)
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield capturado
    clear_current()


def _pendencia(c: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in c.items() if k not in ("manager_id", "session_id")}


async def test_create_and_link_assets(captura: dict[str, Any]) -> None:
    from src.mcp.tools.create_and_link_assets import create_and_link_assets

    out = await create_and_link_assets(
        {
            "customer_id": "1234567890",
            "assets": [
                {
                    "type": "SITELINK",
                    "attachment_level": "CAMPAIGN",
                    "attachment_id": "customers/1234567890/campaigns/99999",
                    "link_text": "Sobre nós",
                    "final_urls": ["https://example.com/sobre"],
                }
            ],
        }
    )
    assert list(out) == [*_CHAVES_BASE, "summary"]
    assert out["status"] == "dry_run"
    assert out["operation"] == "create_and_link_assets"
    assert out["customer_id"] == "1234567890"
    assert out["confirmation_token"] == "TOKEN-FIXO"
    assert out["expires_in_minutes"] == 10
    assert out["to_apply"] == mc._APPLY_HINT
    assert out["blast_summary"] == _RESUMO_ASSETS
    assert out["confirmation_reason"] == _MOTIVO_ASSETS
    assert out["summary"] == _SUMMARY_ASSETS
    cp = _pendencia(captura)
    assert cp["operation_type"] == "create_and_link_assets"
    assert cp["customer_id"] == "1234567890"
    assert cp["blast_summary"] == out["blast_summary"]
    assert list(cp["payload"]) == [
        "customer_id",
        "assets",
        "__target_count__",
        "__params_summary__",
    ]
    assert cp["payload"]["__params_summary__"] == out["summary"]
    assert cp["payload"]["__target_count__"] == out["summary"]["total_ops_chained"]


@freeze_time(_AGORA)
async def test_import_offline_conversions(
    captura: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.mcp.tools import import_offline_conversions as mod

    async def _zone(customer_id: str) -> str | None:
        return "America/Sao_Paulo"

    monkeypatch.setattr(mod, "resolve_account_zone", _zone)
    monkeypatch.setattr(mod, "validate_conversion_action_for_upload", AsyncMock(return_value=None))
    out = await mod.import_offline_conversions(
        {
            "customer_id": "1234567890",
            "conversion_action_id": "987654321",
            "conversions": [
                {
                    "gclid": "Cj0KCQjwTEST_VALID_GCLID_001",
                    "conversion_date_time": "2026-11-10 08:30:00",
                    "conversion_value_brl": 100.0,
                }
            ],
        }
    )
    assert list(out) == [*_CHAVES_BASE, "summary"]
    assert out["status"] == "dry_run"
    assert out["operation"] == "import_offline_conversions"
    assert out["customer_id"] == "1234567890"
    assert out["confirmation_token"] == "TOKEN-FIXO"
    assert out["expires_in_minutes"] == 10
    assert out["to_apply"] == mc._APPLY_HINT
    assert out["blast_summary"] == _RESUMO_IMPORT
    assert out["confirmation_reason"] == _MOTIVO_IMPORT
    assert out["summary"] == _SUMMARY_IMPORT
    cp = _pendencia(captura)
    assert cp["operation_type"] == "import_offline_conversions"
    assert cp["customer_id"] == "1234567890"
    assert cp["blast_summary"] == out["blast_summary"]
    assert list(cp["payload"]) == [
        "customer_id",
        "conversion_action_id",
        "conversions",
        "__target_count__",
        "__params_summary__",
        "__time_zone__",
    ]
    assert cp["payload"]["__time_zone__"] == "America/Sao_Paulo"
    assert cp["payload"]["__params_summary__"] == out["summary"]


async def test_upload_customer_match_list(
    captura: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.mcp.tools import upload_customer_match_list as mod

    monkeypatch.setattr(mod, "validate_user_list_for_upload", AsyncMock(return_value=None))
    out = await mod.upload_customer_match_list(
        {
            "customer_id": "1163862076",
            "user_list_id": "1234567890",
            "operation": "add",
            "members": [{"email": "user1@example.com"}, {"phone_number": "+5511987654321"}],
        }
    )
    assert list(out) == [
        *_CHAVES_BASE,
        "user_list_id",
        "operation_type",
        "members_count",
    ]
    assert out["status"] == "dry_run"
    assert out["operation"] == "upload_customer_match_list"
    assert out["customer_id"] == "1163862076"
    assert out["blast_summary"] == (
        "Upload Customer Match: ADD 2 membro(s) pra user_list_id=1234567890."
    )
    assert out["confirmation_token"] == "TOKEN-FIXO"
    assert out["expires_in_minutes"] == 10
    assert out["confirmation_reason"] == _MOTIVO_UPLOAD
    assert out["to_apply"] == (
        "Chame apply_change(confirmation_token=<token>) para submeter o job. "
        "Job é assíncrono no backend Google — após apply, tool retorna "
        "job_resource_name. Pra checar status posterior, use run_gaql com "
        "query 'SELECT offline_user_data_job.status, failure_reason FROM "
        "offline_user_data_job WHERE offline_user_data_job.id = <id>'."
    )
    assert out["user_list_id"] == "1234567890"
    assert out["operation_type"] == "add"
    assert out["members_count"] == 2
    cp = _pendencia(captura)
    assert cp["operation_type"] == "upload_customer_match_list"
    assert cp["customer_id"] == "1163862076"
    assert cp["blast_summary"] == out["blast_summary"]
    assert list(cp["payload"]) == [
        "user_list_id",
        "operation",
        "hashed_members",
        "__target_count__",
    ]
    assert cp["payload"]["__target_count__"] == 2


_RESUMO_ASSETS = (
    "Criar 1 asset(s) text-extension + 1 link(s). Tipos: SITELINK:1. Níveis: CAMPAIGN:1."
)
_MOTIVO_ASSETS = (
    "create_and_link_assets: cria asset(s) e vincula a campanha/grupo — "
    "muda o que veicula, sempre CONFIRM (spec §7.1 creates)"
)
_SUMMARY_ASSETS: dict[str, Any] = {
    "asset_count": 1,
    "by_type": {"SITELINK": 1},
    "by_level": {"CAMPAIGN": 1},
    "attachment_ids_distinct": 1,
    "total_ops_chained": 2,
}
_RESUMO_IMPORT = "Importar 1 conversões offline (sum R$ 100.00, range 2026-11-10 08:30:00 → 2026-11-10 08:30:00) pra conversion_action_id=987654321"
_MOTIVO_IMPORT = (
    "import_offline_conversions: importa conversoes que entram no sinal do "
    "Smart Bidding e nao tem volta — sempre CONFIRM (spec §7.1 tracking)"
)
_SUMMARY_IMPORT: dict[str, Any] = {
    "conversion_count": 1,
    "sum_value_brl": 100.0,
    "date_range": {"earliest": "2026-11-10 08:30:00", "latest": "2026-11-10 08:30:00"},
    "gclids_distinct": 1,
    "order_ids_present": 0,
    "conversion_action_id": "987654321",
    "time_zone": "America/Sao_Paulo",
    "utc_offset": "-03:00",
}
_MOTIVO_UPLOAD = "upload_customer_match_list: 2 membro(s) — PII upload, sempre CONFIRM"
