> **Relatório bruto** de um dos 5 agentes da varredura de 21/09 — recorte: ausência que é filtro — o que as respostas omitem.
> Recuperado do transcript da sessão em 25/09 e reproduzido **sem edição**. Os status
> ("CONFIRMADO", "PLAUSÍVEL") são do agente, não verificação nossa; o destino de cada
> achado está no [índice](README.md).

---

## População medida antes de procurar

Enumerado via `from src.mcp.tools._registry import all_tools, import_all_tools` (nunca grep — F183):

- **68 tools registradas** (62 Google + 6 Meta), 68/68 handlers parseados por AST para extrair as chaves do dict de retorno. Piso de não-vacuidade: o script aborta se `analisadas != len(ts)`.
- **38 tools de leitura**; ~34 devolvem coleção.
- **27 tools com parâmetro de corte** (`limit`/`top_n`).
- **6 tools com parâmetro `status` enum — todas com `default='enabled'`.**
- **55 cláusulas `WHERE`** varridas nos 19 arquivos de `src/google_ads/queries/`.
- Três scans com `assert casou &gt; 0` (status, limit, contagem de tools). Todos casaram.

**O que já está certo e não é achado:** `truncated` tem cobertura quase total (30 sites, via o primitivo `aplicar_limite` em `src/mcp/tools/_common.py:4`, cujo docstring já nomeia o defeito de "detector que morre calado"). `get_change_history` carrega `freshness` (F131 — a entrada do catálogo diz textualmente "sem isto, `total_changes: 0` e a mesma resposta para 'nada mudou' e para 'mudou e ainda nao indexou'"). `detect_drift` carrega `cobertura` + `freshness`. `get_ad_schedule` tem `schedule_desconhecida_por_truncamento` (F147). `get_assets` tem `orphan_scope`. O gate de acesso por conta **levanta exceção**, não devolve vazio (`src/google_ads/reports.py:65-74`). A família está reconhecida no repo — os achados abaixo são onde ela não foi aplicada.

---

## Achados, ranqueados por impacto

### 1. `filters_applied` que omite justamente os filtros que cortam — **CONFIRMADO**

`D:\v4-ads-mcp\src\mcp\tools\audit_quality_score.py:153-157` declara:

```python
"filters_applied": {
    "ad_group_ids": ad_group_ids,
    "min_impressions": min_impressions,
    "limit": limit,
},
```

Os três são os filtros que **o chamador passou**. Os dois que de fato estreitam estão em `D:\v4-ads-mcp\src\google_ads\queries\audit_quality_score.py:38-40`, e o próprio docstring (linhas 17-19) os chama de *"Hardcoded filters"*:

```
WHERE ad_group_criterion.status = 'ENABLED'
  AND segments.date BETWEEN ...
  AND ad_group_criterion.quality_info.quality_score IS NOT NULL
```

`quality_score IS NOT NULL` remove **exatamente a população que a tool existe para achar**. A flag principal é `candidate_pause (QS&lt;=2 + impressions&gt;=threshold + clicks=0 = waste)`; o Google não atribui QS a keyword sem volume suficiente — a keyword com 500 impressões, 0 clique e QS nulo é o caso-arquétipo de desperdício e é descartada server-side antes de qualquer flag rodar. O gestor lê `total_flagged: 3` e conclui "só 3 keywords problemáticas".

Um campo chamado `filters_applied` que lista três filtros e esconde dois é pior que campo nenhum: ele **afirma** ao leitor que aquela é a lista.

Prova de que o repo já sabia: a description de outra tool documenta o filtro — `D:\v4-ads-mcp\src\mcp\tools\get_keyword_performance.py:131-133` diz *"`audit_quality_score` também não devolve negativa, mas por outro mecanismo: exige `quality_score IS NOT NULL`"*. O conhecimento existe, só não chegou na resposta da tool dona do filtro.

---

### 2. As 6 tools com `status` default `'enabled'` não ecoam o filtro — **CONFIRMADO**

| tool | onde lê o default | return dict |
|---|---|---|
| `get_campaign_performance` | `:107` | `:121-126` |
| `get_ad_group_performance` | `:105` | `:119-123` |
| `get_ad_performance` | `:116` | `:130-134` |
| `get_keyword_performance` | `:148` | `:169-175` |
| `get_performance_breakdown` | `:152` | `:257-264` |
| `get_ad_schedule` | `:184` | `:289-295` |

Todas devolvem `{customer_id, period, rows, truncated}` (ou equivalente) — **sem `status`**. O filtro vira `AND campaign.status = 'ENABLED'` em `D:\v4-ads-mcp\src\google_ads\queries\performance.py:9,24` e irmãos.

O gestor pergunta *"quanto gastei em campanhas no mês?"*. Uma campanha pausada ontem que queimou R$ 5k no mês **não aparece**, e a resposta ainda vem com `truncated: false` — um sinal verde que reforça "esta lista está completa". É o caso do "verde" descrito na memória `nao-medido-nao-e-zero`.

Agravante: o default é mais estreito que o do próprio Google Ads UI (que mostra tudo menos REMOVED), então o modelo mental do gestor discorda do da tool sem aviso.

**O contraste que fecha o argumento:** o irmão Meta faz o oposto. `D:\v4-ads-mcp\src\mcp\tools\meta_get_campaign_performance.py:21-26` declara na description: *"[Limitação] Retorna campanhas de QUALQUER status ... e o status NÃO vem na resposta ... Campanha pausada com gasto no período APARECE aqui."* Duas tools irmãs, mesma pergunta, tratamento oposto — e só a Meta declara.

---

### 3. `get_top_keywords_creatives` filtra `ENABLED` e não declara em lugar nenhum — **CONFIRMADO**

`D:\v4-ads-mcp\src\google_ads\queries\client_report.py:81` e `:101` fixam `AND ad_group_criterion.status = 'ENABLED'` / `AND ad_group_ad.status = 'ENABLED'`.

O retorno (`D:\v4-ads-mcp\src\mcp\tools\get_top_keywords_creatives.py:147-153`) ecoa `metric` e `period`, **não** o status. A description (`:106-110`) também não menciona — diz só *"Top N palavras-chave + top N anuncios ... Util pra relatorio cliente — secao de destaques"*.

Pior que #2 por três motivos: (a) é **relatório que vai pro cliente**; (b) o filtro contradiz o propósito — um relatório *sobre o período* deveria incluir o que rodou *no* período, e a keyword pausada na semana passada foi possivelmente a maior gastadora; (c) diferente de #2, aqui não há sequer parâmetro `status` para o gestor perceber que existe um eixo de filtragem.

---

### 4. Meta: `purchases`/`leads`/`purchase_roas` viram `0` quando o campo não vem — **CONFIRMADO no código, magnitude PLAUSÍVEL**

`D:\v4-ads-mcp\src\meta_ads\insights.py:134-144`:

```python
def _extract_action_value(actions, action_type) -&gt; float:
    """Extract value of FIRST action matching action_type. 0 if absent."""
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == action_type:   # igualdade EXATA
            ...
    return 0.0
```

Consumido em `:184-187` com os tipos **nus** `"purchase"` e `"lead"`. A Meta entrega os eventos sob nomes qualificados (`offsite_conversion.fb_pixel_lead`, `onsite_conversion.lead_grouped`, `omni_purchase`, `offsite_conversion.fb_pixel_purchase`). Quando o nome não é o nu, a função devolve `0.0` — indistinguível de "a Meta mediu e deu zero".

**A assimetria interna é a evidência:** `_extract_purchase_roas` (`:147-154`) pega `roas_list[0]` **sem checar `action_type`**, e o próprio docstring exemplifica com `'action_type':'omni_purchase'`. Ou seja: a mesma linha pode sair com `purchase_roas: 4.45` e `purchases: 0` — autocontraditória.

Isso contraria a lição que o F89 deixou escrita duas linhas acima, em `:174-175`: *"Campo constante é pior que campo ausente pra consumidor LLM: ele relata como se fosse dado."*

**Probe que decide** (não executei — mutate/produção fora do meu escopo): chamar a Graph API `/act_&lt;id&gt;/insights?fields=actions,action_values,purchase_roas&amp;level=campaign&amp;date_preset=last_30d` numa conta V4 com lead-gen ativo, e **listar os `action_type` distintos** retornados. Controle positivo: uma conta que sabidamente gerou leads no período. Se nenhum `action_type` for exatamente `"lead"`, o campo `leads` está saindo zero em 100% das linhas dessa conta.

---

### 5. Zero fabricado em agregados — o `if not rows` que escolheu zeros — **CONFIRMADO**

`D:\v4-ads-mcp\src\mcp\tools\get_account_overview.py:68-79` tem um branch **explícito** para lista vazia e escolhe emitir o dicionário completo de zeros, sem marcador nenhum:

```python
if not rows:
    return {"impressions": 0, ..., "cost_per_conversion_brl": 0.0, "roas": 0.0}
```

Há um branch dedicado ao caso "não medi" e ele produz saída idêntica a "medi e deu zero". É a forma mais literal do defeito no repo.

O sub-caso mais grave **inverte o sinal**, e não só cala: `:93` — `"cost_per_conversion_brl": micros_to_currency(cost / conv) if conv else 0.0`. Com `cost = 5000` e `conv = 0`, o CPA sai **R$ 0,00** — o melhor CPA possível — quando a verdade é "gastou R$ 5.000 e não converteu" (CPA indefinido/infinito). Mesmo defeito em `D:\v4-ads-mcp\src\mcp\tools\get_funnel_metrics.py:85`, dentro do bloco `totals` que um LLM sumarizador cita como veredito.

Atenuante honesto: os denominadores (`conversions`, `impressions`, `cost_brl`) estão no **mesmo dict**, então um leitor atento desambigua. Por isso ranqueei abaixo de #1-#4 e por isso **não** listo as 24 ocorrências de `ctr/cpc ... else 0.0` nos row formatters — ali o denominador está na mesma linha e o risco é baixo. O que sobe o caso do CPA é a inversão de sinal, não a mudez.

---

### 6. `bulk_pause_by_query` nunca diz sobre qual janela mediu — **CONFIRMADO**

`D:\v4-ads-mcp\src\mcp\tools\bulk_pause_by_query.py:222-227` resolve `start`/`end` (default `LAST_30_DAYS`, auto-injetado em `segments.date` quando o filtro usa `metrics.*`). Esse par entra na query em `:230-235` e **não aparece em nenhum envelope de saída**:

- branch zero (`:261-268`): `{"status":"no_op", "matched_count": 0, "message": "Nenhuma entidade matched o filtro. Nada a pausar."}` — atribui ao filtro, mas não diz qual janela;
- branch preview (`:315-326`): `preview={target_type, matched_count, total_cost_brl, sample}`; e o `summary` em `:298-301` diz literalmente *"Custo total R$ {x} no periodo"* — **um valor monetário cujo escopo não está em lugar nenhum da resposta**.

Cenário: gestor pede *"pause keywords sem conversão"*, o modelo monta `filter="metrics.conversions = 0"`, a tool injeta LAST_30_DAYS, e volta `matched_count: 0`. Lê-se "não há keyword sem conversão". A verdade pode ser "nos últimos 30 dias todas converteram ao menos uma vez". Todas as outras ~30 tools de leitura ecoam `period: {from,to}`; esta, que é a de **blast radius alto**, não.

Parente direto do F133 ("custo lido como veredito sem a conversão ao lado") — aqui é custo sem a **janela** ao lado.

---

### 7. `get_budget_pacing`: `ENABLED` fixo, sem parâmetro, sem eco, e o `status` some da linha — **CONFIRMADO**

`D:\v4-ads-mcp\src\google_ads\queries\overview.py:44` fixa `WHERE campaign.status = 'ENABLED'`. A query **seleciona** `campaign.status` (`:39`), mas o formatter (`D:\v4-ads-mcp\src\mcp\tools\get_budget_pacing.py:37-44`) não o inclui na linha, e o retorno (`:129-134`) não ecoa o filtro.

O dado para declarar já vem do Google e é descartado no caminho. O gestor lê o `spent_mtd_brl` somado e não tem como saber que campanha pausada no meio do mês (com gasto real) está fora. Atenuante: a description diz *"Por campanha ativa"*. Mas a description não vai junto quando o modelo resume a resposta.

---

### 8. `audit_zombie_keywords.filters_applied` — mesma classe do #1 — **CONFIRMADO**

`D:\v4-ads-mcp\src\mcp\tools\audit_zombie_keywords.py:134-137` declara `{ad_group_ids, limit}`; `D:\v4-ads-mcp\src\google_ads\queries\audit_zombie_keywords.py:53-54` fixa `status = 'ENABLED'` e `negative = FALSE`. Impacto menor que o #1 porque ambos são defensáveis para "zumbi" (você pausa o que está ativo), mas o campo segue prometendo uma lista completa de filtros e entregando metade.

---

### 9. `get_negative_keywords_audit.total_negatives` sem declaração de escopo — **CONFIRMADO**

`D:\v4-ads-mcp\src\google_ads\queries\tactical.py:80` varre só `campaign_criterion` — **negativas de ad_group e listas negativas compartilhadas (`shared_set`) ficam fora**. O retorno (`D:\v4-ads-mcp\src\mcp\tools\get_negative_keywords_audit.py:203-211`) traz `total_negatives`, `returned_count`, `truncated`, `limit` — e nenhum campo de escopo.

O gestor pergunta *"esse termo já está negativado?"*, a auditoria não acha, ele adiciona duplicata — ou conclui que há gap de cobertura que não existe. A description menciona "nivel de campanha"; a resposta, que é o que sobrevive ao resumo, não.

Este é o caso que mais pede o tratamento do `get_assets.orphan_scope`: um `escopo: "apenas_nivel_campanha"` fecharia.

Nota positiva no mesmo arquivo: `_compute_summary` (`:101-105`) nomeia o bucket `pre_30_days_or_unknown` em vez de fingir que sabe — isso é o padrão certo, aplicado.

---

### 10. `meta_list_my_ad_accounts`: conta desativada pelo reconciliador some sem rastro — **CONFIRMADO**

`D:\v4-ads-mcp\src\db\repositories\manager_meta_account_access.py:170-183` filtra `a.is_active = true AND m.revoked_at IS NULL`. O handler (`D:\v4-ads-mcp\src\mcp\tools\meta_list_my_ad_accounts.py:37-54`) projeta 8 campos e **descarta três que o dataclass já carrega** (`D:\v4-ads-mcp\src\db\repositories\meta_ad_accounts.py:27,33,38`): `synced_at`, `missed_syncs`, `su_reachable`.

`is_active` vira `false` depois de 3 resyncs sem ver a conta (F128). A conta desaparece da lista e `total` decresce — o gestor lê "essa conta não é mais minha". A causa real pode ser cache velho ou alcance do system user, não churn: o próprio comentário em `:34-38` avisa que *"conta pode estar na lista autoritativa e mesmo assim ficar fora do alcance do SU"* (é o F154 aberto). Nenhum dos três sinais chega à resposta, e `synced_at` responderia sozinho "quando foi a última vez que isto foi medido".

O gêmeo Google (`D:\v4-ads-mcp\src\mcp\tools\list_my_accounts.py:42-52`) tem a mesma forma, com o agravante de a revogação ser *soft* — `revoked_at`/`revoked_reason` existem na tabela e não são contados em lugar nenhum da resposta.

---

### 11. `country_name: null` em breakdown geo — **CONFIRMADO, baixo**

`D:\v4-ads-mcp\src\mcp\tools\get_performance_breakdown.py:252-255`: quando `lookup_country_names` não resolve o id, grava `None`. O docstring de `D:\v4-ads-mcp\src\google_ads\reports.py:206` diz explicitamente *"IDs not returned by Google are absent from the result; callers decide the fallback"* — e o caller escolheu `null` mudo. Baixo impacto (o `country_criterion_id` continua na linha), mas é literalmente a decisão de fallback deixada em branco.

---

### 12. Não existe modelo de freshness para **métricas** — **PLAUSÍVEL**

`assess_freshness` (`src/google_ads/change_freshness.py`) é usado em exatamente um lugar: `get_change_history` (e consumido por `detect_drift`). Nenhuma tool de métrica tem equivalente, embora várias descriptions avisem em prosa que *"cost data Google pode lagar entre queries"*. Consequência: `date_range="TODAY"` em `get_account_overview` devolve números baixos indistinguíveis de "conta parada", e conversão com lag de atribuição entra dias depois sem nenhum marcador.

**Probe que decide:** rodar `get_account_overview(customer_id=X, date_range="YESTERDAY")` duas vezes, com ~6h de intervalo, na mesma conta, e comparar `conversions` e `cost_brl`. Controle: a mesma dupla de leituras para `LAST_30_DAYS` excluindo os 3 últimos dias (janela que deveria estar estável). Se a primeira diverge e a segunda não, o lag é real e mensurável — e o padrão do F131 se aplica igual.

---

## O que eu NÃO examinei

Cobertura declarada, não implícita:

- **Corpos das 30 tools mutate.** Li o schema e a forma do retorno (AST) de todas as 68, e o corpo de `bulk_pause_by_query` inteiro. **Não** li o corpo de `apply_change`, `update_ad_schedule`, `apply_recommendation`, `import_offline_conversions`, `upload_customer_match_list`, nem dos `create_*`/`update_*`/`remove_*`. Em particular **não auditei a família partial-failure** (`classify_partial` em `_common.py:20`, `__partial_failure__`) — e ela tem um caso conhecido e **aberto** nessa exata família: **F180**, "o Google engole operação impossível em vez de errar, então `failed_count` é sempre zero". Não o reivindico como achado meu; sinalizo que é o vizinho não varrido.
- **`src/web/`** (painel, rotas admin, templates) — zero leitura. Se há contagem muda lá, não vi.
- **Testes** (`tests/`) — não li nenhum. Não sei quais dos achados acima já têm guard.
- **`src/meta_ads/reconcile.py`, `partnership.py`, `graph.py`** — li só `insights.py` e os trechos de `reports.py` citados por terceiros. A lógica de paginação pós-F189 eu li só via `_meta_performance.py:31-41`.
- **`meta_get_account_overview` e `meta_get_performance_breakdown`** — não abri os corpos; herdam `meta_account_not_found_error` e provavelmente o parser de #4, mas não confirmei.
- **`get_device_performance`, `get_hourly_performance`, `get_geo_performance`, `get_audience_performance`, `get_my_audit_log`, `audit_orphan_smart_actions`, `audit_goal_attribution`, `run_gaql`, `list_gaql_resources`, `get_my_rate_limit_status`** — examinei schema, chaves de retorno e a cláusula `WHERE` do builder de cada um, e **não achei filtro não declarado**. Não li os corpos linha a linha. `get_audience_performance` e `get_geo_performance` confirmadamente não têm filtro de status hardcoded (`tactical.py:107-122`).
- **Nenhuma chamada a produção.** Os itens #4 e #12 dependem de probe ao vivo para dimensionar; descrevi as duas com controle e deixei a execução para quem me despachou.
- **Um caso que investiguei e descartei:** `get_ad_schedule` com `status='enabled'` parecia produzir `has_schedule: false` falso-negativo. Não é defeito — critério de ad_schedule pausado realmente não restringe entrega, então filtrar para ENABLED é semanticamente correto ao computar a grade efetiva. Registro porque o método pede verificar antes de afirmar, e este teria virado achado inventado.
