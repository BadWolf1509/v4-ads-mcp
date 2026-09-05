"""F146: `import_offline_conversions` assumia `-03:00` fixo — e 2 das 25 contas sao UTC-4.

Achado pelo guard AST do F141 na primeira execucao. Dois lugares, mesma
premissa ("V4 BR-invariant"):

- `_validate_payload_shape` interpretava o `conversion_date_time` (naive, digitado
  pelo gestor no relogio local) como `-03:00`. Numa conta UTC-4 isso torna o
  instante **1h mais cedo** do que foi (o texto original do F146 no catalogo
  dizia o contrario — o teste com controle abaixo derrubou a afirmacao antes do
  codigo sair). Consequencia no validador: a janela de 90 dias fecha 1h ANTES
  do que deveria. Consequencia no upload: o carimbo vai ao Google 1h adiantado —
  uma conversao das 00:30 locais cai no dia anterior. Em silencio.
- `run_conversion_upload` anexava a string `-03:00` ao timestamp enviado ao
  Google. Nessas contas o carimbo ia com uma hora de erro — em silencio.

## O desenho

- O fuso vem de `google_ads_accounts.time_zone` (F141), resolvido UMA vez no
  dry-run e guardado no payload pendente (`__time_zone__`): preview e upload usam
  o mesmo fuso, e o preview MOSTRA o offset que vai ser enviado.
- `_validate_payload_shape(payload, *, tz)` — kwarg obrigatorio, sem default.
- O builder calcula o offset por timestamp a partir do fuso (`%z`), nao anexa
  string fixa.
- Decisao registrada (Wellington, 03/09): conta sem fuso no inventario ->
  **recusa com erro claro**. No F141 o fallback UTC valia porque era leitura;
  aqui um offset chutado grava timestamp errado em conta de cliente, em
  silencio — corrupcao de dado, nao ruido. Payload pendente sem `__time_zone__`
  (token de antes do deploy) -> erro, nunca `-03:00`.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from src.mcp.tools.import_offline_conversions import _validate_payload_shape
from tests.unit.test_run_conversion_upload import (
    _capture_client_with_success_response,
    _common_patches,
    _payload,
)

CAMPO_GRANDE = ZoneInfo("America/Campo_Grande")  # UTC-4
FORTALEZA = ZoneInfo("America/Fortaleza")  # UTC-3


def _conv_em(dt_local: datetime) -> dict[str, Any]:
    """Como o gestor digita: o relogio da parede, sem offset."""
    return {
        "gclid": "Cj0KCQjwTEST_F146",
        "conversion_date_time": dt_local.strftime("%Y-%m-%d %H:%M:%S"),
        "conversion_value_brl": 10.0,
    }


def _payload_com(conv: dict[str, Any]) -> dict[str, Any]:
    return {"customer_id": "3237459217", "conversion_action_id": "1", "conversions": [conv]}


# --- validacao: o fuso e USADO, nao so passado ---------------------------------


def test_conversao_de_meia_hora_atras_em_campo_grande_e_aceita_no_fuso_da_conta() -> None:
    conv = _conv_em(datetime.now(CAMPO_GRANDE) - timedelta(minutes=30))
    assert _validate_payload_shape(_payload_com(conv), tz=CAMPO_GRANDE) is None


def test_controle_hora_de_fortaleza_lida_em_campo_grande_e_futura() -> None:
    """CONTROLE: mesmo timestamp naive, fuso ERRADO no sentido que adianta -> rejeita.

    Hora de parede de UTC-3 lida como UTC-4 torna o instante 1h MAIS TARDE:
    "agora-30min" vira "+30min", fora da tolerancia de 5 min. Sem este teste, o
    de cima passaria com um `tz` ignorado. (Primeira versao deste controle
    estava no sentido inverso e falhou — o que derrubou a afirmacao errada do
    catalogo sobre a direcao do bug.)
    """
    conv = _conv_em(datetime.now(FORTALEZA) - timedelta(minutes=30))
    err = _validate_payload_shape(_payload_com(conv), tz=CAMPO_GRANDE)
    assert err is not None
    assert "futuro" in err["error_message"].lower()


def test_o_caso_real_do_validador_janela_de_90_dias_fechava_uma_hora_antes() -> None:
    """Conversao a 89d 23h 30min atras no relogio de Campo Grande: dentro dos 90 dias.

    Lida como -03:00 (o bug), o instante recua 1h -> 90d 00h 30min -> REJEITADA.
    No fuso certo -> aceita. E o unico erro que o -03:00 fixo causava no
    validador; o outro (carimbo adiantado) e do builder.
    """
    conv = _conv_em(datetime.now(CAMPO_GRANDE) - timedelta(days=89, hours=23, minutes=30))
    assert _validate_payload_shape(_payload_com(conv), tz=CAMPO_GRANDE) is None
    err = _validate_payload_shape(_payload_com(conv), tz=FORTALEZA)
    assert err is not None and "90 dias" in err["error_message"]


def test_validate_exige_tz_sem_default() -> None:
    """A licao do F141/F145: 'obrigatorio' se assere pela assinatura."""
    p = inspect.signature(_validate_payload_shape).parameters["tz"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY
    assert p.default is inspect.Parameter.empty


# --- builder: offset calculado do fuso, por timestamp -------------------------


async def _upload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    from src.google_ads.conversions import run_conversion_upload

    client, click_convs = _capture_client_with_success_response(1)
    patches = _common_patches(client)
    for p in patches:
        p.start()
    try:
        result = await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=payload,
            target_count=1,
            params_summary={"conversion_count": 1},
        )
    finally:
        for p in patches:
            p.stop()
    return result, click_convs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tz_name", "offset"),
    [
        ("America/Campo_Grande", "-04:00"),
        ("America/Boa_Vista", "-04:00"),
        ("America/Fortaleza", "-03:00"),
        ("America/Sao_Paulo", "-03:00"),
    ],
)
async def test_builder_anexa_o_offset_do_fuso_da_conta(tz_name: str, offset: str) -> None:
    payload = _payload()
    payload["__time_zone__"] = tz_name
    _, click_convs = await _upload(payload)
    assert click_convs[0].field("conversion_date_time") == f"2026-05-17 14:30:00{offset}"


@pytest.mark.asyncio
async def test_builder_sem_fuso_no_payload_recusa_e_nao_chama_o_google() -> None:
    """Token pendente de antes do deploy nao tem `__time_zone__`. Nunca `-03:00` chutado."""
    payload = _payload()
    payload.pop("__time_zone__", None)
    result, click_convs = await _upload(payload)
    assert result["status"] == "error"
    assert "fuso" in result["error_message"].lower()
    assert click_convs == [], "nenhuma ClickConversion pode ter sido montada"


# --- handler: recusa sem fuso; fuso e offset no dry-run -------------------------
#
# Estes dois passam de imediato (o handler ja esta corrigido quando foram escritos);
# a prova de que distinguem codigo bom de quebrado e a sabotagem (e) e (f).


async def _dry_run(monkeypatch_zone: str | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from unittest.mock import AsyncMock, patch

    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools import import_offline_conversions as mod

    captured: dict[str, Any] = {}

    async def _zone(customer_id: str) -> str | None:
        return monkeypatch_zone

    async def _create_pending(conn, **kwargs):
        captured.update(kwargs)
        return "TOKEN123"

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    try:
        with (
            patch.object(mod, "resolve_account_zone", _zone),
            patch.object(
                mod, "validate_conversion_action_for_upload", AsyncMock(return_value=None)
            ),
            patch.object(mod, "create_pending", _create_pending),
            patch.object(mod.connection, "get_pool", lambda: _FakePool()),
        ):
            out = await mod.import_offline_conversions(
                {
                    "customer_id": "3237459217",
                    "conversion_action_id": "1",
                    "conversions": [_conv_em(datetime.now(CAMPO_GRANDE) - timedelta(hours=1))],
                }
            )
    finally:
        clear_current()
    return out, (captured or None)


class _FakeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def acquire(self):
        return _FakeConn()


@pytest.mark.asyncio
async def test_handler_recusa_conta_sem_fuso_antes_de_criar_token() -> None:
    out, pending = await _dry_run(None)
    assert out["status"] == "error"
    assert "fuso" in out["error_message"].lower()
    assert pending is None, "sem fuso nao pode existir token pendente"


@pytest.mark.asyncio
async def test_dry_run_guarda_o_fuso_no_payload_e_mostra_o_offset_no_preview() -> None:
    out, pending = await _dry_run("America/Campo_Grande")
    assert pending is not None
    assert pending["payload"]["__time_zone__"] == "America/Campo_Grande"
    assert out["summary"]["time_zone"] == "America/Campo_Grande"
    assert out["summary"]["utc_offset"] == "-04:00"
