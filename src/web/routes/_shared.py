"""Helpers e infraestrutura compartilhados pelos módulos de rota do painel.

Movido de `routes.py` no split da PR 5 (Task 2): tudo que mais de um módulo de
rota consome — `_require_admin`, o helper de flash message, `_audit_admin`, o
fragmento de toggle de acesso, e a instância compartilhada de `Jinja2Templates`
(com os filtros/globals do Jinja registrados nela).
"""

import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

import structlog
from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates

from src.db.repositories import audit_log
from src.meta_ads.labels import META_ACCOUNT_STATUS_LABELS
from src.web.deps import CurrentUser
from src.web.static_files import asset_version

log = structlog.get_logger(__name__)


def _require_admin(user: CurrentUser) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


# Teto de `days` nos dois exports CSV do audit (item 4 do relatorio de DB da
# varredura de 21/09). O export e trilha de compliance, e um ano cobre a
# historia inteira do `audit_log`. O seletor do painel vai ate 90 dias, mas
# quem limita a rota e a validacao, nao o seletor: a URL aceita o que vier.
_TETO_DIAS_EXPORT_AUDIT = 365


_ADMIN_FLASH_ERRORS: dict[str, str] = {
    "bad_domain": "Só emails @v4company.com podem ser convidados.",
    "exists": "Esse email já está cadastrado (convite pendente ou conta existente). Nada foi criado.",
    "same_manager": "Gestor de origem e destino são o mesmo — nada foi copiado.",
    "conta_inativa": (
        "Esta conta ainda está fora da parceria — restaurar agora não devolveria "
        "acesso nenhum (o gate exige conta ativa). Espere a reconciliação "
        "reativá-la; a linha volta com o botão."
    ),
    # Codigo PROPRIO — nao reaproveita "conta_inativa": aquela mensagem fala em
    # "parceria" (vocabulario Meta); o lado Google saiu/voltou do MCC.
    "conta_inativa_google": (
        "Esta conta ainda está fora do MCC — restaurar agora não devolveria "
        "acesso nenhum (o gate exige conta ativa). Espere a reconciliação "
        "reativá-la; a linha volta com o botão."
    ),
    # F179: admin_invites_cancel mede o retorno do DELETE antes de audita-lo —
    # convidado que logou entre o SELECT e o DELETE ja nao tem status='invited',
    # e o cancelamento nao teve efeito nenhum. Mapa fixo, nao eco do param.
    "invite_ja_aceito": "Esse convite já foi aceito — nada foi cancelado.",
}

# Mapa fixo pro `ok=<codigo>` da reconciliacao Google — distinto do `ok=1` usado
# nas demais paginas admin porque a rota de restaurar precisa de MENSAGEM
# PROPRIA (nao so "sucesso genérico"). Mesma regra: nunca ecoar o param.
_GOOGLE_ACCOUNTS_FLASH_OK: dict[str, str] = {
    "restored": "Acesso restaurado — os grants revogados pela saída do MCC foram reconcedidos.",
}

# Mapa fixo pro `ok=<codigo>` da reconciliacao Meta — distinto do `ok=1` usado
# nas demais paginas admin porque a rota de restaurar precisa de MENSAGEM
# PROPRIA (nao so "sucesso genérico"). Mesma regra: nunca ecoar o param.
_META_ACCOUNTS_FLASH_OK: dict[str, str] = {
    "restored": "Acesso restaurado — os grants revogados pela saída da parceria foram reconcedidos.",
}


def _admin_flash(
    request: Request,
    *,
    ok_message: str | None = None,
    ok_codes: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Flash message via query param. Mapa fixo — NUNCA ecoar o valor do param (XSS)."""
    code = request.query_params.get("error")
    if code:
        message = _ADMIN_FLASH_ERRORS.get(code)
        return {"kind": "error", "message": message} if message else None
    ok = request.query_params.get("ok")
    if ok_codes and ok:
        message = ok_codes.get(ok)
        return {"kind": "success", "message": message} if message else None
    if ok_message and ok == "1":
        return {"kind": "success", "message": ok_message}
    return None


async def _audit_admin(
    conn: Any,
    *,
    admin: CurrentUser,
    operation: str,
    customer_id: str | None = None,
    platform: Literal["google", "meta"] = "google",
    had_effect: bool | None = None,
    **summary: Any,
) -> None:
    """Record an audit_log row for a sensitive admin-panel mutation.

    Panel actions (access matrix, roles, activation, invites) have no MCP
    session, so session_id is always None; manager_id is the authenticated
    admin performing the action. summary becomes params_summary (target of
    the action — never tokens/secrets).

    had_effect: true = a escrita afetou linha; false = passou sem efeito; None
        nos caminhos que nao medem. Repassado direto para audit_log.record —
        mesma semantica, ver o docstring de la (F179).
    """
    await audit_log.record(
        conn,
        manager_id=admin.id,
        session_id=None,
        customer_id=customer_id,
        action_type="mutate",
        operation=operation,
        params_summary=summary or None,
        platform=platform,
        had_effect=had_effect,
    )


def _toggle_checkbox_fragment(
    *,
    post_url: str,
    manager_id: str,
    account_id: str,
    account_field: str,
    checked: bool,
) -> str:
    """Checkbox de reposição servido após o toggle de acesso.

    O comportamento (toast, revert-on-fail) vive num listener delegado em
    v4-panel.js, acionado por `data-v4-access-toggle` — era o F74.

    O NOME ACESSÍVEL segue a mesma regra. Com `aria-label` de texto, a rota
    tinha que reproduzir o que o template escreve, e não reproduzia: todo
    checkbox virava "Alternar acesso" depois do primeiro toggle — e nas views
    por gestor o `aria-label` ainda vencia o `<label>` que embrulha, então o
    texto visível e o nome anunciado passavam a discordar. Agora o nome vem
    por `aria-labelledby`, apontando pro cabeçalho do gestor e pro da conta,
    que ficam FORA do nó trocado. O valor é função pura dos dois ids que já
    chegam no form, então template e fragmento não têm como divergir.
    """
    state = "checked " if checked else ""
    vals = {"manager_id": manager_id, account_field: account_id}
    hx_vals = html.escape(json.dumps(vals), quote=True)
    rotulo = html.escape(f"v4-mgr-{manager_id} v4-acc-{account_id}", quote=True)
    return (
        f'<input type="checkbox" {state}hx-post="{post_url}" '
        f'hx-vals=\'{hx_vals}\' hx-trigger="change" hx-swap="outerHTML" '
        f'data-v4-access-toggle aria-labelledby="{rotulo}">'
    )


# Um nivel a mais que no routes.py original: este arquivo mora em
# src/web/routes/_shared.py, entao precisa subir DOIS parents (nao um) pra
# chegar em src/web/templates.
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


class MetaExpirySignals(NamedTuple):
    """Sinais de expiração do OAuth pessoal Meta pro painel admin."""

    expired: bool
    expiring_soon: bool
    days_until: int | None
    days_since: int | None


def meta_expiry_signals(
    token_expires_at: datetime | None, *, agora: datetime | None = None
) -> MetaExpirySignals:
    """Traduz a data de expiração nos sinais que o template consome.

    Separado da rota pra ser testável sem DB. O cálculo antigo era
    `max(0, delta.days)`, que achatava vencido em 0 e fazia o painel dizer
    "expira em <data passada> (0 dias)".

    Os dias são contados sempre na direção positiva: `timedelta` negativo
    arredonda pra baixo (`-15,4 dias` vira `.days == -16`), então medir
    `agora - expiração` evita o off-by-one no "há N dias".
    """
    if token_expires_at is None:
        return MetaExpirySignals(False, False, None, None)

    agora = agora or datetime.now(UTC)
    if token_expires_at <= agora:
        return MetaExpirySignals(True, False, None, (agora - token_expires_at).days)

    dias = (token_expires_at - agora).days
    return MetaExpirySignals(False, dias < 7, dias, None)


def meta_status_label(status: int | None) -> str:
    """Jinja filter: resolve Meta account_status int to PT-BR label."""
    return META_ACCOUNT_STATUS_LABELS.get(status or 0, "DESCONHECIDO")


templates.env.filters["meta_status_label"] = meta_status_label

# Cache-busting dos estaticos: muda a cada revisao do Cloud Run, o que torna
# seguro o Cache-Control imutavel de CachedStaticFiles.
templates.env.globals["asset_version"] = asset_version()
