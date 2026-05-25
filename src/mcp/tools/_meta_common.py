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


def parse_meta_ad_account_id(raw: str) -> str:
    """Normalize ad_account_id to 'act_<numeric>' format."""
    if raw.startswith("act_"):
        return raw
    return f"act_{raw}"
