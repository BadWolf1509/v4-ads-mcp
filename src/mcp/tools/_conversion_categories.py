"""Categorias de conversao: fonte unica para create_conversion_action e os audits.

Os audits (`audit_orphan_smart_actions`, `audit_goal_attribution`) tinham uma
copia propria da lista e ela ficou sem PHONE_CALL_LEAD, ADD_TO_CART,
BEGIN_CHECKOUT e SUBSCRIBE_PAID: dava pra criar a conversao e nao dava pra
audita-la. Agora as categorias criaveis vivem aqui e os audits derivam delas.
"""

CATEGORIAS_CRIAVEIS = [
    # Sprint 3b.19A removed values (validated empiricamente em smoke runbook,
    # including per-value probe em 3b.19A.1):
    # - "LEAD" (F17): removido do SDK v20 — era value 6 historicamente.
    # - "IMPORTED_LEAD" (F18): ENUM_VALUE_NOT_PERMITTED — system-managed pelo
    #   Google Lead Form / CRM import workflow.
    # - "QUALIFIED_LEAD" (F18): INVALID_VALUE — system-managed (lead lifecycle).
    # - "CONVERTED_LEAD" (F18): INVALID_VALUE — system-managed (lead lifecycle).
    # - "DOWNLOAD" (F19): INVALID_VALUE em WEBPAGE + UPLOAD_CLICKS types —
    #   provavelmente requer GOOGLE_PLAY_DOWNLOAD type (app-install workflow,
    #   niche excluido do _TYPE_ENUM v0).
    # Final whitelist: 13 categorias V4-focused empirically validated.
    "DEFAULT",
    "PURCHASE",
    "SIGNUP",
    "SUBMIT_LEAD_FORM",
    "BOOK_APPOINTMENT",
    "REQUEST_QUOTE",
    "PHONE_CALL_LEAD",
    "ADD_TO_CART",
    "BEGIN_CHECKOUT",
    "SUBSCRIBE_PAID",
    "CONTACT",
    "ENGAGEMENT",
    "PAGE_VIEW",
]

# Categorias que o Google devolve em conversoes existentes mas que a tool de
# criacao nao oferece (sao filtro valido dos audits, nao valor de criacao).
_SO_LEITURA = ["GET_DIRECTIONS", "OUTBOUND_CLICK", "STORE_VISIT", "STORE_SALE"]

CATEGORIAS_AUDITAVEIS = CATEGORIAS_CRIAVEIS + [
    c for c in _SO_LEITURA if c not in CATEGORIAS_CRIAVEIS
]
