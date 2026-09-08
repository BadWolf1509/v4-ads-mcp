"""F56/F128: as duas tools que leem `keyword_view` avisam a MESMA coisa.

`get_keyword_performance` e `get_performance_breakdown(level="keyword")` leem a
mesma tabela do Google, e essa tabela mistura criterio POSITIVO com NEGATIVO. As
duas devolvem o campo `negative` por linha; so uma avisava. Quem chegasse pela
tool nova — que a descricao das nove irmas manda preferir — leria a lista como se
fosse de keywords ativas e pausaria um criterio negativo achando que era uma
keyword cara.

Por que par nomeado e nao varredura de "toda tool que emite `negative`": a
terceira tool que alcanca esse campo e `update_keyword_status`, e ela **trata**
o caso em codigo (`validate_keyword_criterion_types` separa o lote em positivas
e negativas antes de mutar) em vez de avisar. Uma varredura precisaria de uma
excecao para ela, e lista de excecao e o modo de falha que este repo ja
catalogou. O que se afirma aqui e mais estreito e mais verdadeiro: **gemeas que
leem a mesma tabela devolvem o mesmo aviso** — a invariante do F128.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from src.mcp.tools._registry import get_tool, import_all_tools
from tests.unit import _guard_harness as h

import_all_tools()

# As duas pontas do par. `keyword_view` e a tabela; o que as une nao e o nome nem
# o bucket, e a fonte de dados.
_GEMEAS = ("get_keyword_performance", "get_performance_breakdown")


def _cita_keyword_view(no: ast.AST) -> bool:
    return any(
        isinstance(sub, ast.Constant) and isinstance(sub.value, str) and "keyword_view" in sub.value
        for sub in ast.walk(no)
    )


def _le_keyword_view(nome: str, *, profundidade: int = 3) -> bool:
    """A tool alcanca um builder que consulta `FROM keyword_view`.

    Transitivo, com teto de profundidade — e o teto tem motivo medido, nao
    cautela: `get_keyword_performance` importa `keyword_performance_query`
    direto (1 salto), mas `get_performance_breakdown` passa por
    `build_performance_breakdown_query`, que DESPACHA por `level` para o mesmo
    builder (2 saltos). Uma sonda de um salto so responderia `False` para a
    segunda gemea — e a assercao de premissa ficaria vermelha por limitacao da
    SONDA, nao por o par ter mudado, que e a pior forma de guard vermelho.

    O harness continua com um salto de proposito (o guard do truncamento quer
    delegacao direta); aqui a pergunta e outra — "esta tool, em algum lugar da
    cadeia, le esta tabela?" — e ela e transitiva por natureza.
    """
    tool = get_tool(nome)
    assert tool is not None, f"tool `{nome}` saiu do registry"
    fronteira = [Path(sys.modules[tool.handler.__module__].__file__ or "")]
    vistos: set[Path] = set()
    for _ in range(profundidade):
        proxima: list[Path] = []
        for arquivo in fronteira:
            if arquivo in vistos:
                continue
            vistos.add(arquivo)
            if _cita_keyword_view(h.arvore(arquivo)):
                return True
            proxima.extend(destino for destino, _ in h.funcoes_chamadas_de_src(arquivo))
        fronteira = proxima
    return False


def _avisa_do_negativo(nome: str) -> bool:
    tool = get_tool(nome)
    assert tool is not None
    d = (tool.description or "").lower()
    return "negative" in d and ("f56" in d or "negativa" in d)


@pytest.mark.parametrize("nome", _GEMEAS)
def test_as_duas_gemeas_avisam_da_mistura_positiva_com_negativa(nome: str) -> None:
    """Contra o codigo pre-fix, `get_performance_breakdown` falha aqui.

    A mudanca de producao que deixa este teste vermelho: apagar o trecho "F56"
    da descricao de qualquer uma das duas — que e exatamente o que aconteceria
    numa reescrita de descricao que nao soubesse por que aquele paragrafo
    existe.
    """
    assert _avisa_do_negativo(nome), (
        f"`{nome}` le `keyword_view`, que mistura criterio positivo e negativo, "
        "e a descricao nao avisa. A gemea avisa — e ler a mesma tabela com "
        "avisos diferentes e o F128."
    )


@pytest.mark.parametrize("nome", _GEMEAS)
def test_a_premissa_do_par_continua_verdadeira(nome: str) -> None:
    """Contraprova: sem ela, o par vira dois nomes escritos a mao.

    Se uma das duas deixar de ler `keyword_view` (mudou de recurso, foi
    tombstonada na Fase 2B), este teste fica vermelho e obriga a revisar o par
    em vez de deixar uma assercao verdadeira por motivo errado — a familia
    "guard verdadeiro independente da implementacao".
    """
    assert _le_keyword_view(nome), (
        f"`{nome}` nao le mais `keyword_view` — o par do F56 mudou, revise "
        "este arquivo em vez de manter a assercao por inercia."
    )
