# Classificação de buckets — 2026-09-04

**Substitui** [`tool-buckets-2026-05-25.md`](tool-buckets-2026-05-25.md) (sprint 3b.39), que
ficou 3 ciclos vencido — a reclassificação era pra ser mensal.

| | |
|---|---|
| Fonte | `audit_log`, janela 2026-08-05 → 2026-09-04 (1671 linhas, 41 operations) |
| Tools com bucket | 68 (62 Google + 6 Meta) |
| Always-loaded | **22** (era 23) |
| Defer | **46** (era 45) |
| Movimento | 13 sobem, 14 descem |

## O que a medição mostrou

**A classificação de maio estava invertida nos dois sentidos.** Dez das 23 tools
always-loaded tiveram **zero** uso de gestor em 30 dias, enquanto as sete mais usadas da
conta inteira estavam todas em `defer` — inclusive a primeira colocada, com 474 chamadas e
dois gestores distintos.

Isso não é erro de quem classificou em maio: os números de maio eram reais. O uso é que
mudou, e a regra que eu tinha na cabeça — *"criação é deliberada, o gestor procura a tool"* —
continua errada como critério. O que decide é a medição, e ela vence a intuição.

### O controle que a medição precisou

Os últimos dois dias do log são **minha própria sessão** (F131–F147 e o sprint do
`ad_schedule`), não adoção. Sem separar, `run_gaql` apareceria com 582 chamadas em vez de
474, e `get_change_history` com 80 em vez de 14 — este último passaria de fria a quente
por causa do meu próprio uso investigando drift. A coluna que decide é a de **antes**.

### Duas armadilhas de nome que falseiam a contagem

1. **`audit_goal_attribution` grava duas operations** — `audit_goal_attribution_actions` e
   `audit_goal_attribution_goals`. Casar pelo nome exato da tool devolve zero. Uma primeira
   passagem minha reportou "11 de 23 zeradas" por isso; o número correto é **10**.
2. **`apply_change` grava sob o nome do mutate embrulhado**, nunca sob o próprio. Zero
   linhas no log não significa zero uso — significa que o log não o nomeia.

## Always-loaded (22)

Uso de gestor em 30 dias, já descontada minha sessão.

| Tool | Uso | Gestores | |
|---|---:|---:|---|
| `run_gaql` | 474 | 2 | ↑ promovida |
| `get_campaign_performance` | 166 | 3 | ↑ promovida |
| `get_conversion_actions` | 142 | 2 | mantida |
| `meta_get_campaign_performance` | 128 | 2 | mantida |
| `meta_get_ad_set_performance` | 101 | 1 | ↑ promovida |
| `meta_get_account_overview` | 80 | 2 | mantida |
| `validate_gaql` | 64 | 1 | ↑ promovida |
| `add_keywords` | 23 | 1 | ↑ promovida |
| `get_ad_group_performance` | 20 | 1 | ↑ promovida |
| `get_performance_breakdown` | 18 | 1 | mantida |
| `get_keyword_performance` | 18 | 2 | ↑ promovida |
| `get_change_history` | 14 | 1 | mantida |
| `meta_get_ad_performance` | 12 | 2 | ↑ promovida |
| `list_my_accounts` | 11 | 3 | mantida |
| `add_negative_keywords` | 10 | 1 | mantida |

As sete restantes entram por razão que **não é uso medido**, e cada uma tem que justificar
o assento:

| Tool | Por que fica sem número |
|---|---|
| `apply_change` | **Acoplamento.** É a segunda metade de todo mutate always-CONFIRM. Se a tool que emite o token está carregada e esta não está, o fluxo morre no meio, com pendência criada e sem como redimir. Não há medição possível: ela audita sob o nome do mutate. |
| `list_my_accounts` · `meta_list_my_ad_accounts` | **Porta de entrada.** Sem elas o gestor não descobre `customer_id` nem `act_<id>`, e nenhuma outra tool aceita ser chamada sem esse argumento. |
| `get_assets` · `remove_asset_link` | **Janela de descoberta** — shipadas em 02/09, dois dias antes desta medição. Zero uso aqui não é sinal, é falta de amostra. Reavaliar em 04/10. |
| `get_ad_schedule` · `update_ad_schedule` | **Janela de descoberta** — shipando agora (sprint 3b.42). Mesma cláusula. |
| `detect_drift` | **Decisão do Wellington (04/09), contra a medição.** Zero uso em 30 dias e a carência de 60 dias de maio já venceu. Fica porque é a tool do workflow de co-gestão: o D+1/D+2 pós-lote é justamente quando ninguém vai procurar uma tool que não está à vista. |

A janela de descoberta é a mesma cláusula que o doc de maio deu ao `detect_drift`. Ela tem
prazo: se em 04/10 essas quatro seguirem em zero, descem.

## Demovidas para defer (14)

| Tool | Uso | Era |
|---|---:|---|
| `audit_goal_attribution` | 6 | warm |
| `audit_competitor_keywords` | 4 | core (16 em maio) |
| `update_keyword_status` | 3 | warm |
| `create_conversion_action` | 1 | warm (8 em maio) |
| `update_ad_group_status` | 1 | warm |
| `audit_zombie_keywords` | 1 | warm |
| `apply_audience` · `audit_quality_score` · `bulk_pause_by_query` · `create_and_link_assets` · `create_campaign` · `get_recommendations` · `remove_audience` · `update_keyword_bid` | 0 | warm/core |

`create_and_link_assets` era a **segunda mais usada da conta** em maio, com 22 chamadas.
Hoje tem zero. É o argumento mais forte pra cadência mensal: nenhuma classificação
sobrevive a um trimestre sem remedição.

Descer para `defer` não some com a tool — ela continua no catálogo e o cliente a carrega
por busca. O que muda é o custo de contexto no handshake.

## O guard que passou a existir

`bucket` e o prefixo `[CORE]`/`[DEFER]` da descrição são a **mesma afirmação dita em dois
lugares**: o kwarg decide o `anthropic/alwaysLoad` do handshake, o prefixo é o que o modelo
lê. Reclassificar mexendo só no kwarg deixa a descrição mentindo, e nada quebra — servidor
sobe, testes passam, e a tool se anuncia como o oposto do que é.

`test_prefixo_da_descricao_concorda_com_o_bucket`, em
[`tests/unit/test_registry_bucket.py`](../../tests/unit/test_registry_bucket.py), afirma a
propriedade sobre **toda** tool registrada, não sobre uma lista — tool nova nasce coberta.
Verificado por sabotagem: com o prefixo do `run_gaql` invertido em memória, o guard reprova.

## Próxima reclassificação

**2026-10-04.** A query que produz a tabela precisa da coluna de controle (separar a janela
de quem está mexendo no repo) e do match por prefixo de operation. Sem as duas, os números
saem errados nas duas direções, como saíram aqui na primeira passagem.
