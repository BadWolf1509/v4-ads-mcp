"""Helpers compartilhados pelas tools Meta MCP (Sprint M.2a Task 9 onwards)."""

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


def parse_meta_ad_account_id(raw: str) -> str:
    """Normalize ad_account_id to 'act_<numeric>' format."""
    if raw.startswith("act_"):
        return raw
    return f"act_{raw}"
