"""A politica de blast radius tem que bater com o caminho que cada tool toma.

`blast_radius.classify` se descreve como quem "decide auto-apply vs
require-confirmation". Na pratica so 9 das 26 tools de mutacao leem `.level`;
as outras 17 computam o veredito e usam apenas `.reason` como texto, com o
caminho (auto-aplicar ou emitir token) fixo no codigo.

Nao ha divergencia hoje — este teste existe pra que continue assim. Apertar a
politica no modulo (por exemplo passar `remove_negative_keywords` a CONFIRM,
defensavel ja que remover negativa ALARGA o targeting) nao mudaria nada nas 17,
e o desalinhamento seria silencioso: a tool seguiria auto-aplicando enquanto o
modulo diria o contrario.

Reescrever as 17 pra consultarem `.level` seria a outra saida. Nao vale o
tamanho: o risco nao e a tool errar, e a politica e a tool DIVERGIREM — e isso
um teste pega. A lista de tools e DERIVADA do source, entao uma tool nova entra
sozinha.
"""

import ast
from pathlib import Path

import pytest

from src.governance.blast_radius import RiskLevel, classify
from tests.unit import _guard_harness as h

_TOOLS = Path(__file__).resolve().parents[2] / "src" / "mcp" / "tools"

_EXECUTORES = {
    "run_mutation",
    "run_conversion_upload",
    "run_recommendation_action",
    "run_offline_user_data_job",
}

# Varia o bastante pra atravessar todos os limiares do modulo (1, 5, 20).
_CONTAGENS = (0, 1, 5, 20, 100, 500)


def _operacao_classificada(arvore: ast.AST) -> str | None:
    """String literal passada como `operation=` pro classify."""
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Name)):
            continue
        if no.func.id != "classify":
            continue
        for kw in no.keywords:
            if kw.arg == "operation" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
    return None


def _tools_com_caminho_fixo() -> list[tuple[str, str, RiskLevel]]:
    """(arquivo, operation, nivel esperado) das tools que NAO leem `.level`."""
    achados: list[tuple[str, str, RiskLevel]] = []
    for p in h.fontes_py(_TOOLS):
        if p.name.startswith("_"):
            continue
        arvore = ast.parse(p.read_text(encoding="utf-8"))
        operacao = _operacao_classificada(arvore)
        if operacao is None:
            continue
        le_level = any(
            isinstance(no, ast.Attribute) and no.attr == "level" for no in ast.walk(arvore)
        )
        if le_level:
            continue  # honra a politica em runtime — nada a garantir aqui
        emite_token = h.chama(arvore, "create_pending", arv=arvore)
        aplica_direto = any(h.chama(arvore, e, arv=arvore) for e in _EXECUTORES)
        if emite_token and not aplica_direto:
            achados.append((p.name, operacao, RiskLevel.CONFIRM))
        elif aplica_direto and not emite_token:
            achados.append((p.name, operacao, RiskLevel.AUTO))
        else:
            pytest.fail(
                f"{p.name}: nao le `.level` e o caminho nao e obvio no source "
                f"(create_pending={emite_token}, executor={aplica_direto}). "
                "Ou faca a tool consultar risk.level, ou deixe um caminho unico."
            )
    return achados


_CASOS = _tools_com_caminho_fixo()


def test_derivou_as_tools_de_caminho_fixo() -> None:
    """Se o scanner parar de casar, os testes abaixo passariam vazios."""
    assert len(_CASOS) >= 15, f"esperado ~17 tools de caminho fixo, achei {len(_CASOS)}"


@pytest.mark.parametrize(("arquivo", "operacao", "esperado"), _CASOS)
def test_politica_bate_com_o_caminho_fixo_da_tool(
    arquivo: str, operacao: str, esperado: RiskLevel
) -> None:
    """Pra toda contagem plausivel, a politica concorda com o que a tool faz."""
    for n in _CONTAGENS:
        veredito = classify(operation=operacao, params={"target_count": n})
        assert veredito.level is esperado, (
            f"{arquivo} sempre {esperado.value}, mas classify({operacao!r}, "
            f"target_count={n}) diz {veredito.level.value} — a tool nao le "
            "`.level`, entao essa divergencia seria silenciosa em producao"
        )
