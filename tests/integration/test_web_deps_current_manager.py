"""Integration tests — src/web/deps.py `current_manager` dependency (302-gate).

tests/integration/test_web_panel_login.py já cobre "sem cookie" e "cookie
adulterado/malformado" (test_unauthenticated_dashboard_redirects_to_login,
test_invalid_cookie_redirects_to_login) — ambos batem no branch
`session is None` de current_manager. Este arquivo fecha o gap restante: um
cookie VÁLIDO (HMAC íntegro, TTL ok) cujo manager foi desativado
(is_active=False) DEPOIS de logar — current_manager consulta o DB a cada
request (não confia só no cookie) e deve negar mesmo assim.

Usa a rota real /admin/managers/{id}/toggle-active (src/web/routes.py:788) pra
desativar — mais realista que UPDATE cru: exercita o mesmo caminho que um admin
usaria em produção pra revogar acesso de um gestor.
"""

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME, sign_panel_session
from src.db import connection
from src.db.repositories import managers

_SIGNING_KEY = "x" * 32


def _cookie_for(manager_id: UUID, email: str) -> str:
    return sign_panel_session(
        manager_id=str(manager_id),
        email=email,
        signing_key=_SIGNING_KEY,
        aud="panel",
    )


@pytest.mark.integration
async def test_deactivated_manager_with_valid_cookie_redirects_to_login(
    client: AsyncClient,
) -> None:
    """Cookie válido de um manager que ERA ativo no momento do login mas foi
    desativado depois (toggle-active) -> current_manager re-consulta o DB a
    cada request e nega (302 -> /login), não confia cegamente no cookie."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        admin_id = uuid4()
        target_id = uuid4()
        await managers.create(
            conn,
            manager_id=admin_id,
            email="admin-deactivate@v4company.com",
            full_name=None,
            role="admin",
        )
        await managers.create(
            conn,
            manager_id=target_id,
            email="target-deactivate@v4company.com",
            full_name=None,
            role="gestor",
        )

    admin_cookie = _cookie_for(admin_id, "admin-deactivate@v4company.com")
    target_cookie = _cookie_for(target_id, "target-deactivate@v4company.com")

    # Confirma que o manager consegue acessar ANTES do toggle (sanity check).
    pre_toggle = await client.get(
        "/", cookies={PANEL_SESSION_COOKIE_NAME: target_cookie}, follow_redirects=False
    )
    assert pre_toggle.status_code == 200

    # Admin desativa o manager via a rota real.
    toggle_response = await client.post(
        f"/admin/managers/{target_id}/toggle-active",
        cookies={PANEL_SESSION_COOKIE_NAME: admin_cookie},
        follow_redirects=False,
    )
    assert toggle_response.status_code in (302, 303)

    # Manager desativado tenta acessar de novo com o MESMO cookie (ainda
    # criptograficamente válido) -> negado.
    post_toggle = await client.get(
        "/", cookies={PANEL_SESSION_COOKIE_NAME: target_cookie}, follow_redirects=False
    )
    assert post_toggle.status_code == 302
    assert post_toggle.headers["location"] == "/login"

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        m = await managers.get_by_id(conn, target_id)
    assert m is not None
    assert m.is_active is False


@pytest.mark.integration
async def test_manager_not_found_in_db_with_valid_cookie_redirects_to_login(
    client: AsyncClient,
) -> None:
    """Cookie válido (HMAC íntegro) apontando pra um manager_id que não existe
    mais no DB (linha deletada) -> current_manager trata get_by_id()==None
    como negado, não KeyError/500."""
    fake_manager_id = uuid4()
    cookie = _cookie_for(fake_manager_id, "ghost@v4company.com")

    response = await client.get(
        "/", cookies={PANEL_SESSION_COOKIE_NAME: cookie}, follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
