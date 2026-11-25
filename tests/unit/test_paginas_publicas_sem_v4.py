"""Páginas públicas sem a V4 (desligamento, 25/11/2026): o produto é "Fluxo Certo Ads"."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web.templating import NOME_PRODUTO, templates

RAIZ = Path(__file__).resolve().parents[2]
PROIBIDOS = (
    "logo_v4",
    "V4 Ads MCP",
    "@v4company",
    "V4 Company",
    "V4 Lima",
    "Google V4",
    "admin V4",
    "clientes V4",
    "da sua unidade",
    "email corporativo",
)


@pytest.fixture
def navegador() -> TestClient:
    from src.app import create_app  # noqa: PLC0415 — exige o env do conftest

    return TestClient(create_app(skip_db_init=True), follow_redirects=False)


def test_nome_produto() -> None:
    assert NOME_PRODUTO == "Fluxo Certo Ads"
    assert templates.env.globals["nome_produto"] == NOME_PRODUTO


@pytest.mark.parametrize(
    "rota",
    [
        "/login",
        "/help",
        "/legal/privacy",
        "/legal/terms",
        "/legal/data-deletion-status/00000000-0000-0000-0000-000000000000",
        "/access-denied?reason=deactivated",
        "/access-denied?reason=not_invited",
    ],
)
def test_paginas_publicas_sem_v4(navegador: TestClient, rota: str) -> None:
    resp = navegador.get(rota)
    assert resp.status_code == 200
    assert NOME_PRODUTO in resp.text
    achados = [p for p in PROIBIDOS if p in resp.text]
    assert achados == [], f"{rota}: {achados}"


def test_nome_produto_num_lugar_so() -> None:
    literais = [
        str(p.relative_to(RAIZ))
        for p in (RAIZ / "src/web/templates").rglob("*.html")
        if NOME_PRODUTO in p.read_text(encoding="utf-8")
    ]
    assert literais == []


def test_templates_sem_v4() -> None:
    """Nenhum template (painel logado incluso) cita a V4 como marca ou operadora."""
    achados = [
        f"{p.relative_to(RAIZ)}: {termo}"
        for p in (RAIZ / "src/web/templates").rglob("*.html")
        for termo in PROIBIDOS
        if termo in p.read_text(encoding="utf-8")
    ]
    assert achados == []


def test_descricoes_das_tools_sem_v4() -> None:
    """O LLM do cliente lê as descrições: nada de "conta V4", "co-gestores V4" etc.

    Lê o snapshot `schemas_das_tools.json`, que `test_schemas_snapshot` mantém igual ao vivo.
    """
    import json  # noqa: PLC0415
    import re  # noqa: PLC0415

    schemas = json.loads(
        (RAIZ / "tests/unit/fixtures/schemas_das_tools.json").read_text(encoding="utf-8")
    )
    achados = sorted(
        nome
        for nome, texto in ((t["name"], json.dumps(t, ensure_ascii=False)) for t in schemas)
        if re.search(r"\bV4\b", texto)
    )
    assert achados == []
