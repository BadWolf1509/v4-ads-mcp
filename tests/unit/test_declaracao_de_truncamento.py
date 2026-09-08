"""§3.2 da spec: tool que corta tem que dizer que cortou.

Por que propriedade e nao lista: a versao "lista de tools que precisam de
`truncated`" passa verde para a tool NOVA que ninguem lembrou de listar, que e
exatamente como as 9 desta frente chegaram a producao. O escopo aqui e derivado
do registry — tool nova com `limit` entra sozinha.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from src.mcp.tools._registry import all_tools, import_all_tools
from tests.unit import _guard_harness as h

import_all_tools()


def _tools_com_limite() -> list[tuple[str, Path]]:
    achados = []
    for t in all_tools():
        props = (t.input_schema or {}).get("properties", {})
        if "limit" not in props:
            continue
        arquivo = Path(sys.modules[t.handler.__module__].__file__ or "")
        achados.append((t.name, arquivo))
    if not achados:
        raise h.EscopoVazioError(
            "nenhuma tool declara `limit` — o registry nao carregou, e o guard "
            "estaria passando sem olhar nada"
        )
    return sorted(achados)


def _chaves_de_retorno(arquivo: Path) -> set[str]:
    """Chaves string de TODO dict literal do modulo.

    Deliberadamente largo: o retorno de varias tools e montado em variavel e so
    depois devolvido, entao olhar so o `ast.Return` veria dict vazio. Largo aqui
    erra para o lado de ABSOLVER, e quem fecha essa folga e o teste de mordida
    do Step 7.
    """
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    chaves: set[str] = set()
    for node in ast.walk(arvore):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    chaves.add(k.value)
    return chaves


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Task 2 fecha as 9 nomeadas no brief; o guard hoje acusa 14 — os outros "
        "5 (audit_competitor_keywords, get_assets, meta_get_ad_performance, "
        "meta_get_ad_set_performance, meta_get_campaign_performance) sao achado "
        "da Task 1, fora do escopo da Task 2 (ver task-1-report.md). Remover a "
        "marca so fecha o suite se as 14 fecharem, nao so as 9."
    ),
)
def test_toda_tool_com_limite_declara_truncated() -> None:
    """Achado da Task 1 (nao ajustado aqui — guard e propriedade, nao lista):

    O scanner olha só o módulo onde o `handler` está definido
    (`sys.modules[t.handler.__module__]`). 4 dos 5 extras (o trio
    `meta_get_{campaign,ad_set,ad}_performance` + `get_assets`) já computam e
    devolvem `truncated` em produção, só que a chave literal mora num MÓDULO
    HELPER compartilhado (`_meta_performance.py::run_meta_level_performance` /
    `google_ads/asset_inventory.py::build_inventory`) que este scanner não
    atravessa — falso positivo estrutural, não mentira em produção. O 5º,
    `audit_competitor_keywords`, é diferente: não tem NENHUMA chave literal
    `truncated` (nem no próprio módulo nem no helper `competitor_analysis.py`)
    porque corta DUAS listas com o mesmo `limit` e declara duas flags
    compostas (`positive_keywords_truncated`, `search_terms_truncated`) em vez
    de uma `truncated` única — forma genuinamente diferente da propriedade
    testada aqui, não um blind spot de varredura.
    """
    sem = [nome for nome, arq in _tools_com_limite() if "truncated" not in _chaves_de_retorno(arq)]
    assert sem == [], f"estas tools cortam resultado e nao dizem que cortaram (spec 3.2): {sem}"


def test_nenhuma_tool_devolve_truncated_constante() -> None:
    """`"truncated": False` fixo satisfaz o teste de cima e mente igual.

    Esta e a assercao que distingue "o campo existe" de "o campo e computado" —
    sem ela o guard de cima e satisfeito por um literal, que e a familia
    "asserir o adjacente a invariante".
    """
    ofensores: list[str] = []
    for nome, arq in _tools_com_limite():
        arvore = ast.parse(arq.read_text(encoding="utf-8"))
        for node in ast.walk(arvore):
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values, strict=True):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "truncated"
                    and isinstance(v, ast.Constant)
                ):
                    ofensores.append(f"{nome}:{k.lineno}")
    assert ofensores == [], f"`truncated` como literal nao e deteccao, e decoracao: {ofensores}"


def test_o_guard_enxerga_as_duas_formas_erradas() -> None:
    """Mordida: prova que as assercoes acima distinguem codigo bom de quebrado."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        bom = Path(d) / "bom.py"
        bom.write_text('def f():\n    return {"rows": [], "truncated": t}\n', encoding="utf-8")
        assert "truncated" in _chaves_de_retorno(bom)

        mudo = Path(d) / "mudo.py"
        mudo.write_text('def f():\n    return {"rows": []}\n', encoding="utf-8")
        assert "truncated" not in _chaves_de_retorno(mudo)
