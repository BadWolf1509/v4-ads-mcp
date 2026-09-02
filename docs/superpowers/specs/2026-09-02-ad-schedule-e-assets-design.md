# Spec — `ad_schedule`, leitura de assets e unlink de asset

**Data:** 2026-09-02 · **Origem:** gaps de campo trazidos pela sessão de gestão de tráfego da MO João Pessoa (`jo-o-pessoa-db`), conta `786-223-0676` · **Findings relacionados:** F133 (custo sem conversão), F134/F135 (camada `customer_asset` invisível) · **Status:** aguardando revisão do Wellington antes de virar plano.

---

## 1. O que originou, e o que mudou no caminho

Três das cinco limitações trazidas do campo são ausência de tool, não defeito — por isso ficaram fora da numeração do catálogo e vêm para cá. Duas coisas mudaram entre o relato e esta spec, e as duas mudam o desenho:

1. **O caso que motivava o `ad_schedule` está invertido.** O pedido nasceu de "as lojas fecham fim de semana e as campanhas gastam 16,6% do orçamento nesses dias". Medido em janela madura (19/08–01/09) e reproduzido de forma independente: o fim de semana tem **CPA R$ 18,59 contra R$ 23,59** de seg–sex, e domingo (R$ 14,14) é o melhor dia da conta. A premissa de negócio segue verdadeira; caiu a inferência de que gasto com loja fechada é desperdício. **A tool continua justificada — o corte específico é que virou outra coisa.**
2. **A métrica que o dry-run ia mostrar era a errada.** O pedido original era "% de custo histórico das janelas cortadas". Custo sozinho foi exatamente o número que quase transformou o melhor CPA da conta em corte. É o **F133 no eixo do tempo**, dentro de um desenho nosso — e é a razão de a regra de dry-run abaixo ser normativa, não sugestão.

**Por que a escrita entra (e não só leitura):** o canal alternativo é a UI, cujo save falhou em silêncio **duas vezes** nessa conta — orçamento compartilhado em 17/08 (aceito 7×, exibido na tabela, nada persistiu) e os callouts de 02/09 (duas tentativas; a primeira não persistiu e só apareceu por conferência via GAQL). Um `ad_schedule` que não persiste calado deixa a conta servindo fora de hora sem ninguém saber e ainda queima 14 dias de re-learning quando refeito. Escrita via MCP com confirmação de estado por GAQL é **mais** segura que a UI, não menos.

## 2. Escopo

| # | Tool | Tipo | Blast radius |
|---|---|---|---|
| 1 | `get_ad_schedule` | read | — |
| 2 | `update_ad_schedule` | mutate | **always-CONFIRM** (estrutural) |
| 3 | `get_assets` | read | — |
| 4 | `remove_asset_link` | mutate | **always-CONFIRM** (remove) |

**Fora de escopo, por decisão:**

- **Remover a entidade `Asset`.** O que serve na SERP é o vínculo; asset órfão é inerte. Remoção é irreversível numa entidade que pode estar linkada onde a varredura não alcançou, e o registro tem caso de "órfão" que era ativo vivo. Com órfãos visíveis no `get_assets`, o lixo fica auditável sem gesto destrutivo.
- **Geo targeting write.** O gap que dói é da plataforma (o Google Ads não exclui por raio) e a frequência é ~1×/mês.
- **`remove_keyword` / `remove_ad_group` / `remove_campaign`.** `PAUSED` resolve, e a fricção da UI é saudável para operação irreversível.

---

## 3. `get_ad_schedule` (read)

**Superfície verificada** (probe `validate_gaql`, 2026-09-02):

```
SELECT campaign.id, campaign.name, campaign_criterion.criterion_id,
       campaign_criterion.ad_schedule.day_of_week,
       campaign_criterion.ad_schedule.start_hour,
       campaign_criterion.ad_schedule.start_minute,
       campaign_criterion.ad_schedule.end_hour,
       campaign_criterion.ad_schedule.end_minute,
       campaign_criterion.bid_modifier, campaign_criterion.status
FROM campaign_criterion
WHERE campaign_criterion.type = 'AD_SCHEDULE'
```

Os campos de minuto foram probados junto (a primeira versão desta spec listava
`start_minute`/`end_minute` na saída sem tê-los na query verificada — corrigido
na auto-revisão).

**Schema:** `customer_id` (required), `campaign_ids[]` (opcional; default = conta inteira), `status` (default `enabled`).

**Saída:** uma linha por janela, com `campaign_id`, `campaign_name`, `criterion_id`, `day_of_week`, `start_hour`, `end_hour`, `start_minute`, `end_minute`, `bid_modifier`, `status`. Mais, por campanha, um bloco `schedule_summary`:

- `has_schedule: bool` — **campanha sem nenhum criterion de AD_SCHEDULE serve 24×7**. Essa distinção não pode ficar implícita numa lista vazia; é a mesma classe do F131 (vazio que quer dizer duas coisas).
- `hours_per_week` coberto.
- `budget_is_shared: bool`, lido de `campaign_budget.explicitly_shared` (probe válida; `true` nos dois orçamentos ENABLED da `786-223-0676`).

## 4. `update_ad_schedule` (mutate, always-CONFIRM)

### 4.1 A guarda central: é CONJUNTO, não incremento

O conjunto de criteria `AD_SCHEDULE` de uma campanha **define as janelas em que ela serve** — o que fica de fora para de servir. Semântica igual à do `update_rsa` ("substitui a lista inteira"). Quem adiciona "seg–sex 07–17" achando que soma a uma grade existente **desliga a campanha no resto da semana**.

**Consequência de desenho:** a tool recebe a **grade completa desejada**, nunca um delta. O executor calcula `add` e `remove` contra o estado atual. Esse formato é seguro sob qualquer leitura da semântica do Google e elimina a classe inteira de erro por mal-entendido.

```
update_ad_schedule(customer_id, campaign_ids[], windows[], bid_modifier?)
  windows[]: { day_of_week, start_hour, start_minute?, end_hour, end_minute? }
```

**Restrições da API, lidas do SDK v24 (`AdScheduleInfo`), não por analogia:**

- Campos existentes: `day_of_week`, `start_hour`, `end_hour`, `start_minute`, `end_minute`. Não há outro.
- `MinuteOfHour` aceita **apenas** `ZERO | FIFTEEN | THIRTY | FORTY_FIVE`. **Não é possível agendar 07:10** — o schema deve recusar isso na entrada, com mensagem clara, em vez de deixar o Google recusar depois.
- `DayOfWeek`: `MONDAY`…`SUNDAY`.

### 4.2 O dry-run — regra normativa, não sugestão

O preview **DEVE** mostrar, para as janelas que **deixam de servir**: `cost_brl`, `conversions` e `CPA`. E **DEVE** mostrar o CPA das janelas que **permanecem**, lado a lado.

A pergunta que o preview tem de responder é *"o que estou desligando é melhor ou pior do que o que fica?"*. **Custo sozinho não responde** — foi ele que quase transformou CPA R$ 18,59 em corte. Mostrar só as janelas que entram ("o que eu adicionei?") em vez das que saem ("o que eu empurrei?") é o mesmo defeito com outra roupa.

**Fonte dos números:** `segments.day_of_week` + `segments.hour` sobre `campaign`, na janela que o gestor pedir (default 30 dias) — combinação probada válida em 2026-09-02. Marginais por dia já foram validadas; a conjunta dia × hora é levantada na implementação, com a janela madura.

### 4.3 Orçamento compartilhado: desligar não economiza, REALOCA

Quando `campaign_budget.explicitly_shared` é `true`, a verba de uma janela desligada **volta no mesmo dia** pelas janelas que seguem servindo. O efeito real do corte proposto na `786-223-0676` seria mover gasto de CPA R$ 18,59 para CPA R$ 23,59 — não é neutro, é negativo.

O dry-run **DEVE** ler `explicitly_shared` e declarar isso, em vez de deixar o operador supor economia. É barato: um campo, uma query.

### 4.4 Confirmação de estado

Pós-apply, reconsultar por GAQL e devolver a grade resultante. As duas falhas silenciosas da UI nessa conta são a razão de existir da tool; confiar no ACK da mutação repetiria o problema num canal novo.

---

## 5. `get_assets` (read)

**O que resolve:** a limpeza de 02/09 previa 4 vínculos em `campaign_asset` e eram **6** — os mesmos assets existiam também em `customer_asset`, **dormentes**, e só apareceram porque o gestor foi atrás por desconfiança no `run_gaql`. Vínculo dormente não serve, não aparece, e fica armado para ressurgir quando o de campanha for mexido.

```
get_assets(customer_id, field_type?, campaign_ids?, limit=200)
```

**Decisões:**

- **Todos os `field_type` por default**, com filtro opcional. Limitar à família text-extension que o `create_and_link_assets` cobre repetiria o erro do checklist: ele previu uma camada quando existiam duas.
- **`status` por linha, e sem filtrar status no default** — pelo motivo da §7.
- **As três camadas juntas**: `customer_asset` + `campaign_asset` + `ad_group_asset`, cada linha marcando seu `level`.
- **Órfãos marcados**: asset sem nenhum vínculo. Dá inventário sem precisar de tool destrutiva.

### 5.1 ⚠️ Questão aberta que BLOQUEIA o campo `effective`

A tool deve devolver precedência **calculada** (`effective: bool`, `shadowed_by: level|null`) e não três listas cruas — a tool que conhece a regra deve aplicá-la; três listas devolvem ao gestor o mesmo problema com mais passos, e foi não saber a regra de cabeça que quase deixou a limpeza pela metade.

**Mas a regra não está confirmada.** Consulta aos docs oficiais (via context7, 2026-09-02) devolve a estrutura de vínculo e os limites por tipo, e **não enuncia a precedência entre níveis**. A crença de campo é "o mais específico vence" (ad group > campanha > conta). Codificar isso por analogia é exatamente o `Don't do` do CLAUDE.md — e um `effective` errado é pior que nenhum, porque o gestor age sobre ele.

**Probe desenhada (executável — verifiquei que as duas resources aceitam métricas):**

1. Achar um `field_type` com vínculo simultâneo em `customer_asset` e `campaign_asset` para a mesma campanha. A `786-223-0676` tinha exatamente isso em CALLOUT antes da limpeza de 02/09.
2. `SELECT ... metrics.impressions FROM campaign_asset` e `FROM customer_asset`, segmentado por data.
3. Se o vínculo de conta acumula **zero** impressões nas campanhas que têm vínculo próprio, e não-zero nas que não têm, a precedência "mais específico vence" está confirmada empiricamente.

**Enquanto a probe não rodar:** entregar as três camadas com `level` e `status`, **sem** `effective`/`shadowed_by`. Uma tool que só mostra as três camadas já teria evitado o erro de 02/09; o `effective` é a melhoria, e só entra confirmado.

---

## 6. `remove_asset_link` (mutate, always-CONFIRM)

Assimetria direta: `create_and_link_assets` existe, o inverso não — custou duas idas à UI. `remove_audience.py` é o formato precedente.

```
remove_asset_link(customer_id, links[])
  links[]: { level: CUSTOMER|CAMPAIGN|AD_GROUP, resource_name }
```

Remove o `*_asset`, **nunca** o `Asset`. Idempotente: vínculo já removido volta gracioso via partial failure, como o `remove_audience`.

---

## 7. 🔴 Restrição obrigatória do smoke: só a asserção por id + status é incondicional

Confirmar remoção **contando linhas não distingue os dois estados** — o vínculo removido continua na tabela com `status: REMOVED`. Medido na `786-223-0676` em 02/09, comparando o momento em que a remoção **falhou** com o momento em que **funcionou**:

| forma de checar | falha | sucesso | distingue? |
|---|---|---|---|
| `row_count` da query **não-filtrada** | 16 | **16** | ❌ nunca |
| `row_count` filtrado por `status = 'ENABLED'` | 16 | 12 | ⚠️ só com baseline conhecido |
| `status` consultado **por `asset.id` alvo** | `ENABLED` | `REMOVED` | ✅ sempre |

A linha do meio salvou a operação naquele dia, mas depende de saber o número esperado. A de cima é a armadilha. E nenhuma cobre **remoção parcial**: tirar 2 de 4 devolve 14, que passa por "mudou, deve ter dado certo".

**Portanto:** asserte `status == REMOVED` no registro alvo. Nunca `id not in lista_enabled`, nunca `row_count`. Query de referência: `FROM campaign_asset WHERE campaign_asset.field_type = '...' AND asset.id IN (...)`.

Isto vale para o smoke **e** para a confirmação de estado que a própria tool faz pós-apply.

## 8. Guards obrigatórios

1. **Minuto fora do quarto de hora é recusado no schema**, com mensagem citando os 4 valores válidos.
2. **`update_ad_schedule` recebe grade completa** — teste que uma chamada com uma única janela numa campanha que tinha cinco produz `remove` das outras quatro no preview. É a guarda do erro de conjunto-vs-incremento, e tem de falhar contra qualquer implementação que trate a entrada como delta.
3. **Dry-run sem `conversions` não passa** — teste que o preview de janelas removidas traz `cost_brl`, `conversions` e `cpa`. Deriva direto do F133; sem ele a regra da §4.2 é prosa.
4. **`explicitly_shared` chega ao preview** quando o orçamento é compartilhado.
5. **Confirmação por `status == REMOVED`**, jamais por ausência ou contagem (§7).
6. **`get_assets` não filtra status por default** — teste que uma linha `REMOVED` aparece sem filtro explícito.

Todo guard deve ser verificado **contra o código pré-fix ou por sabotagem**, nunca por ter passado de primeira. Esta sessão registrou 7 ocorrências da família *guard que passou sem cobrir*, uma delas em cima do próprio mecanismo antissilêncio.

## 9. Ordem sugerida

1. `get_assets` sem `effective` — resolve o gap de visibilidade que causou o erro de 02/09 e não depende de nada.
2. **Probe de precedência** (§5.1). Se confirmar, `effective`/`shadowed_by` entram como incremento.
3. `remove_asset_link` — depende do `get_assets` para o gestor saber o que remover, e do §7 para o smoke.
4. `get_ad_schedule` — leitura barata, e a base do preview.
5. `update_ad_schedule` — por último: é o de maior blast radius e o que mais depende do preview estar certo.

## 10. Questões em aberto para o Wellington

- **Precedência (§5.1):** entregar `get_assets` sem `effective` agora e incrementar depois da probe, ou segurar a tool inteira até a probe rodar? A recomendação está na §9 (entregar sem).
- **Janela default do preview de `update_ad_schedule`:** 30 dias cobre sazonalidade de semana; 90 dá n maior mas atravessa mudanças estruturais (esta conta teve geo e portfólio mexidos em agosto). Inclinação: 30, com override.
- **`update_ad_schedule` em lote sobre várias campanhas** partilhando um orçamento: o efeito de realocação (§4.3) atravessa campanhas do mesmo portfólio. Vale recusar lote parcial dentro de um mesmo `campaign_budget` compartilhado, ou só avisar?
