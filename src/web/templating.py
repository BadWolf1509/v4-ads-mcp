"""Instância única de `Jinja2Templates` do painel, com filtros e globals.

Saiu de `src/web/routes/_shared.py` (F7) para que quem renderiza template sem
ser rota do painel — `src/auth/oauth.py` — não importe o pacote de rotas.
`_shared` reexporta `templates` e os filtros para os módulos de rota.
"""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from src.meta_ads.labels import META_ACCOUNT_STATUS_LABELS
from src.web.numeros import FUSO_PAINEL
from src.web.static_files import asset_version

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def meta_status_label(status: int | None) -> str:
    """Jinja filter: resolve Meta account_status int to PT-BR label."""
    return META_ACCOUNT_STATUS_LABELS.get(status or 0, "DESCONHECIDO")


templates.env.filters["meta_status_label"] = meta_status_label


def hora_brasilia(valor: datetime | None, formato: str = "%d/%m %H:%M") -> str:
    """Jinja filter: datetime (UTC no banco) -> texto no horario de Brasilia.

    `strftime` direto no template imprimia UTC como se fosse hora local (3h
    adiantado). Naive e tratado como UTC, que e o que o banco grava.
    """
    if valor is None:
        return "—"
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)
    return valor.astimezone(FUSO_PAINEL).strftime(formato)


templates.env.filters["hora_brasilia"] = hora_brasilia
# Cache-busting dos estaticos: muda a cada revisao do Cloud Run, o que torna
# seguro o Cache-Control imutavel de CachedStaticFiles.
templates.env.globals["asset_version"] = asset_version()
# Nome do produto num lugar so (era "V4 Ads MCP" ate o desligamento da V4, 25/11/2026).
NOME_PRODUTO = "Fluxo Certo Ads"
templates.env.globals["nome_produto"] = NOME_PRODUTO
# Operador e contato das paginas legais (rascunho de 25/11; texto juridico final e do operador).
NOME_OPERADOR = "Wellington Ribeiro"
CONTATO_OPERADOR = "wellington.ribeiro.eng@gmail.com"
templates.env.globals["nome_operador"] = NOME_OPERADOR
templates.env.globals["contato_operador"] = CONTATO_OPERADOR
