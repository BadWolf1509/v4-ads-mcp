"""Criativos Meta e previa de anuncio.

Leitura pura. `/{act}/generatepreviews` aceita criativo de OUTRA conta (sonda de
2026-10-31) e `filtering` por id nao e suportado em `adcreatives`; por isso a previa so sai
depois de provar, fail-closed, que o ID pertence a conta: percorre `/{act}/ads` (para
`ad_id`) ou `/{act}/adcreatives` (para `creative_id`). Sem achar, recusa sem chamar
`generatepreviews`. Da previa so o `src` do iframe volta, nunca o HTML.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from src.meta_ads.colecao import ContextoMeta
from src.meta_ads.reports import run_meta_graph_get

_TAMANHO_MAX_PAGINA = 100
_POSSE_LIMIT = 200
_POSSE_MAX_PAGES = 5

# Campos medidos na sonda de 2026-10-31. A edge ignora campo desconhecido em silencio.
_CAMPOS = (
    "id,name,status,object_type,title,body,image_url,thumbnail_url,call_to_action_type,"
    "object_story_id,effective_object_story_id,instagram_permalink_url"
)
_PASSA = tuple(_CAMPOS.split(","))

FORMATOS = [
    "MOBILE_FEED_STANDARD",
    "INSTAGRAM_STANDARD",
    "INSTAGRAM_STORY",
    "INSTAGRAM_REELS",
    "FACEBOOK_STORY_MOBILE",
    "FACEBOOK_REELS_MOBILE",
]

MSG_GRANDE = (
    "pode ser uma conta grande: a busca olha até {n} registros e o ID não apareceu. "
    "Confirme que o ID é desta conta."
)


class PosseNaoProvada(Exception):  # noqa: N818
    """O ID nao foi achado na conta (ou a leitura de posse falhou): recusa."""


def _pagina_e_max(limit: int) -> tuple[int, int]:
    pagina = min(limit + 1, _TAMANHO_MAX_PAGINA)
    return pagina, -(-(limit + 1) // pagina)


def parse_criativo(linha: dict[str, Any], ads_vinculados: list[str] | None) -> dict[str, Any]:
    saida: dict[str, Any] = {campo: linha.get(campo) for campo in _PASSA}
    saida["ads_vinculados"] = ads_vinculados
    return saida


async def _percorrer(
    ctx: ContextoMeta, ad_account_id: str, edge: str, fields: str, operacao: str
) -> tuple[list[dict[str, Any]], bool]:
    """Linhas da varredura e se ainda havia mais paginas (`paging.next`)."""
    resp = await run_meta_graph_get(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=ad_account_id,
        edge=f"/{ad_account_id}/{edge}",
        params={"fields": fields, "limit": _POSSE_LIMIT},
        operation_name=operacao,
        max_pages=_POSSE_MAX_PAGES,
        audit_this_call=True,
        params_summary={"ad_account_id": ad_account_id, "call": f"posse_{edge}"},
    )
    linhas = [linha for linha in (resp.get("data") or []) if isinstance(linha, dict)]
    return linhas, bool((resp.get("paging") or {}).get("next"))


def _criativo_de(linha: dict[str, Any]) -> str | None:
    c = linha.get("creative")
    cid = c.get("id") if isinstance(c, dict) else None
    return str(cid) if cid is not None else None


async def ler_anuncios(
    ctx: ContextoMeta, ad_account_id: str, operacao: str
) -> tuple[list[dict[str, Any]], bool]:
    return await _percorrer(ctx, ad_account_id, "ads", "id,creative{id}", operacao)


async def provar_posse(
    ctx: ContextoMeta,
    ad_account_id: str,
    operacao: str,
    *,
    ad_id: str | None = None,
    creative_id: str | None = None,
) -> str:
    """Devolve o `creative_id` provadamente da conta; levanta `PosseNaoProvada` se nao."""
    if (ad_id is None) == (creative_id is None):
        raise PosseNaoProvada("informe exatamente um de ad_id ou creative_id")
    if ad_id is not None:
        anuncios, _ = await ler_anuncios(ctx, ad_account_id, operacao)
        for linha in anuncios:
            if str(linha.get("id")) == ad_id:
                cid = _criativo_de(linha)
                if cid is None:
                    raise PosseNaoProvada("o anúncio não tem criativo associado")
                return cid
        raise PosseNaoProvada(
            "anúncio não encontrado nesta conta; " + MSG_GRANDE.format(n=_POSSE_LIMIT * 5)
        )
    criativos, _ = await _percorrer(ctx, ad_account_id, "adcreatives", "id", operacao)
    for linha in criativos:
        if str(linha.get("id")) == creative_id:
            return str(creative_id)
    raise PosseNaoProvada(
        "criativo não encontrado nesta conta; " + MSG_GRANDE.format(n=_POSSE_LIMIT * 5)
    )


async def listar_criativos(
    ctx: ContextoMeta, ad_account_id: str, limit: int, ad_id: str | None, operacao: str
) -> tuple[list[dict[str, Any]], bool]:
    """Lista criativos. Com `ad_id`, so o criativo daquele anuncio, com `ads_vinculados`."""
    vinculos: dict[str, list[str]] | None = None
    ads_truncados = False
    alvo: str | None = None
    if ad_id is not None:
        anuncios, ads_truncados = await ler_anuncios(ctx, ad_account_id, operacao)
        vinculos = {}
        for linha in anuncios:
            cid = _criativo_de(linha)
            if cid is not None:
                vinculos.setdefault(cid, []).append(str(linha.get("id")))
            if str(linha.get("id")) == ad_id:
                alvo = cid
        if not any(str(a.get("id")) == ad_id for a in anuncios):
            raise PosseNaoProvada(
                "anúncio não encontrado nesta conta; " + MSG_GRANDE.format(n=_POSSE_LIMIT * 5)
            )
        if alvo is None:
            raise PosseNaoProvada("o anúncio não tem criativo associado")
    pagina, max_pages = _pagina_e_max(limit)
    if alvo is not None:
        pagina, max_pages = _POSSE_LIMIT, _POSSE_MAX_PAGES
    resp = await run_meta_graph_get(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=ad_account_id,
        edge=f"/{ad_account_id}/adcreatives",
        params={"fields": _CAMPOS, "limit": pagina},
        operation_name=operacao,
        max_pages=max_pages,
        audit_this_call=True,
        params_summary={"ad_account_id": ad_account_id, "ad_id": ad_id},
    )
    linhas = [x for x in (resp.get("data") or []) if isinstance(x, dict)]
    sobrou_next = bool((resp.get("paging") or {}).get("next"))
    if alvo is not None:
        achados = [x for x in linhas if str(x.get("id")) == alvo]
        if not achados:
            raise PosseNaoProvada(
                "criativo do anúncio não encontrado; " + MSG_GRANDE.format(n=_POSSE_LIMIT * 5)
            )
        assert vinculos is not None
        return [parse_criativo(achados[0], vinculos.get(alvo, []))], ads_truncados
    truncated = len(linhas) > limit or sobrou_next
    return [parse_criativo(x, None) for x in linhas[:limit]], truncated


class _IframeSrc(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.src: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "iframe" and self.src is None:
            for nome, valor in attrs:
                if nome == "src" and valor:
                    self.src = valor
                    return


def extrair_src_iframe(html: Any) -> str | None:
    """`src` do primeiro iframe, so se https e host facebook.com (ou subdominio)."""
    if not isinstance(html, str) or not html:
        return None
    parser = _IframeSrc()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001
        return None
    src = parser.src
    if not src:
        return None
    try:
        partes = urlsplit(src)
        host = (partes.hostname or "").lower()
    except ValueError:
        return None
    if "\\" in src or src != src.strip() or any(ord(c) < 33 for c in src):
        return None
    if partes.scheme != "https" or partes.username or partes.password:
        return None
    try:
        if partes.port is not None:
            return None
    except ValueError:
        return None
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        return None
    if host != "facebook.com" and not host.endswith(".facebook.com"):
        return None
    return src


async def gerar_previa(
    ctx: ContextoMeta, ad_account_id: str, creative_id: str, ad_format: str, operacao: str
) -> Any:
    """Chama `generatepreviews`. SO depois de `provar_posse`."""
    resp = await run_meta_graph_get(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=ad_account_id,
        edge=f"/{ad_account_id}/generatepreviews",
        params={"ad_format": ad_format, "creative": json.dumps({"id": creative_id})},
        operation_name=operacao,
        audit_this_call=True,
        params_summary={
            "ad_account_id": ad_account_id,
            "creative_id": creative_id,
            "ad_format": ad_format,
        },
    )
    data = resp.get("data") or []
    if not data or not isinstance(data[0], dict):
        return None
    return data[0].get("body")
