"""Os guards do contrato das métricas Meta (spec 2026-09-26, §6).

O defeito que o spec fecha é o F189/F190 de novo: a mesma regra consertada num gêmeo
e não no outro (`insights.py` e `account_overview.py` liam os mesmos campos por regras
diferentes). O contrato único só fica único se nada mais puder ler métrica da linha
Graph, e se toda chamada /insights sair do construtor que põe a atribuição. E como o
contrato mudou de número para null, quem lê a tool (o LLM) tem de ser avisado.
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.meta_ads.metricas import FRASE_DA_ATRIBUICAO, FRASE_DO_CTR, FRASE_DO_NULL
from tests.unit import _guard_harness as h

# Os campos de métrica que a linha /insights traz (`insights._COMMON_INSIGHTS_FIELDS`).
_CHAVES_DE_METRICA = frozenset(
    {
        "spend",
        "impressions",
        "clicks",
        "ctr",
        "cpc",
        "reach",
        "frequency",
        "actions",
        "action_values",
        "purchase_roas",
    }
)
_CONTRATO = h.SRC / "meta_ads" / "metricas.py"
_CONSTRUTOR = (h.SRC / "meta_ads" / "insights.py", "build_insights_call")


def _arquivos_meta() -> list[Path]:
    """`src/meta_ads/` inteiro + as tools e helpers Meta de `src/mcp/tools/`.

    O CONJUNTO de raizes e afirmado, nao um piso numerico: uma pasta sumindo da
    varredura enquanto a outra cresce passaria por qualquer piso.
    """
    ferramentas = h.SRC / "mcp" / "tools"
    arquivos = h.fontes_py(h.SRC / "meta_ads") + [
        p for p in h.fontes_py(ferramentas) if p.stem.startswith(("meta_", "_meta_"))
    ]
    raizes = {p.parent.name for p in arquivos}
    assert raizes == {"meta_ads", "tools"}, raizes
    assert any(p.stem == "meta_get_account_overview" for p in arquivos)
    return arquivos


def _leituras_de_metrica(arv: ast.Module) -> list[tuple[int, str]]:
    """`x.get("<metrica>")` e `x["<metrica>"]`, com a linha."""
    achados = []
    for no in ast.walk(arv):
        chave = None
        if (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr == "get"
            and no.args
            and isinstance(no.args[0], ast.Constant)
        ):
            chave = no.args[0].value
        elif isinstance(no, ast.Subscript) and isinstance(no.slice, ast.Constant):
            chave = no.slice.value
        if isinstance(chave, str) and chave in _CHAVES_DE_METRICA:
            achados.append((no.lineno, chave))
    return achados


def test_so_o_contrato_le_metrica_da_linha_graph() -> None:
    """Um segundo leitor de `actions`/`reach`/... e um segundo contrato — o F190."""
    ofensores = []
    lidas_no_contrato = 0
    for arquivo in _arquivos_meta():
        leituras = _leituras_de_metrica(h.arvore(arquivo))
        if arquivo == _CONTRATO:
            lidas_no_contrato = len(leituras)
            continue
        ofensores += [f"{h.rel(arquivo)}:{linha} le {chave!r}" for linha, chave in leituras]
    assert not ofensores, (
        "metrica da linha Graph lida fora de `src/meta_ads/metricas.py`: "
        f"{ofensores}. Use `metricas_da_linha` — a regra do null, do nome canonico e "
        "da unidade mora so la (spec 2026-09-26)."
    )
    assert lidas_no_contrato >= 10, "o contrato parou de ler as metricas — o guard perdeu o alvo"


def _ids_dentro(arv: ast.Module, funcao: str) -> set[int]:
    alvo = next(n for n in ast.walk(arv) if isinstance(n, ast.FunctionDef) and n.name == funcao)
    return {id(n) for n in ast.walk(alvo)}


def test_toda_chamada_insights_sai_do_construtor_unico() -> None:
    """O construtor põe a atribuição unificada; params montados a mão não põem.

    Medido: o overview montava os params à mão e mandava `ad_account_id` espúrio à
    Graph API — o índice da varredura o dava como fechado pelo F190.
    """
    arquivo_construtor, funcao = _CONSTRUTOR
    ofensores = []
    dentro_do_construtor = 0
    for arquivo in _arquivos_meta():
        arv = h.arvore(arquivo)
        docstrings = h._nos_de_docstring(arv)
        permitidos = _ids_dentro(arv, funcao) if arquivo == arquivo_construtor else set()
        for lit in h._literais_de_string(arv):
            if id(lit) in docstrings or "/insights" not in h._texto_logico(lit):
                continue
            if id(lit) in permitidos:
                dentro_do_construtor += 1
                continue
            ofensores.append(f"{h.rel(arquivo)}:{lit.lineno}")
    assert dentro_do_construtor == 1, "o construtor parou de montar o edge — guard sem alvo"
    assert not ofensores, (
        f"edge /insights montado fora de `build_insights_call`: {ofensores}. "
        "Chame o construtor: ele poe a atribuicao unificada (spec 2026-09-26, §4.2)."
    )


def _modulo(caminho: Path) -> str:
    return ".".join(caminho.relative_to(h.RAIZ).with_suffix("").parts)


def _tools_que_chegam_ao_contrato() -> set[str]:
    """Tool cujo modulo importa o contrato, direto ou por modulo de `src/` no meio.

    A populacao sai do grafo de import, nao de lista: tool Meta nova que devolva
    metrica cai aqui sozinha.
    """
    importa: dict[str, set[str]] = {}
    for p in h.fontes_py():
        alvos = set()
        for no in ast.walk(h.arvore(p)):
            if isinstance(no, ast.ImportFrom) and no.module:
                alvos.add(no.module)
            elif isinstance(no, ast.Import):
                alvos.update(a.name for a in no.names)
        importa[_modulo(p)] = alvos
    alcanca = {"src.meta_ads.metricas"}
    mudou = True
    while mudou:
        novos = {m for m, alvos in importa.items() if alvos & alcanca} - alcanca
        alcanca |= novos
        mudou = bool(novos)
    ferramentas = h.SRC / "mcp" / "tools"
    return {
        p.stem
        for p in h.fontes_py(ferramentas)
        if not p.stem.startswith("_") and _modulo(p) in alcanca
    }


def test_toda_tool_com_metrica_meta_avisa_o_contrato_na_description() -> None:
    """O contrato mudou de numero para null e de porcentagem para fracao."""
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    nomes = _tools_que_chegam_ao_contrato()
    assert len(nomes) >= 5, f"piso medido em 26/09: 5 tools; a varredura achou {sorted(nomes)}"
    faltando = {}
    for nome in sorted(nomes):
        tool = get_tool(nome)
        assert tool is not None, f"`{nome}` nao esta no registry com o nome do modulo"
        ausentes = [
            f
            for f in (FRASE_DO_NULL, FRASE_DO_CTR, FRASE_DA_ATRIBUICAO)
            if f not in tool.description
        ]
        if ausentes:
            faltando[nome] = ausentes
    assert not faltando, f"description sem a frase do contrato: {faltando}"
