"""§3.2 da spec: tool que corta tem que dizer que cortou.

Por que propriedade e nao lista: a versao "lista de tools que precisam de
`truncated`" passa verde para a tool NOVA que ninguem lembrou de listar, que e
exatamente como as 9 desta frente chegaram a producao. O escopo aqui e derivado
do registry — tool nova com `limit` entra sozinha.
"""

from __future__ import annotations

import ast
import sys
import tempfile
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


def _chaves_alcancaveis(arquivo: Path, *, raiz: Path | None = None) -> set[str]:
    """`_chaves_de_retorno` do próprio módulo MAIS as dos módulos `src.*` que
    ele importa, um salto (`h.modulos_importados_de_src` — não transitivo).

    Cobre a tool que delega a montagem do retorno pra um helper compartilhado
    (`meta_get_ad_performance` etc. chamam `_meta_performance.py::
    run_meta_level_performance`; `get_assets` chama `asset_inventory.py::
    build_inventory`) — a chave `truncated` é computada e devolvida de
    verdade, só que no módulo errado pra um scanner que olha só
    `handler.__module__`.

    `raiz` é repassado pro resolvedor do harness só pra permitir o teste de
    mordida montar um `src.` falso; o guard em si sempre usa o default (raiz
    real do repo).
    """
    chaves = set(_chaves_de_retorno(arquivo))
    for helper in h.modulos_importados_de_src(arquivo, raiz=raiz):
        chaves |= _chaves_de_retorno(helper)
    return chaves


def _declara_truncamento(chaves: set[str]) -> bool:
    """`truncated` OU qualquer chave terminada em `_truncated`.

    O sufixo cobre `audit_competitor_keywords`: corta DUAS listas
    (`positive_keywords`, `search_terms`) sob o MESMO `limit` e declara duas
    flags compostas (`positive_keywords_truncated`, `search_terms_truncated`)
    em vez de uma `truncated` única — exigir uma única ali seria pior
    contrato (perderia qual das duas foi cortada), não melhor.
    """
    return "truncated" in chaves or any(c.endswith("_truncated") for c in chaves)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Correcao da rodada 1 (task-1-fix-1.md) fechou os 5 falsos-positivos "
        "do scanner (escopo por arquivo em vez de por propriedade). Sobram "
        "exatamente 9 tools que de fato nao declaram truncamento em lugar "
        "nenhum alcancavel: get_ad_group_performance, get_ad_performance, "
        "get_audience_performance, get_campaign_performance, "
        "get_change_history, get_geo_performance, get_keyword_performance, "
        "get_my_audit_log, get_search_terms_report. Task 2 fecha estas 9; "
        "remover a marca so fecha o suite quando elas fecharem."
    ),
)
def test_toda_tool_com_limite_declara_truncated() -> None:
    """Corrigido na rodada 1 (task-1-fix-1.md): a propriedade e "existe chave
    `truncated` OU `*_truncated`, no modulo do handler OU num modulo `src.*`
    que ele importe (um salto — `_chaves_alcancaveis`)", nao mais "existe
    `truncated` literal so no modulo do handler".

    A versao anterior confundia "o handler nao TEM a chave no proprio modulo"
    com "a tool nao DECLARA truncamento" — seguia acusando 5 tools que ja
    fazem a coisa certa: `meta_get_ad_performance`, `meta_get_ad_set_performance`
    e `meta_get_campaign_performance` delegam a `_meta_performance.py::
    run_meta_level_performance`, que devolve `"truncated"` de verdade;
    `get_assets` delega a `asset_inventory.py::build_inventory`, idem; e
    `audit_competitor_keywords` corta duas listas sob o mesmo `limit` e
    declara duas flags compostas (`positive_keywords_truncated`,
    `search_terms_truncated`) em vez de uma `truncated` unica — o sufixo
    cobre isso sem exigir uma chave unica pior (perderia qual lista cortou).

    As 9 que sobram (xfail acima) nao declaram truncamento nem no proprio
    modulo nem em nenhum modulo `src.*` que importem — confirmado lendo cada
    um dos handlers e seus imports de um salto (task-1-fix-1-report.md).
    """
    sem = [
        nome
        for nome, arq in _tools_com_limite()
        if not _declara_truncamento(_chaves_alcancaveis(arq))
    ]
    assert sem == [], f"estas tools cortam resultado e nao dizem que cortaram (spec 3.2): {sem}"


def test_nenhuma_tool_devolve_truncated_constante() -> None:
    """`"truncated": False` (ou `"algo_truncated": False`) fixo satisfaz o
    teste de cima e mente igual.

    Esta e a assercao que distingue "o campo existe" de "o campo e computado" —
    sem ela o guard de cima e satisfeito por um literal, que e a familia
    "asserir o adjacente a invariante". Cobre o sufixo tambem: uma
    `"search_terms_truncated": False` fixa mentiria exatamente igual a uma
    `"truncated": False` fixa.
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
                    and isinstance(k.value, str)
                    and (k.value == "truncated" or k.value.endswith("_truncated"))
                    and isinstance(v, ast.Constant)
                ):
                    ofensores.append(f"{nome}:{k.lineno}")
    assert ofensores == [], (
        f"`truncated`/`*_truncated` como literal nao e deteccao, e decoracao: {ofensores}"
    )


def test_o_guard_enxerga_as_duas_formas_erradas() -> None:
    """Mordida: prova que as assercoes acima distinguem codigo bom de quebrado."""
    with tempfile.TemporaryDirectory() as d:
        bom = Path(d) / "bom.py"
        bom.write_text('def f():\n    return {"rows": [], "truncated": t}\n', encoding="utf-8")
        assert "truncated" in _chaves_de_retorno(bom)

        mudo = Path(d) / "mudo.py"
        mudo.write_text('def f():\n    return {"rows": []}\n', encoding="utf-8")
        assert "truncated" not in _chaves_de_retorno(mudo)


def test_o_guard_segue_um_salto_mas_nao_absolve_por_ter_seguido() -> None:
    """Mordida do salto: tool que importa um helper `src.*` que TAMBEM nao
    declara truncamento continua acusada — seguir o import nao pode virar
    absolvicao automatica so por existir uma delegacao.

    Sem este caso, uma implementacao de `_chaves_alcancaveis` que trocasse
    "existe a chave no helper" por "existe um import de `src.*`" (sem de fato
    ler as chaves do helper) passaria os outros testes caladamente — eles so
    exercitam helper que DECLARA (via `_meta_performance.py`/
    `asset_inventory.py` reais) ou tool sem NENHUM import `src.*`. Este caso
    e o unico que prova que o salto realmente LE o destino em vez de so
    confirmar que ele existe.
    """
    with tempfile.TemporaryDirectory() as d:
        raiz = Path(d)
        pacote_helper = raiz / "src" / "mcp" / "tools"
        pacote_helper.mkdir(parents=True)
        helper_mudo = pacote_helper / "_helper_mudo.py"
        helper_mudo.write_text('def montar():\n    return {"rows": []}\n', encoding="utf-8")

        tool = raiz / "tool_delega.py"
        tool.write_text(
            "from src.mcp.tools._helper_mudo import montar\ndef f():\n    return montar()\n",
            encoding="utf-8",
        )

        # Confirma que o salto de fato encontrou e resolveu o helper — senao
        # o `assert not` abaixo passaria pelo motivo errado (resolucao vazia),
        # nao por ter lido um helper mudo de verdade.
        assert h.modulos_importados_de_src(tool, raiz=raiz) == [helper_mudo]

        assert not _declara_truncamento(_chaves_alcancaveis(tool, raiz=raiz))
