# bucket: defer
"""Tool: add_negative_keywords - add campaign-level negative keywords. Auto-applies.

Spec 2026-10-05 §3.2: antes de gravar, le as negativas da campanha. A repetida (mesmo texto e
tipo) sai do lote — o Google a descartaria em silencio (catalogo A1) e a resposta diria
"aplicada" sobre nada. A coberta por uma mais ampla e gravada e avisada. A acentuada sem o par
sem acento e avisada — o Google nao aplica variante proxima em negativa — e, com
`incluir_variante_sem_acento`, o par entra no lote.
"""

from typing import Any

import structlog

from src.google_ads.access import AccountAccessDeniedError
from src.google_ads.errors import GoogleAdsFriendlyError
from src.google_ads.mutations import run_mutation
from src.google_ads.negativas import chave, classificar, sem_acento
from src.google_ads.queries.tactical import campaign_negative_keywords_query
from src.google_ads.reports import run_report
from src.governance.blast_radius import classify
from src.governance.rate_limit import QuotaExhausted
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import applied_envelope
from src.mcp.tools._registry import register_tool

log = structlog.get_logger(__name__)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "campaign_id": {"type": "string", "pattern": "^[0-9]+$"},
        "keywords": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 80},
                    "match_type": {
                        "type": "string",
                        "enum": ["EXACT", "PHRASE", "BROAD"],
                    },
                },
                "required": ["text", "match_type"],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": 500,
        },
        "incluir_variante_sem_acento": {
            "type": "boolean",
            "default": False,
            "description": (
                "Grava tambem a grafia sem acento de cada negativa acentuada (mesmo match type), "
                "quando ela ainda nao existe — o Google nao aplica variante proxima em negativa."
            ),
        },
    },
    "required": ["customer_id", "campaign_id", "keywords"],
    "additionalProperties": False,
}

# Motivo FIXO: o texto cru do erro (host, SQL, driver) nao chega ao gestor — o scrub do
# `_error_envelope` do servidor. So o erro escrito para ele (friendly, quota) vai junto.
_MOTIVO_LEITURA_FALHOU = "leitura das negativas da campanha falhou"


def _negativa_existente(row: Any) -> dict[str, Any]:
    cc = row.campaign_criterion
    return {
        "criterion_id": str(cc.criterion_id),
        "text": cc.keyword.text,
        "match_type": cc.keyword.match_type.name,
    }


def _planejar(
    pedidas: list[dict[str, Any]],
    existentes: list[dict[str, Any]],
    incluir_variante: bool,
) -> dict[str, list[dict[str, Any]]]:
    """O lote que vai ao Google e o que a resposta conta sobre o resto."""
    lote: list[dict[str, Any]] = []
    ja_existia: list[dict[str, Any]] = []
    avisos: list[dict[str, Any]] = []
    variantes: list[dict[str, Any]] = []
    conhecidas = list(existentes)
    for kw in pedidas:
        estado, existente = classificar(kw, conhecidas)
        if estado == "repetida":
            origem = "campanha" if any(existente is e for e in existentes) else "pedido"
            ja_existia.append({**kw, "existente": existente, "origem": origem})
            continue
        lote.append(kw)
        conhecidas.append(kw)
    # Cobertura DEPOIS do lote montado: contra a campanha e o resto do pedido, em qualquer
    # ordem — `[PHRASE x, BROAD x]` e `[BROAD x, PHRASE x]` dizem o mesmo.
    for kw in lote:
        estado, existente = classificar(kw, [c for c in conhecidas if c is not kw])
        if estado == "coberta":
            avisos.append({"tipo": "coberta", **kw, "coberta_por": existente})
    vistas: set[tuple[str, str]] = set()
    for kw in pedidas:
        if (chave(kw["text"]), kw["match_type"]) in vistas:
            continue
        vistas.add((chave(kw["text"]), kw["match_type"]))
        texto = sem_acento(kw["text"])
        if texto is None:
            continue
        par = {"text": texto, "match_type": kw["match_type"]}
        if classificar(par, conhecidas + pedidas)[0] != "nova":
            continue
        if incluir_variante:
            lote.append(par)
            conhecidas.append(par)
            variantes.append({**par, "variante_de": kw["text"]})
        else:
            avisos.append({"tipo": "sem_variante_sem_acento", **kw, "sugestao": texto})
    return {
        "lote": lote,
        "ja_existia": ja_existia,
        "avisos": avisos,
        "variantes_incluidas": variantes,
    }


async def _negativas_da_campanha(
    customer_id: str, campaign_id: str
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """As negativas existentes, ou `(None, motivo)` quando a leitura nao mediu."""
    ctx = get_current()
    gaql, _ = campaign_negative_keywords_query(campaign_id)
    try:
        linhas = await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=gaql,
            row_formatter=_negativa_existente,
            operation_name="add_negative_keywords",
        )
    except AccountAccessDeniedError:
        raise  # acesso negado nao e "cobertura desconhecida": o envelope responde `denied`
    except (GoogleAdsFriendlyError, QuotaExhausted) as e:
        log.info("negativas_leitura_previa_falhou", customer_id=customer_id, error=str(e))
        return None, f"{_MOTIVO_LEITURA_FALHOU}: {e}"
    except Exception:
        log.exception("negativas_leitura_previa_falhou", customer_id=customer_id)
        return None, _MOTIVO_LEITURA_FALHOU
    return linhas, None


@register_tool(
    name="add_negative_keywords",
    description=(
        "[DEFER] Adiciona palavras-chave negativas em nivel de campanha. Sempre auto-aplica "
        "(negativas raramente quebram coisas - spec §7.1). Aceita ate 500 negativas "
        "por chamada com match_type EXACT, PHRASE ou BROAD."
        " O Google NAO aplica variante proxima em negativa: acento, plural e erro de digitacao"
        " sao negativas distintas (medido em 05/10: `material de construção` deixou passar"
        " `material de construcao`). Antes de gravar a tool le as negativas da campanha:"
        " a de mesmo texto e mesmo tipo sai do lote e vem em `ja_existia` (o Google a"
        " descartaria em silencio); a coberta por uma mais ampla do mesmo texto (BROAD cobre"
        " PHRASE e EXACT; PHRASE cobre EXACT) e gravada e vem em `avisos`. A acentuada sem a"
        " grafia sem acento vem em `avisos` com a `sugestao`; com"
        " `incluir_variante_sem_acento: true` o par e gravado e listado em"
        " `variantes_incluidas` — o opt-in pode dobrar o lote (ate 1000 operacoes por"
        " chamada). `ja_existia[].origem` diz se a repetida ja estava na `campanha` ou"
        " veio duas vezes no `pedido`. Plural e erro de digitacao NAO sao tratados."
        " `cobertura_verificada: false` (com `cobertura_motivo`) diz que a leitura previa"
        " falhou e a tool gravou sem conferir. Nada a gravar responde `status: no_changes`."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def add_negative_keywords(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_id = args["campaign_id"]

    existentes, motivo = await _negativas_da_campanha(customer_id, campaign_id)
    plano = _planejar(
        args["keywords"], existentes or [], args.get("incluir_variante_sem_acento", False)
    )
    keywords = plano["lote"]
    relato: dict[str, Any] = {
        "campaign_id": campaign_id,
        "ja_existia": plano["ja_existia"],
        "avisos": plano["avisos"],
        "variantes_incluidas": plano["variantes_incluidas"],
        "cobertura_verificada": existentes is not None,
    }
    if motivo is not None:
        relato["cobertura_motivo"] = motivo

    if not keywords:
        return {
            "status": "no_changes",
            "operation": "add_negative_keywords",
            "customer_id": customer_id,
            "applied_count": 0,
            **relato,
        }

    target_count = len(keywords)
    risk = classify(
        operation="add_negative_keywords",
        params={"target_count": target_count},
    )

    payload = {
        "campaign_id": campaign_id,
        "keywords": keywords,
        "__target_count__": target_count,
    }
    summary = (
        f"Adicionar {target_count} negativa(s) na campanha {campaign_id}. "
        f"Match types: {sorted({k['match_type'] for k in keywords})}."
    )

    # add_negative_keywords always classifies as AUTO per blast_radius
    result = await run_mutation(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        operation_type="add_negative_keywords",
        payload=payload,
        target_count=target_count,
    )
    return applied_envelope(
        "add_negative_keywords",
        customer_id,
        summary,
        applied_count=result["applied_count"],
        provider_request_id=result["provider_request_id"],
        auto_applied_reason=risk.reason,
        resource_names=result.get("resource_names", []),
        **relato,
    )
