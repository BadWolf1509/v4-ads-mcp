# bucket: defer
"""Tool: get_assets — vinculos de asset nas TRES camadas, num lugar so.

F134: a limpeza de 02/09 previa 4 vinculos em `campaign_asset` e eram 6 — os
mesmos assets tambem existiam em `customer_asset`, e so apareceram porque o
gestor foi atras por desconfianca no `run_gaql`.

NAO calcula precedencia: a probe da spec secao 5.1 mostrou que o conceito nao
existe na API. Devolve o `primary_status` do Google, que e autoritativo e cobre
mais (reprovacao, revisao pendente, LIMITED).
"""

import asyncio
from typing import Any

from src.google_ads.asset_inventory import build_inventory
from src.google_ads.queries.assets import (
    build_ad_group_asset_query,
    build_campaign_asset_query,
    build_customer_asset_query,
    parse_ad_group_asset_row,
    parse_campaign_asset_row,
    parse_customer_asset_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "field_type": {
            "type": "string",
            "description": (
                "Opcional. Filtra por tipo (CALLOUT, SITELINK, STRUCTURED_SNIPPET, "
                "CALL, PROMOTION, BUSINESS_LOGO...). Default: TODOS os tipos."
            ),
        },
        "campaign_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 50,
            "description": "Opcional. Restringe a camada de campanha a estes ids.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 200,
            "description": "Máximo de vínculos retornados. truncated:true se exceder.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Lista vínculos de asset nas TRÊS camadas — customer_asset, "
    "campaign_asset e ad_group_asset — numa resposta só, cada linha com `level` e "
    "`resource_name` (o mesmo que `remove_asset_link` recebe). Traz "
    "`primary_status` + `primary_status_reasons`, que é o veredito do Google "
    "sobre servir (ELIGIBLE|PAUSED|REMOVED|PENDING|LIMITED|NOT_ELIGIBLE), e "
    "`summary.assets_sem_vinculo_ativo` com os órfãos. **NÃO filtra status por "
    "default**: linha REMOVED é a única prova positiva de que uma remoção "
    "funcionou — contagem não distingue, porque o vínculo removido continua na "
    "tabela. ATENÇÃO: não existe campo de precedência entre camadas na API do "
    "Google (o enum de razões não tem nenhum valor de ofuscamento), então esta "
    "tool não afirma qual vínculo 'vence' — ela mostra os três e o veredito de "
    "cada um. Filtros: field_type opcional (default todos), campaign_ids "
    "opcional, limit (default 200, teto 1000)."
)


@register_tool(
    name="get_assets",
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_assets(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    field_type = args.get("field_type")
    campaign_ids = args.get("campaign_ids")
    limit = args.get("limit", 200)

    async def _consulta(query: str, parser: Any, fase: str) -> list[dict[str, Any]]:
        return await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=query,
            row_formatter=parser,
            operation_name="get_assets",
            audit_this_call=False,
            params_summary={"phase": fase, "field_type": field_type},
        )

    # As TRES camadas em paralelo. Consultar so uma e o bug de 02/09.
    conta, campanha, grupo = await asyncio.gather(
        _consulta(
            build_customer_asset_query(field_type=field_type),
            parse_customer_asset_row,
            "customer_asset",
        ),
        _consulta(
            build_campaign_asset_query(field_type=field_type, campaign_ids=campaign_ids),
            parse_campaign_asset_row,
            "campaign_asset",
        ),
        _consulta(
            build_ad_group_asset_query(field_type=field_type),
            parse_ad_group_asset_row,
            "ad_group_asset",
        ),
    )

    links, summary = build_inventory(rows=[*conta, *campanha, *grupo], limit=limit)
    return {"customer_id": customer_id, "links": links, "summary": summary}
