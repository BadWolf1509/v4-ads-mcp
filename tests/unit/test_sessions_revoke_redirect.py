"""POST-redirect-GET no revoke sem HTMX (sem DB — inspeciona o codigo da rota).

Rodar o handler exigiria pool + sessao real; o que importa aqui e a FORMA da
resposta no ramo nao-HTMX, e ela e estatica no source.
"""

import ast
from pathlib import Path

_ROTAS = Path(__file__).resolve().parents[2] / "src" / "web" / "routes.py"


def _funcao(nome: str) -> ast.AsyncFunctionDef:
    arvore = ast.parse(_ROTAS.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.AsyncFunctionDef) and no.name == nome:
            return no
    raise AssertionError(f"{nome} nao encontrada em routes.py")


def test_revoke_sem_htmx_redireciona_em_vez_de_renderizar() -> None:
    """Renderizar a lista com 200 num POST faz o refresh re-executar a acao."""
    funcao = _funcao("sessions_revoke")
    renders = [
        no
        for no in ast.walk(funcao)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and no.func.attr == "TemplateResponse"
    ]
    assert len(renders) == 1, (
        "so o fragmento da lista (caminho HTMX) deve renderizar template; "
        f"achei {len(renders)} TemplateResponse"
    )
    redirects = [
        no
        for no in ast.walk(funcao)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Name)
        and no.func.id == "RedirectResponse"
    ]
    assert redirects, "o ramo nao-HTMX precisa de RedirectResponse"
    codigos = {
        kw.value.value
        for chamada in redirects
        for kw in chamada.keywords
        if kw.arg == "status_code" and isinstance(kw.value, ast.Constant)
    }
    assert codigos == {303}, f"POST-redirect-GET exige 303, achei {codigos}"
