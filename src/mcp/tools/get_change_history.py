# bucket: defer
"""Tool: get_change_history - audit-log of recent changes to the account.

Wraps the change_event GAQL resource with structured filters and a summary
block. Two V4 skills (auditoria-google-ads + analise-performance-google-ads)
call this as 'CRITICO antes de tudo' to detect:
- Auto-apply Recommendations (client_type em AUTO_APPLY_CLIENT_TYPES)
- Structural changes (geo settings, conversion actions, bidding strategy)
- Who changed what

Audited as a sensitive read.

Caveats (empirically verified against production change_event 2026-05-11,
re-confirmado em dogfood 2026-05-21 MO-JP, e refinado em dogfood 2026-05-25
MO-JP+CAB pós-reverts Pedro 21/05):
- Propagation lag: change_event é AUDIT LOG LAGGING, NOT real-time. **O lag
  não tem contrato**: medido de ~3h (conta 786-223-0676 em 2026-09-02 — writes
  às 11:28-11:43 invisíveis às 11:50 e presentes no fim da tarde) a >4 dias
  (dogfood 25/05, 3 dos 4 reverts Pedro de 21/05 ainda ausentes), na MESMA
  conta. F131: é por ser variável que a fronteira passou a ser MEDIDA a cada
  chamada e devolvida em `freshness`, em vez de prometida em prosa aqui. O lag
  afeta MÚLTIPLOS campos, não apenas `campaign.status` — também
  `ai_max_setting.enable_ai_max`, `asset_automation_settings`,
  `text_guidelines.messaging_restrictions`, etc.
- Padrão V4 pra validar estado ATUAL pós-mutação (revert/incident recovery):
  use `run_gaql FROM campaign` como LEADING indicator (real-time) e
  `get_change_history` como LAGGING (audit log). Se divergirem, confie no
  leading. Se um campo opcional não retornar no GAQL, está vazio/removido.
- 30-day window é a retenção documentada; alguns date_range presets podem
  bater limite ligeiramente menor. Nosso path usa explicit BETWEEN dates.
- Google não distingue 'user applied via Recommendations UI' de 'Google
  auto-apply' em change_event.client_type. summary.auto_applied_count
  conta a união dos dois valores de recommendations (F142);
  cross-reference auto-apply settings se intent matters.
"""

from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.change_scan import consultar_change_history
from src.mcp.context import get_current
from src.mcp.tools._common import propriedades_de_data
from src.mcp.tools._registry import register_tool

# F135: espelha ChangeEventResourceType do SDK (v24, verificado 2026-09-02).
# NAO edite a mao sem rodar tests/unit/test_change_event_enum_guards.py — ele
# reconcilia esta lista com o enum do SDK e falha nas DUAS direcoes.
#
# A lista anterior era mantida a mao e divergiu em 13 posicoes: faltavam 10
# (entre elas `AD`, que e o que a API emite quando um RSA e editado, enquanto
# `AD_GROUP_AD` era o unico enum de anuncio oferecido — filtro por anuncio
# devolvia zero com 20 edicoes no dia) e sobravam 3 que a API rejeita com
# "Invalid enum value cannot be included in WHERE clause".
#
# Deliberadamente NAO derivado do SDK em runtime: o schema de uma tool MCP e
# contrato publico, e derivar faria um bump do lockfile mudar os valores
# aceitos sem diff nem revisao. Fonte autoritativa e o SDK; reconciliador e o
# guard no CI.
_OPERATION_TYPES = ["CREATE", "UPDATE", "REMOVE"]

_RESOURCE_TYPES = [
    "AD",
    "AD_GROUP",
    "AD_GROUP_AD",
    "AD_GROUP_ASSET",
    "AD_GROUP_BID_MODIFIER",
    "AD_GROUP_CRITERION",
    "AD_GROUP_FEED",
    "ASSET",
    "ASSET_SET",
    "ASSET_SET_ASSET",
    "CAMPAIGN",
    "CAMPAIGN_ASSET",
    "CAMPAIGN_ASSET_SET",
    "CAMPAIGN_BUDGET",
    "CAMPAIGN_CRITERION",
    "CAMPAIGN_FEED",
    "CUSTOMER_ASSET",
    "FEED",
    "FEED_ITEM",
]

# ChangeClientType. Reconciliado com o enum do SDK pelo guard em
# `tests/unit/test_change_client_type_guards.py` — nao edite a mao sem
# rodar ele. A verificacao empirica de 2026-05-11 pegou os nomes certos
# mas deixou passar duas divergencias por dois meses (F142): um plural
# que nao existe e o valor de auto-apply por assinatura, que faltava.
_CLIENT_TYPES = [
    "UNSPECIFIED",
    "UNKNOWN",
    "GOOGLE_ADS_WEB_CLIENT",  # Web UI (Google Ads website)
    "GOOGLE_ADS_AUTOMATED_RULE",  # F142: era plural; a API rejeita o plural
    "GOOGLE_ADS_SCRIPTS",
    "GOOGLE_ADS_BULK_UPLOAD",
    "GOOGLE_ADS_API",
    "GOOGLE_ADS_EDITOR",
    "GOOGLE_ADS_MOBILE_APP",
    "GOOGLE_ADS_RECOMMENDATIONS",
    "GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION",  # F142: auto-apply por assinatura
    "SEARCH_ADS_360_SYNC",
    "SEARCH_ADS_360_POST",
    "INTERNAL_TOOL",
    "OTHER",
]

# A constante de auto-apply vive em `drift_detection` (fonte unica). Havia
# uma copia aqui, e copia divergente foi o vetor do F142.
#
# Google nao distingue "aplicado pelo gestor via UI de Recommendations" de
# "aplicado pelo auto-apply do Google" dentro de cada valor — skills que
# usam `auto_applied_count` devem cruzar com as settings de auto-apply.

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        **propriedades_de_data(default="LAST_7_DAYS"),
        # F183: array sem teto vira clausula IN de GAQL sem teto. Nos tres que sao
        # enum o teto e DERIVADO da propria lista (`len(...)`) — numero escrito a mao
        # seria segunda fonte de verdade e passaria a mentir quando o enum mudasse.
        "resource_types": {
            "type": "array",
            "items": {"type": "string", "enum": _RESOURCE_TYPES},
            "maxItems": len(_RESOURCE_TYPES),
        },
        "operation_types": {
            "type": "array",
            "items": {"type": "string", "enum": _OPERATION_TYPES},
            "maxItems": len(_OPERATION_TYPES),
        },
        "user_emails": {
            "type": "array",
            "items": {"type": "string", "format": "email"},
            # Sem enum pra derivar: 20 acompanha `detect_drift.responsible_user_emails`,
            # que filtra a mesma especie de lista (gestores de uma conta).
            "maxItems": 20,
        },
        "client_types": {
            "type": "array",
            "items": {"type": "string", "enum": _CLIENT_TYPES},
            "maxItems": len(_CLIENT_TYPES),
        },
        # 10000, nao 9999: `maximum` e contrato publico ja negociado no
        # handshake do MCP (F140), entao estreita-lo NAO chega na sessao
        # aberta — ela segue anunciando 10000 e passaria a levar erro duro de
        # `jsonschema` (src/mcp/server.py) onde antes funcionava. O cap de 10k
        # do change_event (`_CAP_CHANGE_EVENT`) se resolve DENTRO da tool, pelo
        # idioma `fetch n+1` com teto de API: pede-se `min(limit + 1, CAP)` e,
        # na borda onde a sentinela nao cabe, le-se `len == CAP` como corte.
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 200},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


@register_tool(
    name="get_change_history",
    description=(
        "[DEFER] Historico de mudancas (change_event) na conta nos ultimos 7-30 dias com "
        "filtros opcionais (resource_types, operation_types, user_emails, "
        "client_types). Util pra auditoria 'CRITICO antes de tudo': detectar "
        "auto-apply Recommendations, mudancas estruturais, e quem mexeu no que. "
        "Recomendacao aceita a mao pelo APP de celular sai com client_type "
        "GOOGLE_ADS_MOBILE_APP e o e-mail do gestor, igual a uma edicao manual (sondado em "
        "05/10: nenhum campo do change_event a distingue). "
        "ATENCAO: change_event e audit log LAGGING e o lag NAO tem contrato "
        "— medido de ~3h a >4 dias na MESMA conta. Por isso a resposta traz "
        "`freshness` com a fronteira MEDIDA: `account_frontier` (evento mais "
        "recente indexado na conta, sem filtro), `slice_frontier` (das linhas "
        "devolvidas) e `status` (confiavel|ambiguo|nao_coberto|em_curso|indeterminado). "
        "`nao_coberto` = fronteira anterior ao fim da janela (lag OU conta parada — nao afirma "
        "qual); `em_curso` = a janela alcanca o dia corrente DA CONTA, que ainda nao fechou, "
        "entao `confiavel` nao e alcancavel. Presets de data resolvem no fuso da conta (F141). "
        "Leia o status antes de concluir que nada mudou: lista vazia com "
        "status != confiavel NAO e prova de ausencia. Pra validar estado "
        "atual (revert/incident), use `run_gaql FROM campaign` como "
        "leading indicator. Inclui summary com totais por usuario/resource/"
        "operation. `truncated: true` avisa que a janela tinha MAIS mudancas do que "
        "o limit e a lista foi cortada pelas mais RECENTES — as mais antigas da janela "
        "ficaram de fora, entao suba o limit ou estreite o periodo antes de concluir "
        "que uma mudanca nao existiu. E ortogonal ao `freshness`: `truncated` fala do "
        "que o limit cortou, `freshness` do que o Google ainda nao indexou. "
        "No teto (`limit: 10000`, cap duro do change_event) nao ha linha sentinela "
        "para comparar, entao `truncated: true` ali le-se 'pode haver mais' e pode "
        "significar que coube exato — estreite a janela pra ter certeza. "
        "Janela maxima 30 dias (Google retention exclusivo — start_date "
        "alem disso e auto-clampado pra today-28 com warning F23, preset OU custom; "
        "janela inteira fora da retencao da erro claro). Audited."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_change_history(args: dict[str, Any]) -> dict[str, Any]:
    # F141: UM `hoje` por request, no fuso da conta, pra janela, clamp, sonda e
    # freshness. A resolucao fica AQUI, no handler registrado, e o corpo recebe
    # o `today` pronto: `detect_drift` chama `consultar_change_history` ate 30
    # vezes numa varredura particionada, e cada uma delas re-resolvendo o
    # relogio seria uma leitura de banco por sub-janela E — pior — um `hoje`
    # diferente no meio de uma varredura que atravessasse a meia-noite da
    # conta. Isso e a familia do F141 dentro do proprio fix do F141.
    ctx = get_current()
    return await consultar_change_history(
        args,
        today=await resolve_account_today(args["customer_id"]),
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
    )
