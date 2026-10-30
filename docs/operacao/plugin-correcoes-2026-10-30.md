# Correções do plugin `v4-trafego-google-ads` — varredura de 30/10

O plugin **não tem fonte no disco**: só a cópia instalada (upload do app, 0.5.0, em
`~/.claude/plugins/marketplaces/local-desktop-app-uploads/v4-trafego-google-ads/`). As correções
abaixo são para o Wellington aplicar **na fonte** e subir uma 0.5.1. Cada item traz o arquivo da
cópia instalada, o que está escrito e o que o servidor faz hoje (conferido no código de 30/10).

| # | Arquivo (cópia 0.5.0) | Hoje diz | Correto |
|---|---|---|---|
| 1 | `skills/analise-performance-google-ads/references/queries-v4-ads.md:152-166` | demografia por `FROM age_view` | o resource do Google é **`age_range_view`** (`gender_view` está certo). `age_view` não existe e a query volta com erro |
| 2 | mesmo arquivo, Q15 (linhas 317-336) e `skills/auditoria-google-ads/references/change-history-patterns.md:11-18` | "Não há tool dedicada — usar GAQL no resource `change_event`" | **há duas tools**: `get_change_history` e `detect_drift`. A nota certa já está na seção 3 do mesmo arquivo (linhas 19-27); Q15 e o `change-history-patterns.md` a contradizem. Manter o GAQL só como complemento |
| 3 | `shared/v4-brand.md:134` (pegadinha 3) | "Sem tool dedicada para change_event. Usar `run_gaql`…" | retirar a frase; apontar `get_change_history` / `detect_drift`. **Retirar também "change_event resource"** da lista de casos de `run_gaql` em `shared/v4-brand.md:122` |
| 4 | todo `date_range` de exemplo que apareça como objeto (`{start, end}`) na fonte — **não achei na cópia 0.5.0**, conferir na fonte | objeto | `date_range` é **preset** (`LAST_30_DAYS`…) **ou** o par `start_date` + `end_date` (`YYYY-MM-DD`, os dois). Nunca um objeto. `get_change_history(customer_id, date_range, ...)` em `queries-v4-ads.md:21` vale para o preset; para período custom escrever `start_date`/`end_date` |
| 5 | `queries-v4-ads.md:305-313` (Q14, budget pacing) | chaves `orcamento_diario`, `gasto_mtd`, `projecao_fim_de_mes`, `percent_consumido` | chaves reais por campanha: `daily_budget_brl`, `spent_mtd_brl`, `gasto_hoje_brl`, `spent_pct_of_monthly_budget`, `days_elapsed`, `days_remaining`, `projected_monthly_brl`, `projection_vs_budget_pct`, `delivery_method`, `orcamento_compartilhado`. Em orçamento compartilhado **`spent_pct_of_monthly_budget` e `projection_vs_budget_pct` vêm `null`**; o ritmo está em `orcamentos_compartilhados`. Projeção `null` com `inclui_dia_corrente: true` (F199) |
| 6 | `queries-v4-ads.md:276-282` (recomendações) | `get_recommendations` devolve "pending recommendations (com `dismissed: true\|false`)" | **não existe campo `dismissed`**: a resposta traz `count`, `truncated` e `recommendations[]` com `resource_name`, `type`, `type_pt`. `dismiss_recommendation` **auto-aplica** (sem CONFIRM) e, desde o #176, **recusa** `recommendation_resource_name` que não comece por `customers/<customer_id>/`; `apply_recommendation` recusa o mesmo (#184). Passe sempre o `resource_name` devolvido pela própria conta |
| 7 | `shared/v4-brand.md:125` e `queries-v4-ads.md:48,112,344` | `validate_gaql` "valida sintaxe **sem consumir quota**" / "evita gastar quota" | **consome 1 operação da quota diária da API** (`validate_only` conta no Google; a description da tool foi corrigida no #184). Continua valendo validar antes de rodar, mas não como "de graça" |
| 8 | `shared/v4-brand.md:42` na cópia 0.5.0 (o `estado-atual` citava `:43`) | o item de KPIs já manda `null` virar "—" com nota | **único ponto que resta do `null`**: acrescentar que **variação com `null` de qualquer lado = "sem base de comparação"** (já escrito em `analise-performance-google-ads/SKILL.md:45,146`). Os outros cinco pontos foram tratados no 0.5.0 |
| 9 | `shared/v4-brand.md`, lista de mutações (≈117) | nada sobre confirmação em `update_conversion_action` | **`primary_for_goal` agora exige confirmação** (CONFIRM) em `update_conversion_action`, qualquer valor. O gestor deve esperar o passo extra |

## Como conferir depois de aplicar

- `grep -rn "age_view\|sem consumir quota\|Não há tool dedicada\|Sem tool dedicada\|dismissed" .` na fonte: nenhum
  resultado fora de `age_range_view`.
- `grep -rn "orcamento_diario\|gasto_mtd\|projecao_fim_de_mes\|percent_consumido" .`: nenhum.
- Rodar uma análise e um relatório num cliente com orçamento compartilhado: o pacing não imprime `None`.

⚠️ O item 4 é o único que não achei na cópia instalada; foi pedido na varredura e fica marcado para
conferência na fonte, não como correção confirmada.
