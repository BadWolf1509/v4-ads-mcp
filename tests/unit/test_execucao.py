"""`encerrar_execucao`: o `finally` comum dos executores Google (P6, T6.2).

Contrato (F73/F83/F91):
- reconcile de cota só se a reserva foi persistida;
- audit em bloco `best_effort` próprio, INDEPENDENTE do reconcile: a falha de
  um não pula o outro, e nenhum dos dois levanta;
- o montador do audit roda DENTRO do `best_effort` (Review Focus 5): se ele
  levantar depois de a mutação já ter sido aplicada, o `return` do executor
  sobrevive e o erro vira log ERROR;
- sem montador, nenhuma conexão é pedida para audit.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any
from uuid import UUID

import pytest

from src.db.repositories import audit_log
from src.governance import bookkeeping
from src.governance.execucao import RegistroDeAudit, encerrar_execucao
from src.governance.reserva import Reserva

MANAGER = UUID("11111111-1111-1111-1111-111111111111")
SESSION = UUID("22222222-2222-2222-2222-222222222222")
_RESERVA = Reserva(dia_projeto=date(2026, 11, 15), dia_gestor=date(2026, 11, 15), estimated_ops=3)


class _FalhaDeIoError(Exception):
    """Stand-in de conexão asyncpg derrubada (F76)."""


class _Cm:
    def __init__(self, valor: Any = None) -> None:
        self._valor = valor

    async def __aenter__(self) -> Any:
        return self._valor

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Conn:
    def transaction(self) -> _Cm:
        return _Cm()


class _Pool:
    def __init__(self) -> None:
        self.acquires = 0

    def acquire(self) -> _Cm:
        self.acquires += 1
        return _Cm(_Conn())


class _Registro:
    def __init__(self) -> None:
        self.eventos: list[str] = []
        self.audits: list[dict[str, Any]] = []
        self.reconciles: list[int] = []
        self.falhas_logadas: list[tuple[str, dict[str, Any]]] = []
        self.falha_audit: Exception | None = None
        self.falha_record_actual: Exception | None = None


@pytest.fixture
def reg(monkeypatch: pytest.MonkeyPatch) -> _Registro:
    r = _Registro()

    async def record_actual(_conn: Any, _chave: str, *, actual_ops: int, **_kw: Any) -> None:
        r.eventos.append("reconcile")
        r.reconciles.append(actual_ops)
        if r.falha_record_actual is not None:
            raise r.falha_record_actual

    async def record(_conn: Any, **kw: Any) -> int:
        r.eventos.append("audit")
        r.audits.append(kw)
        if r.falha_audit is not None:
            raise r.falha_audit
        return 1

    class _Log:
        def exception(self, evento: str, **ctx: Any) -> None:
            r.falhas_logadas.append((evento, ctx))

    monkeypatch.setattr("src.governance.reserva.record_actual", record_actual)
    monkeypatch.setattr(audit_log, "record", record)
    monkeypatch.setattr(bookkeeping, "log", _Log())
    return r


def _registro(**campos: Any) -> RegistroDeAudit:
    base: dict[str, Any] = {
        "manager_id": MANAGER,
        "session_id": SESSION,
        "customer_id": "1234567890",
        "action_type": "mutate",
        "operation": "update_campaign_status",
        "status": "success",
    }
    base.update(campos)
    return RegistroDeAudit(**base)


async def _encerrar(pool: _Pool, reserva: Reserva | None, montar: Any) -> None:
    await encerrar_execucao(
        pool,  # type: ignore[arg-type]
        reserva,
        manager_id=MANAGER,
        actual_ops=2,
        operation="update_campaign_status",
        customer_id="1234567890",
        status="success",
        evento_cota="teste_quota_reconcile_failed",
        evento_audit="teste_audit_write_failed",
        montar_audit=montar,
    )


@pytest.mark.asyncio
async def test_caminho_feliz_reconcilia_e_audita_com_os_campos_do_registro(reg: _Registro) -> None:
    pool = _Pool()
    await _encerrar(pool, _RESERVA, lambda: _registro(target_count=1, had_effect=True))

    assert reg.eventos == ["reconcile", "reconcile", "audit"]
    assert reg.reconciles == [2, 2]
    assert reg.audits == [
        {
            "manager_id": MANAGER,
            "session_id": SESSION,
            "customer_id": "1234567890",
            "action_type": "mutate",
            "operation": "update_campaign_status",
            "status": "success",
            "target_count": 1,
            "params_summary": None,
            "provider_request_id": None,
            "error_message": None,
            "duration_ms": None,
            "platform": "google",
            "had_effect": True,
        }
    ]
    assert pool.acquires == 2
    assert reg.falhas_logadas == []


@pytest.mark.asyncio
async def test_sem_reserva_nao_reconcilia_e_audita(reg: _Registro) -> None:
    pool = _Pool()
    await _encerrar(pool, None, _registro)

    assert reg.eventos == ["audit"]
    assert pool.acquires == 1


@pytest.mark.asyncio
async def test_reconcile_que_falha_nao_pula_o_audit(reg: _Registro) -> None:
    reg.falha_record_actual = _FalhaDeIoError("conexao morta")
    pool = _Pool()

    await _encerrar(pool, _RESERVA, _registro)

    assert reg.eventos == ["reconcile", "audit"]
    assert reg.falhas_logadas == [
        (
            "teste_quota_reconcile_failed",
            {"operation": "update_campaign_status", "customer_id": "1234567890"},
        )
    ]


@pytest.mark.asyncio
async def test_audit_que_falha_nao_levanta(reg: _Registro) -> None:
    reg.falha_audit = _FalhaDeIoError("conexao morta")

    await _encerrar(_Pool(), _RESERVA, _registro)

    assert reg.eventos == ["reconcile", "reconcile", "audit"]
    assert reg.falhas_logadas == [
        (
            "teste_audit_write_failed",
            {
                "operation": "update_campaign_status",
                "customer_id": "1234567890",
                "status": "success",
            },
        )
    ]


@pytest.mark.asyncio
async def test_montador_que_levanta_nao_levanta(reg: _Registro) -> None:
    """Review Focus 5: montar o audit DEPOIS de a mutação já ter sido aplicada
    não pode derrubar o `return` do executor — o erro vira log ERROR."""

    def montar() -> RegistroDeAudit:
        raise KeyError("campo que o montador esperava")

    await _encerrar(_Pool(), _RESERVA, montar)

    assert reg.eventos == ["reconcile", "reconcile"]
    assert reg.audits == []
    assert [evento for evento, _ in reg.falhas_logadas] == ["teste_audit_write_failed"]


@pytest.mark.asyncio
async def test_acquire_que_falha_nao_levanta_nem_chama_o_montador(reg: _Registro) -> None:
    """O `best_effort` abre ANTES do `pool.acquire()`: é o `__aenter__` do acquire
    que falha numa conexão stale (F76)."""

    class _CmStale(_Cm):
        async def __aenter__(self) -> Any:
            raise _FalhaDeIoError("stale")

    class _PoolStale(_Pool):
        def acquire(self) -> _Cm:
            self.acquires += 1
            if self.acquires > 1:  # o do reconcile passa; o do audit cai
                return _CmStale()
            return _Cm(_Conn())

    chamadas: list[int] = []

    def montar() -> RegistroDeAudit:
        chamadas.append(1)
        return _registro()

    await _encerrar(_PoolStale(), _RESERVA, montar)

    assert chamadas == []
    assert [evento for evento, _ in reg.falhas_logadas] == ["teste_audit_write_failed"]


@pytest.mark.asyncio
async def test_sem_montador_nao_pega_conexao(reg: _Registro) -> None:
    pool = _Pool()

    await _encerrar(pool, _RESERVA, None)

    assert reg.eventos == ["reconcile", "reconcile"]
    assert pool.acquires == 1


@pytest.mark.asyncio
async def test_sem_reserva_e_sem_montador_nao_faz_io(reg: _Registro) -> None:
    pool = _Pool()

    await _encerrar(pool, None, None)

    assert reg.eventos == []
    assert pool.acquires == 0


@pytest.mark.asyncio
async def test_cancelamento_no_reconcile_propaga_e_pula_o_audit(reg: _Registro) -> None:
    """Minor 7 da revisão do P6: `CancelledError` é `BaseException`, e o
    `best_effort` só engole `Exception` — cancelar a task tem que cancelar, não
    virar log ERROR. O audit que viria depois não roda (como antes do P6)."""
    reg.falha_record_actual = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _encerrar(_Pool(), _RESERVA, _registro)

    assert reg.eventos == ["reconcile"]
    assert reg.falhas_logadas == []


@pytest.mark.asyncio
async def test_cancelamento_no_audit_propaga(reg: _Registro) -> None:
    reg.falha_audit = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _encerrar(_Pool(), _RESERVA, _registro)

    assert reg.eventos == ["reconcile", "reconcile", "audit"]
    assert reg.falhas_logadas == []
