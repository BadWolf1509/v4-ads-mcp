"""StaticFiles com Cache-Control longo + identificador de versao dos assets.

Ate 2026-08-11 os estaticos saiam sem Cache-Control (so etag), entao toda
navegacao pagava uma revalidacao condicional por arquivo. Um max-age longo so
e seguro com cache-busting: as URLs no _base.html carregam ?v=<asset_version>,
e o Cloud Run troca K_REVISION a cada deploy, entao o browser busca uma URL
nova em vez de servir CSS velho.
"""

from __future__ import annotations

import os
from typing import Any

from starlette.responses import Response
from starlette.staticfiles import StaticFiles

_ONE_YEAR = 31_536_000


def asset_version() -> str:
    """Identificador que muda a cada deploy. Cloud Run injeta K_REVISION."""
    return os.getenv("K_REVISION") or "dev"


class CachedStaticFiles(StaticFiles):
    """StaticFiles que marca as respostas como imutaveis.

    Seguro porque as referencias sao versionadas por querystring — ver
    asset_version(). Sem isso, um deploy que mude o CSS ficaria invisivel
    pra quem ja tem o arquivo em cache.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = f"public, max-age={_ONE_YEAR}, immutable"
        return response
