"""Meta enum -> PT-BR label lookups. Domínio puro, zero SDK imports.

Movido de src.mcp.tools._meta_common (Sprint M.2a) — mesmo dado, lugar certo:
labels de domínio Meta, não helper de tool. `_meta_common` re-exporta pra
manter os call-sites antigos funcionando.
"""

# Codigos conferidos na referencia oficial do Ad Account (campos `account_status` e
# `disable_reason`) em 30/10. A tabela anterior tinha 102 (inexistente), 201/202 com o
# significado de 100/8, e nao tinha 8, 9 e 100. 201/202 sao agregados de filtro, nao status
# de uma conta, mas ficam rotulados caso a Graph os devolva.
META_ACCOUNT_STATUS_LABELS: dict[int, str] = {
    1: "ATIVO",
    2: "DESABILITADO",
    3: "PAGAMENTO_PENDENTE",
    7: "EM_REVISÃO_DE_RISCO",
    8: "LIQUIDAÇÃO_PENDENTE",
    9: "EM_PERÍODO_DE_CARÊNCIA",
    100: "FECHAMENTO_PENDENTE",
    101: "FECHADO",
    201: "QUALQUER_ATIVA",
    202: "QUALQUER_FECHADA",
}


META_DISABLE_REASON_LABELS: dict[int, str] = {
    0: "NENHUM",
    1: "POLÍTICA_DE_INTEGRIDADE_DE_ANÚNCIOS",
    2: "REVISÃO_DE_PROPRIEDADE_INTELECTUAL",
    3: "RISCO_DE_PAGAMENTO",
    4: "CONTA_CINZA_ENCERRADA",
    5: "REVISÃO_AFC",
    6: "REVISÃO_DE_INTEGRIDADE_DO_NEGÓCIO",
    7: "FECHAMENTO_PERMANENTE",
    8: "CONTA_DE_REVENDEDOR_SEM_USO",
    9: "CONTA_SEM_USO",
    10: "CONTA_GUARDA_CHUVA",
    11: "POLÍTICA_DE_INTEGRIDADE_DO_BUSINESS_MANAGER",
    12: "CONTA_DESCARACTERIZADA",
    13: "DESCOMPARTILHAMENTO_DE_ENTIDADE_LEGAL",
    14: "REVISÃO_DE_CONVERSA_CTX",
    15: "CONTA_COMPROMETIDA",
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
