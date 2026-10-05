# Classificação de buckets — 2026-10-05

**Substitui** [`tool-buckets-2026-09-04.md`](tool-buckets-2026-09-04.md), que fica como referência
do método: as armadilhas de nome, o controle da sessão de desenvolvimento e o guard
bucket × prefixo continuam valendo.

| | |
|---|---|
| Fonte | `audit_log`, janela 2026-09-05 → 2026-10-05, só `read`/`mutate` (transação READ ONLY) |
| Script | `.superpowers/verificacao-2026-10-05/remedicao.py` (git-ignored; saída em `remedicao.json`) |
| Tools com bucket | 68 (62 Google + 6 Meta) |
| Always-loaded | **13** (era 22) |
| Defer | **55** (era 46) |
| Movimento | 0 sobem, 9 descem |

## O critério

O que decide é o uso de **gestor**, sem contar o do Wellington. O uso dele mistura
desenvolvimento e gestão de verdade, e o log não separa os dois. Uma tool que só ele usa
pode ser carregada por busca. Ele aprovou a regra em 05/10.

## Always-loaded (13)

| Tool | Uso de gestor | Gestores |
|---|---:|---:|
| `run_gaql` | 259 | 1 (Pedro) |
| `meta_get_account_overview` | 145 | 3 |
| `get_campaign_performance` | 120 | 2 |
| `meta_get_campaign_performance` | 103 | 3 |
| `get_conversion_actions` | 95 | 1 |
| `get_keyword_performance` | 70 | 1 |
| `meta_get_ad_set_performance` | 70 | 2 |
| `meta_get_ad_performance` | 11 | 2 |
| `list_my_accounts` | 8 | 3 |
| `get_performance_breakdown` | 1 | 1 |

Ficam sem número, pelos motivos de 04/09: `apply_change` (acoplamento com todo mutate
always-CONFIRM), `meta_list_my_ad_accounts` (porta de entrada) e `detect_drift` (decisão do
Wellington). O `get_performance_breakdown` fica por ser o destino da Fase 2B, não pelo uso.

## Demovidas para defer (9) — zero uso de gestor em 30 dias

| Tool | Por quê |
|---|---|
| `get_assets` · `remove_asset_link` · `get_ad_schedule` · `update_ad_schedule` | A janela de descoberta de 04/09 venceu em 04/10 com zero uso de gestor. O doc anterior mandava descê-las nesse caso. |
| `validate_gaql` | 64 chamadas do Pedro em agosto; zero agora. As 143 do período são do Wellington. |
| `get_change_history` · `get_ad_group_performance` · `add_keywords` · `add_negative_keywords` | Zero uso de gestor. |

Nenhuma defer tem uso que justifique subir: a maior é o `meta_get_performance_breakdown`, com
3 chamadas do Lucas.

## Fase 2B — segue travada (decisão de 05/10)

O `get_campaign_performance` teve 120 chamadas de gestor (Pedro 96, Anderson 24) e o
`get_keyword_performance` 70 (Pedro). O `get_performance_breakdown` teve 1. Os outros seis
reports antigos ficaram em zero. As descriptions mandam preferir o breakdown, e mesmo assim os
gestores seguem nos reports antigos.

Decisão: **esperar o plugin 0.5.0**, aplicado em 05/10, e remedir em 1–2 semanas. A alternativa
considerada foi descer os dois reports antigos para defer, o que seria reversível e mensurável,
mas contrariaria a regra do uso medido. Ela fica para a próxima remedição, se nada mudar.

Desde 03/10 não houve chamada de gestor (fim de semana): o efeito do plugin ainda não aparece.
