# bucket: defer
"""Tool: update_rsa - modify existing Responsive Search Ads.

Always-CONFIRM. Updates via AdService.mutate_ads (not AdGroupAdService).
Provided field lists REPLACE existing (proto-plus semantics with
field_mask).

Pre-flight validates ad existence + RSA type + parent ad_group/campaign
context. Same JSONSchema rules as create_rsa for individual fields
(headlines 3-15 x 30 chars, etc) but all mutable fields optional. The
"at least one mutable field per update" constraint is enforced at runtime
in the tool body (Sprint 3b.19B.1: top-level anyOf is rejected by the
Anthropic Messages API; schema can't express it declaratively).
"""

from collections import Counter
from typing import Any

from src.google_ads.preflight import validate_existing_rsas_for_update
from src.google_ads.rsa_textos import (
    campos_de_texto,
    pinos_pedidos,
    pinos_por_posicao_total,
    posicoes_dos_campos,
    restringir,
)
from src.governance.blast_radius import classify
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import emitir_preview, error_envelope
from src.mcp.tools._registry import register_tool
from src.mcp.tools._rsa_textos import (
    AVISO_PINO,
    ITEM_TEXTO,
    POSICOES_DESCRIPTION,
    POSICOES_HEADLINE,
)

_MUTABLE_FIELDS = ("headlines", "descriptions", "final_urls", "path1", "path2")


def _validate_updates_have_mutable_field(
    updates: list[dict[str, Any]],
) -> str | None:
    """Returns PT-BR error if any update lacks all mutable fields; else None.

    Replaces schema-level anyOf (rejected by Anthropic API — see Sprint
    3b.19B.1). First-found-offender semantics mirror Sprint 3b.5 pre-flight
    pattern for consistent UX.
    """
    for u in updates:
        if not any(f in u for f in _MUTABLE_FIELDS):
            fields = ", ".join(_MUTABLE_FIELDS)
            return (
                f"Update do ad_id {u['ad_id']} sem nenhum campo mutavel. "
                f"Forneca ao menos um de: {fields}."
            )
    return None


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "updates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "ad_id": {"type": "string", "pattern": "^[0-9]+$"},
                    "headlines": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 15,
                        "items": ITEM_TEXTO(30, POSICOES_HEADLINE),
                    },
                    "descriptions": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 4,
                        "items": ITEM_TEXTO(90, POSICOES_DESCRIPTION),
                    },
                    "final_urls": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "path1": {"type": "string", "maxLength": 15},
                    "path2": {"type": "string", "maxLength": 15},
                    # G2: libera, NESTE update, a perda de pino por posicao.
                    "remover_pinos": {"type": "boolean", "default": False},
                },
                "required": ["ad_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["customer_id", "updates"],
    "additionalProperties": False,
}


def _build_params_summary(updates: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit-safe: counts only, NO copy text."""
    fields_updated: Counter[str] = Counter()
    for u in updates:
        for f in ("headlines", "descriptions", "final_urls", "path1", "path2"):
            if f in u:
                fields_updated[f] += 1
    return {
        "count": len(updates),
        "fields_updated_distribution": dict(fields_updated),
        "unique_ads": len({u["ad_id"] for u in updates}),
        "pinos_por_posicao_total": pinos_por_posicao_total(updates),
    }


def _preview_do_update(
    u: dict[str, Any], pinos_atuais: dict[str, dict[str, list[str]] | None]
) -> dict[str, Any]:
    """`pinos` so quando o update traz headlines/descriptions, restrito a esses campos.

    `antes` None = nao lido (pre-flight sem a leitura), nunca `{}` (nao medido != zero).
    """
    item: dict[str, Any] = {
        "ad_id": u["ad_id"],
        "fields_updated": sorted(k for k in u if k not in ("ad_id", "remover_pinos")),
    }
    campos = campos_de_texto(u)
    if campos:
        atuais = pinos_atuais.get(u["ad_id"])
        posicoes = posicoes_dos_campos(campos)
        item["pinos"] = {
            "antes": None if atuais is None else restringir(atuais, posicoes),
            "depois": pinos_pedidos(u),
        }
        if u.get("remover_pinos", False):
            item["remover_pinos"] = True
    return item


@register_tool(
    name="update_rsa",
    description=(
        "[DEFER] Modifica 1-5 RSAs existentes. Cada update tem ad_id + pelo menos 1 dos "
        "campos mutaveis: headlines (3-15 × 30 chars), descriptions (2-4 × 90 "
        "chars), final_urls (1+), path1/path2 (15 chars cada). Listas fornecidas "
        "SUBSTITUEM as existentes (semantics proto-plus + field_mask). Item de "
        "headline/description e string (sem pino) ou {text, pinned_field} "
        "(HEADLINE_1..3 / DESCRIPTION_1..2). Como a lista substitui, string sobre "
        "anuncio pinado TIRA o pino: o pre-flight recusa quando uma posicao que hoje "
        "tem pino fica sem nenhum — repita o pino na lista nova ou passe "
        "remover_pinos: true naquele update. Reescrever o texto mantendo a posicao "
        "segue; o preview mostra pinos antes->depois. Pinar reduz a forca do anuncio. "
        "Pino que nao pegou volta com efeito sem_efeito e pinos_resultantes. Sempre "
        "CONFIRM. Pre-flight rejeita ad inexistente, type != RESPONSIVE_SEARCH_AD, "
        "ad_group REMOVED, campaign non-SEARCH, ou anuncio que e variacao de Ad "
        "Variation (gerenciado pelo Google — edite o anuncio base, que a variacao "
        "herda em minutos). Para mudar status, use "
        "update_ad_status. Lote PARCIAL: se o Google recusar um ad_id, os demais "
        "sao aplicados e o apply_change devolve partial_failures com o motivo por "
        "linha — mas recusar e o caso RARO: o padrao medido e o Google ACEITAR e nao "
        "executar (F180/F184), entao confirme pelo `efeito` de cada linha, nunca por "
        "ausencia de falha. Atualizacoes afetam serving immediately mas Google "
        "pode re-aprovar (geralmente minutos). O apply_change devolve `estado_revisao` "
        "(aprovacao/revisao por anuncio, com os textos reprovados) — foto do instante, "
        "nao veredito: logo apos o write o normal e 'em revisao'; use `releitura` depois."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def update_rsa(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    updates = args["updates"]
    target_count = len(updates)

    shape_error = _validate_updates_have_mutable_field(updates)
    if shape_error:
        return error_envelope("update_rsa", shape_error)

    # Preenchido pelo pre-flight com o que ele ja le (zero round-trip): antes->depois.
    pinos_atuais: dict[str, dict[str, list[str]] | None] = {}
    error = await validate_existing_rsas_for_update(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        updates=updates,
        pinos_atuais=pinos_atuais,
    )
    if error:
        return error_envelope("update_rsa", error)

    risk = classify(operation="update_rsa", params={"target_count": target_count})

    params_summary = _build_params_summary(updates)
    fields_dist = params_summary["fields_updated_distribution"]
    unique_ads = params_summary["unique_ads"]
    summary = (
        f"Atualizar {target_count} RSA(s) ({unique_ads} unicos). Campos: "
        f"{', '.join(f'{f}({n})' for f, n in sorted(fields_dist.items()))}."
    )

    payload = {
        "updates": updates,
        "__target_count__": target_count,
        "__params_summary__": params_summary,
        # F180: o lote deixa de ser atomico. Um ad_id que o Google recusa (variacao
        # de experimento, anuncio removido entre o preview e o apply) para de levar
        # junto os outros — `apply_change` devolve `partial_failures` com o motivo
        # por linha e `failed_count`. O custo e real e esta assumido: nao ha
        # invariante que o lote de RSA preserve (anuncios sao independentes), entao
        # aplicar parte e melhor que perder tudo. Ver F180 no catalogo.
        "__partial_failure__": True,
    }

    preview = [_preview_do_update(u, pinos_atuais) for u in updates]
    extra: dict[str, Any] = {}
    if params_summary["pinos_por_posicao_total"]:
        extra["aviso_pinos"] = AVISO_PINO

    return await emitir_preview(
        ctx,
        operation="update_rsa",
        customer_id=customer_id,
        payload=payload,
        resumo=summary,
        risk=risk,
        updates_preview=preview,
        **extra,
    )
