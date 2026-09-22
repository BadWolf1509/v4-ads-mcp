"""O audit de cancelamento de convite diz se o DELETE teve efeito."""

import inspect

from src.db.repositories import audit_log
from src.web.routes import _shared


def test_record_aceita_had_effect() -> None:
    assert "had_effect" in inspect.signature(audit_log.record).parameters


def test_audit_admin_repassa_had_effect() -> None:
    assert "had_effect" in inspect.signature(_shared._audit_admin).parameters


def test_a_rota_le_o_retorno_do_delete_invite() -> None:
    """Guard de forma: o retorno de `delete_invite` nao pode ser descartado.

    Vive aqui, perto do fix, alem do guard estrutural da Task 9 — este
    afirma a ROTA especifica, aquele afirma a CLASSE. Se um dia divergirem, e
    o estrutural que manda.
    """
    import ast
    from pathlib import Path

    fonte = Path(_shared.__file__).parent / "admin_invites.py"
    arv = ast.parse(fonte.read_text(encoding="utf-8"))
    descartados = [
        no.lineno
        for no in ast.walk(arv)
        if isinstance(no, ast.Expr)
        and isinstance(
            v := (no.value.value if isinstance(no.value, ast.Await) else no.value), ast.Call
        )
        and isinstance(v.func, ast.Attribute)
        and v.func.attr == "delete_invite"
    ]
    assert not descartados, (
        f"delete_invite com retorno descartado em admin_invites.py:{descartados}. "
        "Ele devolve bool justamente para dizer se deletou."
    )


def test_o_false_chega_ao_audit_e_ao_admin() -> None:
    """Assinatura certa nao prova fiacao: os tres testes acima passariam com a
    rota ignorando `cancelou`. Este le a rota e exige que o bool VIAJE."""
    import ast
    from pathlib import Path

    fonte = Path(_shared.__file__).parent / "admin_invites.py"
    arv = ast.parse(fonte.read_text(encoding="utf-8"))

    nomes_ligados = {
        alvo.id
        for no in ast.walk(arv)
        if isinstance(no, ast.Assign)
        and isinstance(
            v := (no.value.value if isinstance(no.value, ast.Await) else no.value), ast.Call
        )
        and isinstance(v.func, ast.Attribute)
        and v.func.attr == "delete_invite"
        for alvo in no.targets
        if isinstance(alvo, ast.Name)
    }
    assert nomes_ligados, "o retorno de delete_invite nao foi ligado a nome nenhum"

    kwargs_had_effect = [
        kw.value
        for no in ast.walk(arv)
        if isinstance(no, ast.Call)
        for kw in no.keywords
        if kw.arg == "had_effect"
    ]
    assert any(isinstance(v, ast.Name) and v.id in nomes_ligados for v in kwargs_had_effect), (
        "had_effect nao recebe o retorno de delete_invite — o audit voltou a afirmar sem medir"
    )

    usado_em_condicao = any(
        isinstance(no, ast.If)
        and any(isinstance(x, ast.Name) and x.id in nomes_ligados for x in ast.walk(no.test))
        for no in ast.walk(arv)
    )
    assert usado_em_condicao, "nada avisa o admin quando o cancelamento nao teve efeito"
