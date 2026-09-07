"""Guard: nenhum tool monta o envelope `applied` a mao.

`applied_envelope` existe desde a consolidacao dos 22 tools (o mesmo commit que
tirou o literal `expires_in_minutes: 10` de 22 lugares). Cinco tools nunca
foram convertidos e seguiam montando o dict literal:

    add_negative_keywords, add_negatives_from_search_terms, apply_change,
    dismiss_recommendation, remove_negative_keywords

O preco nao e' cosmetico. `add_negatives_from_search_terms` simplesmente NAO
devolvia `blast_summary` — o campo que diz ao gestor o que a chamada fez, e que
o helper garante por construcao. Ninguem notou porque nada afirmava que ele
deveria estar la: cada envelope a mao e' um contrato proprio, e o que falta num
deles nao falta em lugar nenhum onde alguem esteja olhando.

Por AST e nao por grep: a busca por nome de tool erra nos dois sentidos (tool
que MENCIONA o helper num comentario, tool nova que ninguem lembrou de
listar). O que o guard pergunta e' estrutural — existe, num arquivo de tool, um
dict literal cuja chave "status" e' a constante "applied" ou "submitted"?
"""

from __future__ import annotations

import ast

from tests.unit import _guard_harness as h

TOOLS = h.SRC / "mcp" / "tools"

# O helper. Ele PRECISA conter o literal — e o unico lugar que deve.
DONO_DO_ENVELOPE = "_mutate_common.py"

_STATUS_DE_SUCESSO = {"applied", "submitted"}


def _envelopes_a_mao(arv: ast.Module) -> list[tuple[int, str]]:
    """(linha, status) de cada dict literal com `"status": "applied"|"submitted"`.

    So dict LITERAL com chave e valor constantes: e' a forma que o helper
    substitui. Um dict montado em variavel e depois mutado (`d["status"] = ...`)
    escapa daqui — limitacao estrutural assumida, nao coberta e nao fingida.
    """
    achados: list[tuple[int, str]] = []
    for no in ast.walk(arv):
        if not isinstance(no, ast.Dict):
            continue
        for chave, valor in zip(no.keys, no.values, strict=True):
            if (
                isinstance(chave, ast.Constant)
                and chave.value == "status"
                and isinstance(valor, ast.Constant)
                and valor.value in _STATUS_DE_SUCESSO
            ):
                achados.append((no.lineno, str(valor.value)))
    return achados


def test_nenhum_tool_monta_o_envelope_applied_a_mao() -> None:
    """Todo caminho de sucesso de mutate passa por `applied_envelope`.

    O helper garante `status`, `operation`, `customer_id`, `blast_summary`,
    `applied_count` e `provider_request_id` em TODA resposta de sucesso. Cada
    dict literal ao lado dele e' um contrato paralelo que pode perder um campo
    sem nenhum teste ficar vermelho — foi o que aconteceu com o
    `blast_summary` do `add_negatives_from_search_terms`.
    """
    ofensores: list[str] = []
    arquivos = 0
    for p in h.fontes_py(TOOLS):
        if p.name == DONO_DO_ENVELOPE:
            continue
        arquivos += 1
        ofensores.extend(
            f"{h.rel(p)}:{linha} (status={status!r})"
            for linha, status in _envelopes_a_mao(h.arvore(p))
        )

    assert arquivos, (
        "o scanner nao viu nenhum arquivo de tool — guard que varre zero arquivos "
        "passa por vacuidade. Confira o caminho (absoluto, derivado de __file__)."
    )
    assert not ofensores, (
        f"envelope de sucesso montado a mao: {ofensores}. Use `applied_envelope` de "
        "src/mcp/tools/_mutate_common.py — ele garante blast_summary, "
        "applied_count e provider_request_id em toda resposta de sucesso, e cada "
        "dict literal ao lado dele e' um contrato paralelo que perde campo em "
        "silencio."
    )


def test_o_helper_ainda_e_o_dono_do_literal() -> None:
    """Controle: o guard acima seria vacuo se o proprio helper tivesse mudado.

    Se `_mutate_common.py` deixasse de conter o literal `"status": "applied"`
    (renomeado, movido, reescrito), o teste de cima passaria verde varrendo um
    codebase onde o envelope nao existe mais em lugar nenhum.
    """
    arv = h.arvore(TOOLS / DONO_DO_ENVELOPE)
    assert [s for _, s in _envelopes_a_mao(arv) if s == "applied"], (
        f"{DONO_DO_ENVELOPE} nao contem mais o envelope `applied` — o guard de "
        "cima ficou sem referencia e passaria por vacuidade."
    )


def test_applied_envelope_garante_o_blast_summary() -> None:
    """A propriedade que o helper existe pra garantir, afirmada diretamente.

    Sem isto o guard estrutural diria so "todo mundo usa o helper" — e um
    helper que parasse de emitir `blast_summary` deixaria as duas coisas
    verdes ao mesmo tempo.
    """
    from src.mcp.tools._mutate_common import applied_envelope

    env = applied_envelope(
        "op_qualquer",
        "1234567890",
        "Resumo do que foi feito.",
        applied_count=2,
        provider_request_id="req-1",
    )
    assert env["status"] == "applied"
    assert env["blast_summary"] == "Resumo do que foi feito."
    assert env["operation"] == "op_qualquer"
    assert env["customer_id"] == "1234567890"
    assert env["applied_count"] == 2
    assert env["provider_request_id"] == "req-1"


def test_auto_applied_reason_so_aparece_quando_ha_um() -> None:
    """O caminho de CONFIRMACAO nao tem razao de auto-aplicacao.

    `apply_change` aplica o que o gestor confirmou; inventar um
    `auto_applied_reason` ali seria afirmar que a tool decidiu sozinha. O
    campo e' opcional pelo mesmo motivo que `confirmation_reason` ja era
    opcional no `preview_envelope`.
    """
    from src.mcp.tools._mutate_common import applied_envelope

    sem = applied_envelope(
        "apply_change", "1234567890", "resumo", applied_count=1, provider_request_id="r"
    )
    assert "auto_applied_reason" not in sem

    com = applied_envelope(
        "update_keyword_status",
        "1234567890",
        "resumo",
        applied_count=1,
        provider_request_id="r",
        auto_applied_reason="baixo risco",
    )
    assert com["auto_applied_reason"] == "baixo risco"
