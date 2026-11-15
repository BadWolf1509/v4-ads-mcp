# Revogação de acesso na desativação do gestor (15/11): desenho curto

**Por quê.** Desativar um gestor hoje só troca `managers.is_active`. Ele fica barrado em toda
entrada (sessão MCP, painel e OAuth, pelo `Manager.is_deactivated` do F84), mas os grants Google e
Meta continuam vivos. Em 15/11 havia 2 gestores desativados com 24/24 e 24/23 grants vivos, e
reativar qualquer um devolve tudo no mesmo clique. Fazer offboarding completo depende de alguém
lembrar de desmarcar 50 caixas. É o 1º teste de gambiarra do `CLAUDE.md`, e o mesmo caso do F128.

**Padrão:** deprovisionamento JML (joiner-mover-leaver), com revogação soft e motivo, nos dois
caminhos que o projeto já usa para o inventário:
- a ação imediata, na rota;
- a reconciliação por estado, no job diário.

Os dois chamam a mesma função do repositório.

## Decisões do Wellington (15/11)

- Desativar revoga, de forma reversível e auditável.
- **Reativar devolve sozinho só o que a desativação tirou.** Revogação de admin e churn não voltam por esse caminho.
- **Abordagem C:** a rota faz o efeito na hora, e a reconciliação diária converge o que escapou:
  - desativação ou reativação por SQL direto (a coluna `status`);
  - falha no meio;
  - os 2 gestores que já estavam desativados, sem script avulso.

## Abordagens consideradas

| | o quê | troca |
|---|---|---|
| A | só na rota, na transação do `toggle-active` | imediato e com autor no audit; não cobre SQL direto e pede script avulso para os 2 de hoje |
| B | só um passo novo no job diário | cobre qualquer caminho; atrasa até 24 h e revoga longe de quem clicou |
| **C, escolhida** | A + B sobre a mesma função | imediato, com autor e convergente; custa um passo de job a mais |

## Objetivos, não-objetivos, anti-objetivos

- **Objetivo:**
  - nenhum grant vivo de gestor com `is_deactivated` depois da rota, ou no máximo até a próxima rodada do job;
  - reativação devolve exatamente os grants que a desativação revogou.
- **Não-objetivo:**
  - revogar as sessões MCP do gestor: o login já as barra;
  - mudar o gate;
  - mudar o que o gestor ativo vê;
  - UI nova: o botão é o mesmo, e o toast diz quantos acessos mudaram.
- **Anti-objetivo:**
  - apagar linha de grant;
  - reativação devolver acesso que um admin revogou à mão;
  - grant ficar revogado para sempre porque dois motivos se cruzaram (conta fora do MCC e gestor desativado ao mesmo tempo).

## Desenho

**1. Motivo novo.** `MANAGER_DEACTIVATED_REASON = "manager_deactivated"` em `src/db/repositories/motivos.py`.

**2. Predicado em SQL igual ao `Manager.is_deactivated`:** `is_active = false OR status = 'inactive'`. `invited` não conta como desativado. Fica numa constante só, e um teste amarra a constante à propriedade Python, os dois lados para os três `status` × `is_active`.

**3. Funções do repositório**, genéricas por `TabelaDeAcesso` em `_acesso_comum.py`, valendo para o Google e o Meta. Todas operam sobre o estado, não sobre o delta (lição do `revoke_for_inactive_accounts`). Todas devolvem as linhas atingidas.

- **`revogar_de_desativados(conn, t, manager_id=None)`**
  - Revoga os grants vivos de gestores desativados, com `manager_deactivated`.
  - Com `manager_id`, só daquele gestor (a rota); sem, todos (o job).
- **`restaurar_de_reativados(conn, t, manager_id=None)`**
  - Para gestores que não estão desativados, põe `revoked_at = NULL` nas linhas `manager_deactivated` cuja conta está ativa.
  - Nas linhas cuja conta está inativa, troca o motivo para o de churn da tabela (`left_mcc` / `partnership_ended`), ainda revogadas. Assim, a volta da conta as devolve.
- **Restaurações de churn** (`restore_for_account` no Google e a equivalente no Meta)
  - Passam a não devolver grant de gestor desativado.
  - Nesses casos, trocam o motivo para `manager_deactivated`, que continua revogado. A reativação o devolve.
  - **Regra:** o motivo sempre nomeia o que bloqueia agora. Com os dois bloqueios ao mesmo tempo, vale o da conta.

**4. Rota** `POST /admin/managers/{id}/toggle-active`. Na mesma transação de `definir_ativo` e do `_audit_admin`, quando `mudou`:
- ao desativar, chama `revogar_de_desativados` nas duas tabelas;
- ao reativar, chama `restaurar_de_reativados` nas duas tabelas.

O audit leva `params_summary` com as contagens por plataforma (`revogados_google`, `revogados_meta` / `restaurados_*`). O toast diz os números. Falha em qualquer passo desfaz tudo: é transação, não `best_effort`, porque nada externo foi feito.

**5. Job diário** `account_resync`, etapa nova `_etapa_gestores`:
- roda **depois** das etapas Google e Meta, para a convergência ver o estado final do dia;
- roda **antes** do purge;
- roda também no caminho `SEM_OAUTH`, porque não depende do Google.

A etapa chama as duas funções sem `manager_id`, nas duas tabelas, dentro de uma transação, e audita o plano e o resultado como as outras reconciliações (`operation="manager_offboarding_reconcile"`).

O lado destrutivo fica atrás da trava `manager_offboarding_apply: bool = False` em `Settings`, como `google_reconcile_apply` e `meta_reconcile_apply`. Desligada, o job calcula e audita quantos revogaria e restauraria, sem escrever. Assim, a primeira rodada mostra os 2 gestores de hoje (~95 grants) antes de alguém ligar a trava. Ligar é mudar a env do serviço, com aval nominal. Falha da etapa entra no exit code (F207).

## Fica com o executor

Nomes internos, formato do `params_summary`, texto do toast e a ordem dos testes.

**Testes exigidos** (full sweep, porque são query e transação):
- a matriz de motivos × estado da conta × estado do gestor;
- idempotência: rodar duas vezes não muda nada;
- uma revogação de admin não volta na reativação;
- conta fora do MCC com o gestor desativado, nas duas ordens de volta;
- predicado SQL igual ao Python;
- rota que falha no meio não deixa estado pela metade;
- etapa do job com a trava desligada não escreve.

**Pronto:** `tests/browser` mais um clique em produção, com aval nominal, num gestor de teste. A trava ligada depois da primeira rodada auditada.
