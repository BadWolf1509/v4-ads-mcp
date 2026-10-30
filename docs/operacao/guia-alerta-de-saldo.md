# Guia do gestor — alerta de saldo acabando

**Decisão de 30/10:** não há job central de alerta. **Cada gestor monta a própria automação** sobre as
tools de saldo, para as contas que administra. Este guia traz o que as tools respondem e um pedido pronto
para colar numa tarefa agendada do Claude.

## O que as tools respondem

| Tool | Conta | O que mede |
|---|---|---|
| `get_account_balance` | Google (`customer_id`, 10 dígitos) | Fundos disponíveis do orçamento de conta (o mesmo número da tela de Faturamento) e a data de fim, se houver |
| `meta_get_account_balance` | Meta (`act_…`) | Saldo pré-pago (lido do texto da Meta) e limite de gastos; `trava_primeiro` diz qual acaba antes |

O campo que importa é `situacao`:

| `situacao` | Significa | Avisar? |
|---|---|---|
| `esgotada` | Sem saldo, menos de um dia de gasto ou orçamento encerrado | **Sim, urgente** |
| `acabando` | Até 7 dias no ritmo dos últimos 7 dias | **Sim** |
| `com_saldo` | Mais de 7 dias | Não |
| `sem_gasto` | Há saldo, mas a conta não gastou nos últimos 7 dias (pausada?) | Opcional |
| `sem_teto` | Sem limite (Google) ou pós-paga sem limite de gastos (Meta): não para por saldo | Não — mas leia `avisos` |
| `indeterminada` | Não deu para calcular (`motivo` explica: sem permissão de faturamento, texto da Meta ilegível…) | **Sim, para conferir à mão** |

Leia também `avisos`: na Meta, **pagamento pendente** ou conta desativada para os anúncios mesmo com
`sem_teto`. Os valores são aproximados (`aproximado: true`): o gasto do Google e da Meta atrasa algumas
horas.

## Pedido pronto para a tarefa agendada

Crie uma tarefa agendada no Claude (diária, de manhã, antes do horário de pico das campanhas) com o MCP
`v4-ads` conectado, e cole:

> Liste as minhas contas com `list_my_accounts` (Google) e `meta_list_my_ad_accounts` (Meta). Para cada
> conta, chame `get_account_balance` ou `meta_get_account_balance`. Monte um aviso só com as contas cuja
> `situacao` seja `esgotada`, `acabando` ou `indeterminada`, ou que tenham algo em `avisos`. Para cada
> uma, diga: nome da conta, plataforma, situação, `restante_brl`, `dias_restantes`, `trava_primeiro`
> e o `motivo` ou o aviso. Ordene por urgência (esgotada, indeterminada, acabando). Se nenhuma conta
> precisar de atenção, responda só "Saldo ok em todas as contas". Não altere nada nas contas.

Para limitar às contas de um cliente, troque a primeira frase pela lista de contas.

## Custo

Cada conta Google gasta 2 operações da cota diária (orçamento e gasto), e cada conta Meta, 2 chamadas.
Uma varredura diária de 20 contas fica muito abaixo do teto por gestor (5.000 operações/dia).
