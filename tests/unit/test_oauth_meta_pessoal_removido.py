"""O OAuth pessoal da Meta foi removido em 11/2026; o callback de exclusão fica.

A execução Meta roda só com o token do system user (Modelo B). As três rotas do
fluxo pessoal (`start`, `callback`, `revoke`) eram código dormante que ainda
manuseava o `meta_app_secret` e gravava token de gestor — superfície sem uso.
O `POST /oauth/meta/data-deletion-callback` continua: é exigência do App Review
da Meta e não depende do fluxo pessoal (mora em `src/auth/meta_data_deletion.py`).

Varre a tabela de rotas da APP inteira (`create_app`), não um router: as rotas
`/oauth/meta/*` nunca estiveram em `src.web.routes.router` (nem no snapshot de
`tabela_de_rotas.json`), então só a app montada diz o que é servido.
"""

from __future__ import annotations

from tests.unit.test_tabela_de_rotas_e_estavel import _flatten

_REMOVIDAS = {"/oauth/meta/start", "/oauth/meta/callback", "/oauth/meta/revoke"}
_MANTIDA = "/oauth/meta/data-deletion-callback"


def _caminhos_servidos() -> set[str]:
    # Lazy import: src/app.py cria a app no nível de módulo (ver
    # test_rotas_de_mutacao_tem_guard.py).
    from src.app import create_app

    app = create_app(skip_db_init=True)
    return {getattr(r, "path", "") for r in _flatten(app.routes)}


def test_oauth_meta_pessoal_nao_existe() -> None:
    caminhos = _caminhos_servidos()
    assert _MANTIDA in caminhos, (
        f"{_MANTIDA} sumiu da app — o callback de exclusão de dados é exigência "
        "do App Review da Meta e fica mesmo sem o OAuth pessoal."
    )
    sobreviventes = sorted(_REMOVIDAS & caminhos)
    assert not sobreviventes, (
        f"rotas do OAuth pessoal da Meta voltaram: {sobreviventes}. O fluxo foi "
        "removido em 11/2026 (execução só com o token do system user)."
    )
    # Nenhuma outra rota nova sob /oauth/meta sem revisão: o prefixo só serve o
    # callback de exclusão.
    sob_prefixo = sorted(c for c in caminhos if c.startswith("/oauth/meta"))
    assert sob_prefixo == [_MANTIDA], sob_prefixo


def test_modulo_do_oauth_pessoal_nao_existe() -> None:
    import importlib.util

    assert importlib.util.find_spec("src.auth.meta_oauth") is None
    assert importlib.util.find_spec("src.db.repositories.meta_oauth_connections") is None
