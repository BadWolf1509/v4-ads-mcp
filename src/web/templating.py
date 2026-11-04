"""Instância única de `Jinja2Templates` do painel, com filtros e globals.

Saiu de `src/web/routes/_shared.py` (F7) para que quem renderiza template sem
ser rota do painel — `src/auth/oauth.py` — não importe o pacote de rotas.
`_shared` reexporta `templates` e os filtros para os módulos de rota.
"""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from src.meta_ads.labels import META_ACCOUNT_STATUS_LABELS
from src.web.static_files import asset_version

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def meta_status_label(status: int | None) -> str:
    """Jinja filter: resolve Meta account_status int to PT-BR label."""
    return META_ACCOUNT_STATUS_LABELS.get(status or 0, "DESCONHECIDO")


templates.env.filters["meta_status_label"] = meta_status_label

_BRASILIA = ZoneInfo("America/Sao_Paulo")


def hora_brasilia(valor: datetime | None, formato: str = "%d/%m %H:%M") -> str:
    """Jinja filter: datetime (UTC no banco) -> texto no horario de Brasilia.

    `strftime` direto no template imprimia UTC como se fosse hora local (3h
    adiantado). Naive e tratado como UTC, que e o que o banco grava.
    """
    if valor is None:
        return "—"
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)
    return valor.astimezone(_BRASILIA).strftime(formato)


templates.env.filters["hora_brasilia"] = hora_brasilia

# Cache-busting dos estaticos: muda a cada revisao do Cloud Run, o que torna
# seguro o Cache-Control imutavel de CachedStaticFiles.
templates.env.globals["asset_version"] = asset_version()
