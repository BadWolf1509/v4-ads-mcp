"""Snapshot do HTML das páginas de acesso Google/Meta (Task F5).

Os três pares de templates gêmeos (matriz, por gestor, detalhe do gestor)
viraram um template por par, parametrizado pela plataforma. Este snapshot foi
gravado ANTES da unificação, contra os seis templates antigos, e prova que a
unificação não mudou o HTML entregue: a comparação só tolera diferença de
espaço em branco (`_normalizar`).

Renderiza pela ROTA (handler chamado direto, com a leitura do banco e a
contagem de convites trocadas por dados fixos), não pelo template: assim o
snapshot cobre também o contexto que a rota monta, que é onde a plataforma
passa a ser escolhida depois da unificação.

Regravar (só quando a mudança no HTML é deliberada, e com o motivo no commit):
`V4_REGRAVAR_SNAPSHOT_ACESSO=1 pytest tests/unit/test_acesso_templates_snapshot.py`.
"""

import asyncio
import os
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from src.db.repositories.google_ads_accounts import GoogleAdsAccount
from src.db.repositories.meta_ad_accounts import MetaAdAccount
from src.web.routes import admin_access
from src.web.routes._shared import templates

_SNAPSHOTS = Path(__file__).parent / "fixtures" / "acesso_snapshot"
_REGRAVAR = os.getenv("V4_REGRAVAR_SNAPSHOT_ACESSO") == "1"

_M1 = "11111111-1111-1111-1111-111111111111"
_M2 = "22222222-2222-2222-2222-222222222222"
_SYNC = datetime(2026, 11, 3, tzinfo=UTC)

_GESTORES = [
    {"id": _M1, "email": "ana.teste@v4company.com", "full_name": "Ana Teste"},
    {"id": _M2, "email": "bruno.teste@v4company.com", "full_name": None},
]
_GESTORES_COM_CONTAGEM = [
    {**_GESTORES[0], "access_count": 1},
    {**_GESTORES[1], "access_count": 0},
]

_CONTAS_GOOGLE = [
    GoogleAdsAccount(
        customer_id="1000000001",
        mcc_id="9999999999",
        descriptive_name="Loja Fictícia & <Cia>",
        currency_code="BRL",
        time_zone="America/Sao_Paulo",
        is_test_account=False,
        is_active=True,
        synced_at=_SYNC,
    ),
    GoogleAdsAccount(
        customer_id="1000000002",
        mcc_id="9999999999",
        descriptive_name="Clínica Exemplo",
        currency_code="BRL",
        time_zone="America/Sao_Paulo",
        is_test_account=False,
        is_active=True,
        synced_at=_SYNC,
    ),
]


def _conta_meta(ad_account_id: str, nome: str, status: int, bm: str | None) -> MetaAdAccount:
    return MetaAdAccount(
        ad_account_id=ad_account_id,
        business_id="555" if bm else None,
        business_name=bm,
        account_name=nome,
        currency="BRL",
        timezone_name="America/Sao_Paulo",
        account_status=status,
        is_active=True,
        synced_at=_SYNC,
    )


_CONTAS_META = [
    _conta_meta("act_2000000001", "Padaria Fictícia & <Cia>", 1, "BM Exemplo"),
    _conta_meta("act_2000000002", "Academia Exemplo", 2, None),
]

_ADMIN = SimpleNamespace(
    id="00000000-0000-0000-0000-0000000000ad",
    email="admin.teste@v4company.com",
    is_admin=True,
)


def _request(path: str, query: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("teste", 80),
            "root_path": "",
            "path": path,
            "query_string": query.encode(),
            "headers": [],
        }
    )


def _render(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[..., Awaitable[Any]],
    carga: Any,
    path: str,
    query: str = "",
    **kwargs: Any,
) -> str:
    async def _run_with_reconnect(_load: Any) -> Any:
        return carga

    async def _pendentes() -> int:
        return 2

    monkeypatch.setattr(admin_access.connection, "run_with_reconnect", _run_with_reconnect)
    monkeypatch.setattr(admin_access, "pending_invites_count", _pendentes)
    monkeypatch.setitem(templates.env.globals, "asset_version", "snap")
    resposta = asyncio.run(handler(_request(path, query), user=_ADMIN, **kwargs))
    return bytes(resposta.body).decode("utf-8")


def _normalizar(html: str) -> str:
    """Só espaço em branco: colapsa sequências e some com o que fica entre tags."""
    html = re.sub(r"\s+", " ", html)
    return re.sub(r">\s+<", "><", html).strip()


def _acessos_google() -> list[dict[str, str]]:
    return [{"manager_id": _M1, "customer_id": "1000000001"}]


def _acessos_meta() -> list[dict[str, str]]:
    return [{"manager_id": _M1, "ad_account_id": "act_2000000001"}]


_CASOS: dict[str, tuple[str, Callable[[], tuple[Any, ...]], str, str, dict[str, Any]]] = {
    "google_matriz": (
        "admin_access",
        lambda: (_GESTORES, _CONTAS_GOOGLE, _acessos_google()),
        "/admin/access",
        "error=same_manager",
        {},
    ),
    "google_matriz_sem_gestor": (
        "admin_access",
        lambda: ([], _CONTAS_GOOGLE, []),
        "/admin/access",
        "",
        {},
    ),
    "google_matriz_sem_conta": (
        "admin_access",
        lambda: (_GESTORES, [], []),
        "/admin/access",
        "",
        {},
    ),
    "google_por_gestor": (
        "admin_access_by_manager",
        lambda: (_GESTORES_COM_CONTAGEM, 2),
        "/admin/access/by-manager",
        "",
        {},
    ),
    "google_detalhe": (
        "admin_access_manager_detail",
        lambda: (_GESTORES[0], _CONTAS_GOOGLE, {"1000000001"}),
        f"/admin/access/{_M1}",
        "",
        {"manager_id": _M1},
    ),
    "meta_matriz": (
        "admin_access_meta",
        lambda: (_GESTORES, _CONTAS_META, _acessos_meta()),
        "/admin/access/meta",
        "error=same_manager",
        {},
    ),
    "meta_matriz_sem_gestor": (
        "admin_access_meta",
        lambda: ([], _CONTAS_META, []),
        "/admin/access/meta",
        "",
        {},
    ),
    "meta_matriz_sem_conta": (
        "admin_access_meta",
        lambda: (_GESTORES, [], []),
        "/admin/access/meta",
        "",
        {},
    ),
    "meta_por_gestor": (
        "admin_access_meta_by_manager",
        lambda: (_GESTORES_COM_CONTAGEM, 2),
        "/admin/access/meta/by-manager",
        "",
        {},
    ),
    "meta_detalhe": (
        "admin_access_meta_manager_detail",
        lambda: (_GESTORES[0], _CONTAS_META, {"act_2000000001"}),
        f"/admin/access/meta/{_M1}",
        "",
        {"manager_id": _M1},
    ),
}


@pytest.mark.parametrize("caso", sorted(_CASOS))
def test_html_das_paginas_de_acesso_so_muda_em_espaco(
    monkeypatch: pytest.MonkeyPatch, caso: str
) -> None:
    nome_handler, carga, path, query, kwargs = _CASOS[caso]
    handler = getattr(admin_access, nome_handler)
    html = _render(monkeypatch, handler, carga(), path, query, **kwargs)
    arquivo = _SNAPSHOTS / f"{caso}.html"
    if _REGRAVAR:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(html.replace("\r\n", "\n").encode("utf-8"))
    assert arquivo.exists(), f"snapshot ausente: {arquivo.name} (ver docstring do módulo)"
    esperado = arquivo.read_text(encoding="utf-8")
    assert _normalizar(html) == _normalizar(esperado), (
        f"{caso}: o HTML mudou além de espaço em branco"
    )


def test_snapshot_cobre_as_seis_paginas() -> None:
    """Piso contra parametrize vazio: cada handler das 6 páginas tem caso."""
    handlers = {h for h, *_ in _CASOS.values()}
    assert handlers == {
        "admin_access",
        "admin_access_meta",
        "admin_access_by_manager",
        "admin_access_meta_by_manager",
        "admin_access_manager_detail",
        "admin_access_meta_manager_detail",
    }
