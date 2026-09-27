"""Formas de linha /insights MEDIDAS na Graph API em 26/09 (`scripts/probe_meta_metricas.py`).

Os testes do contrato das métricas Meta (spec 2026-09-26) usam estas formas, e não as
que o código antigo supunha: nenhuma das 24 contas medidas devolveu o nome nu
`purchase`, e as fixtures que o usavam modelavam uma convenção, não a Graph API.

A FORMA é medida: os nomes de ação, quais campos vêm e quais faltam. Os VALORES de
compra (10) e lead (13) também são medidos (Cheiro | Conta 01, 30 dias); o resto é
ilustrativo e diz quando é.
"""

from __future__ import annotations

from typing import Any

# A mesma compra sob 5 nomes e o mesmo lead sob 7 (M2), mais as conversas iniciadas
# (M3) e ações de engajamento que o contrato ignora. `action_values` e
# `purchase_roas` NÃO vêm (M4) — ausentes em 14 de 14 contas.
LINHA_COMPRA_E_LEAD: dict[str, Any] = {
    "spend": "22662.53",
    "impressions": "1000000",  # ilustrativo, coerente com o ctr
    "clicks": "17775",  # ilustrativo
    "ctr": "1.777474",
    "cpc": "1.275",  # ilustrativo
    "reach": "412000",  # ilustrativo
    "frequency": "2.43",  # ilustrativo
    "actions": [
        {"action_type": "link_click", "value": "17775"},
        {"action_type": "omni_purchase", "value": "10"},
        {"action_type": "onsite_app_purchase", "value": "10"},
        {"action_type": "onsite_web_app_purchase", "value": "10"},
        {"action_type": "onsite_conversion.purchase", "value": "10"},
        {"action_type": "onsite_web_purchase", "value": "10"},
        {"action_type": "onsite_conversion.lead", "value": "13"},
        {"action_type": "offsite_complete_registration_add_meta_leads", "value": "13"},
        {"action_type": "offsite_search_add_meta_leads", "value": "13"},
        {"action_type": "onsite_web_lead", "value": "13"},
        {"action_type": "lead", "value": "13"},
        {"action_type": "offsite_content_view_add_meta_leads", "value": "13"},
        {"action_type": "onsite_conversion.lead_grouped", "value": "13"},
        {"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": "3531"},
    ],
}

# A conta típica (13 das 14 com gasto): só conversas iniciadas e engajamento, sem
# nenhum tipo de compra ou lead. Valores ilustrativos.
LINHA_SO_CONVERSAS: dict[str, Any] = {
    "spend": "839.79",
    "impressions": "91000",
    "clicks": "839",
    "ctr": "0.922477",
    "cpc": "1.0009",
    "reach": "40210",
    "frequency": "2.26",
    "actions": [
        {"action_type": "link_click", "value": "610"},
        {"action_type": "post_engagement", "value": "1204"},
        {"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": "37"},
    ],
}

# Linha do breakdown horário (M5): `reach` e `frequency` ausentes em 50 de 50 linhas.
LINHA_HORARIA: dict[str, Any] = {
    "campaign_id": "120210000000000001",
    "campaign_name": "Conversas | JP",
    "hourly_stats_aggregated_by_advertiser_time_zone": "09:00:00 - 09:59:59",
    "spend": "12.3",
    "impressions": "1400",
    "clicks": "21",
    "ctr": "1.5",
    "cpc": "0.5857",
}
