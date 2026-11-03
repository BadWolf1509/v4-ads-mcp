"""Páginas públicas do painel: help, legal/*, data-deletion-status e access-denied.

Nenhuma exige gestor logado. Saíram de `sessions.py` na varredura de 11/2026
(Task F6); paths, nomes (`data_deletion_status` é alvo de `url_for` em
`src/auth/meta_data_deletion.py`) e comportamento seguem iguais.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.config import get_settings
from src.web.deps import CurrentUser, optional_current_manager
from src.web.routes._shared import templates

router = APIRouter(tags=["web"])


@router.get("/help", response_class=HTMLResponse)
async def help_page(
    request: Request,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Onboarding consolidated. Accessible logged-in or out (login link is included)."""
    # mcp_url injetado no contexto (não hardcoded no template) pra os snippets de
    # conexão nunca driftarem da URL real do serviço — mesmo padrão do /sessions.
    mcp_url = f"{get_settings().public_base_url}/mcp"
    return templates.TemplateResponse(
        request, "help.html", {"current_user": user, "mcp_url": mcp_url}
    )


@router.get("/legal/privacy", response_class=HTMLResponse)
async def legal_privacy(
    request: Request,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Public Privacy Policy. Required by Meta Marketing API App Settings."""
    return templates.TemplateResponse(request, "legal/privacy.html", {"current_user": user})


@router.get("/legal/terms", response_class=HTMLResponse)
async def legal_terms(
    request: Request,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Public Terms of Service. Required by Meta Marketing API App Settings."""
    return templates.TemplateResponse(request, "legal/terms.html", {"current_user": user})


@router.get(
    "/legal/data-deletion-status/{code}", response_class=HTMLResponse, name="data_deletion_status"
)
async def data_deletion_status(
    request: Request,
    code: UUID,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Public data deletion confirmation status page. Meta App Review requirement."""
    return templates.TemplateResponse(
        request,
        "legal/data_deletion_status.html",
        {"current_user": user, "confirmation_code": str(code)},
    )


@router.get("/access-denied", response_class=HTMLResponse, response_model=None)
async def access_denied(
    request: Request,
    reason: str = "not_invited",
) -> HTMLResponse:
    """Q8 invite-only landing page. No auth required.

    Reads a transient `v4_attempted_email` cookie set by the OAuth callback
    before redirect, so the page can show which email was rejected. Cookie is
    cleared on read so it doesn't persist or leak across logins.

    Os params `email`, `detail` e `missing` (e os ramos `meta_*` do template)
    sairam com o OAuth pessoal da Meta em 11/2026: só aquele callback os
    preenchia.
    """
    attempted_email = request.cookies.get("v4_attempted_email")
    response = templates.TemplateResponse(
        request,
        "access_denied.html",
        {
            "current_user": None,
            "reason": reason,
            "attempted_email": attempted_email,
        },
    )
    response.delete_cookie("v4_attempted_email", path="/access-denied")
    return response
