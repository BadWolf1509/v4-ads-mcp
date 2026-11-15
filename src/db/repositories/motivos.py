"""Motivos de revogação de acesso — módulo NEUTRO, sem import de repositório.

Vivem aqui (e não em `manager_account_access`/`manager_meta_account_access`)
porque o inventário (`google_ads_accounts`/`meta_ad_accounts`) precisa deles
nas filas de restauração e o acesso importa o inventário (`row_to_account`):
a constante num dos módulos de acesso obrigava o inventário a um import local
dentro da função, escondendo um ciclo. Os módulos de acesso reexportam os
nomes de hoje, então nenhum chamador muda.

São constantes — não string livre — porque `restore_for_account` filtra pelo
MESMO valor que `revoke*` grava: um typo faria o restore filtrar por um motivo
que nenhuma linha tem e devolver zero em silêncio, sem erro. O valor é o que
vai para `revoked_reason` no banco: mudar o texto muda o que o restore alcança.
"""

LEFT_MCC_REASON = "left_mcc"
ADMIN_REVOKED_REASON = "admin_revoked"
PARTNERSHIP_ENDED_REASON = "partnership_ended"
BULK_COPY_REPLACED_REASON = "bulk_copy_replaced"
# Gestor desativado (desenho de 15/11): grava `revogar_de_desativados`, e só
# `restaurar_de_reativados` devolve. Se, na reativação, a conta também está fora
# (MCC/parceria), o motivo vira o de churn do lado: o motivo nomeia o que bloqueia
# agora, e com dois bloqueios vale o da conta.
MANAGER_DEACTIVATED_REASON = "manager_deactivated"
