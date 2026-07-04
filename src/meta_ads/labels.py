"""Meta enum -> PT-BR label lookups. Domínio puro, zero SDK imports.

Movido de src.mcp.tools._meta_common (Sprint M.2a) — mesmo dado, lugar certo:
labels de domínio Meta, não helper de tool. `_meta_common` re-exporta pra
manter os call-sites antigos funcionando.
"""

META_ACCOUNT_STATUS_LABELS: dict[int, str] = {
    1: "ATIVO",
    2: "DESABILITADO",
    3: "PAGAMENTO_PENDENTE",
    7: "EM_REVISÃO_DE_RISCO",
    101: "FECHADO",
    102: "ANY_ACTIVE",
    201: "FECHAMENTO_PENDENTE",
    202: "LIQUIDAÇÃO_PENDENTE",
}


META_EFFECTIVE_STATUS_LABELS: dict[str, str] = {
    "ACTIVE": "ATIVO",
    "PAUSED": "PAUSADO",
    "ARCHIVED": "ARQUIVADO",
    "DELETED": "REMOVIDO",
    "PENDING_REVIEW": "EM_REVISÃO",
    "DISAPPROVED": "REPROVADO",
    "PREAPPROVED": "PRÉ_APROVADO",
    "PENDING_BILLING_INFO": "COBRANÇA_PENDENTE",
    "CAMPAIGN_PAUSED": "CAMPANHA_PAUSADA",
    "ADSET_PAUSED": "ADSET_PAUSADO",
}
