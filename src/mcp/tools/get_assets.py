# bucket: always
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
    "[CORE] Lista vínculos de asset nas TRÊS camadas — customer_asset, "
    "campaign_asset e ad_group_asset — numa resposta só, cada linha com `level` e "
    "`resource_name` (o mesmo que `remove_asset_link` recebe). Traz "
    "`primary_status` + `primary_status_reasons`, que é o veredito do Google "
    "sobre servir (ELIGIBLE|PAUSED|REMOVED|PENDING|LIMITED|NOT_ELIGIBLE, e "
    "UNSPECIFIED — que aparece de verdade em produção, então trate a lista "
    "como aberta). **`primary_status_reasons` carrega mais que remoção:** "
    "além de ASSET_LINK_REMOVED vêm ASSET_DISAPPROVED e ASSET_UNDER_REVIEW, "
    "ou seja reprovação de política e revisão pendente ficam visíveis aqui "
    "sem outra query. **`asset_name` vem VAZIO nas famílias de texto** "
    "(SITELINK, CALLOUT, CALL, STRUCTURED_SNIPPET, PROMOTION, BUSINESS_NAME, "
    "BUSINESS_MESSAGE): o Google só popula `name` para algumas famílias, "
    "então string vazia ali NÃO significa asset sem conteúdo — para o texto "
    "use `run_gaql` no campo do tipo (ex.: asset.callout_asset.callout_text). "
    "**NÃO "
    "filtra status por default**: linha REMOVED é a única prova positiva de que "
    "uma remoção funcionou — contagem não distingue, porque o vínculo removido "
    "continua na tabela. ATENÇÃO: não existe campo de precedência entre camadas "
    "na API do Google (o enum de razões não tem nenhum valor de ofuscamento), "
    "então esta tool não afirma qual vínculo 'vence' — ela mostra os três e o "
    "veredito de cada um. Filtros: field_type opcional (default todos), "
    "campaign_ids opcional, limit (default 200, teto 1000). **O default de "
    "200 trunca em conta real:** medido na 786-223-0676 são 735 vínculos, "
    "dos quais 598 (81%) são AD_IMAGE de RSA — a família de imagem domina a "
    "contagem e afoga as extensões de texto. Para inventário de conta use "
    "`limit: 1000`; para trabalhar extensões use `field_type`. Truncado traz "
    "`summary.truncated: true`, e a ordem é por `asset_id`, não por "
    "relevância. **Detecção de "
    "órfão exige chamada SEM filtro**: numa chamada sem field_type e sem "
    "campaign_ids, `summary.assets_sem_vinculo_ativo` lista os assets sem "
    "vínculo ENABLED em NENHUMA camada (inclui os que só têm vínculo PAUSED ou "
    "REMOVED) e `summary.orphan_scope` vem `conta_completa`. Com QUALQUER "
    "filtro ativo (field_type OU campaign_ids), a chave `assets_sem_vinculo_"
    "ativo` NÃO aparece — campaign_ids restringe só a camada de campanha, "
    "então um asset com o único vínculo ENABLED fora do recorte pareceria "
    "órfão por engano; `orphan_scope` vem `nao_calculado_com_filtro` "
    "explicando por quê."
)


@register_tool(
    name="get_assets",
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="always",
)
async def get_assets(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    field_type = args.get("field_type")
    campaign_ids = args.get("campaign_ids")
    limit = args.get("limit", 200)
    # Decide tanto a auditoria quanto a supressao do orfao: qualquer filtro
    # ativo torna as tres camadas um recorte, nao a conta inteira — mesma
    # classe do F134, na direcao oposta (la faltava camada; aqui sobraria
    # confianca sobre uma fatia parcial).
    filter_active = field_type is not None or campaign_ids is not None

    async def _consulta(query: str, parser: Any, *, audited: bool = False) -> list[dict[str, Any]]:
        return await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=query,
            row_formatter=parser,
            operation_name="get_assets",
            audit_this_call=audited,
            # params_summary so e construido quando de fato audita — antes
            # disso era montado nas tres chamadas e descartado sempre, porque
            # audit_this_call nunca passava de False.
            params_summary=(
                {"field_type": field_type, "campaign_ids": campaign_ids, "limit": limit}
                if audited
                else None
            ),
        )

    # As TRES camadas em paralelo. Consultar so uma e o bug de 02/09. So a
    # camada `customer_asset` audita: essa tool e o passo de descoberta antes
    # de um `remove_asset_link` destrutivo, e uma chamada do gestor tem que
    # virar UMA linha em audit_log/detect_drift, nao tres (uma por camada).
    # `customer_asset` e a escolhida por ser a camada que este branch inteiro
    # existe pra tornar visivel (F134). Segue o padrao de
    # get_change_history.py: a query principal audita, sondas irmãs nao.
    conta, campanha, grupo = await asyncio.gather(
        _consulta(
            build_customer_asset_query(field_type=field_type),
            parse_customer_asset_row,
            audited=True,
        ),
        _consulta(
            build_campaign_asset_query(field_type=field_type, campaign_ids=campaign_ids),
            parse_campaign_asset_row,
        ),
        _consulta(
            build_ad_group_asset_query(field_type=field_type),
            parse_ad_group_asset_row,
        ),
    )

    links, summary = build_inventory(
        rows=[*conta, *campanha, *grupo], limit=limit, filter_active=filter_active
    )
    return {"customer_id": customer_id, "links": links, "summary": summary}
