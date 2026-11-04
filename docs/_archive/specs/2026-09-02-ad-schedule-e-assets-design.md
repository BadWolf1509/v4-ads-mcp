# Spec — `ad_schedule`, leitura de assets e unlink de asset

**Data:** 2026-09-02 · **Origem:** gaps de campo trazidos pela sessão de gestão de tráfego da MO João Pessoa (`jo-o-pessoa-db`), conta `786-223-0676` · **Findings relacionados:** F133 (custo sem conversão), F134/F135 (camada `customer_asset` invisível) · **Status:** aguardando revisão do Wellington antes de virar plano. **Revisão 2 (02/09):** a probe da §5.1 rodou e mudou o desenho — `effective`/`shadowed_by` saíram, `primary_status` entrou. **Revisão 3 (02/09):** leitura crítica achou 8 defeitos — a §5 contradizia a §5.1, faltavam as convenções de mutate do repo (§2.1), faltava o `resource_name` que acopla §5 a §6, o `get_ad_schedule` não tinha teto, a §4.3 afirmava como medido o que era expectativa, e faltavam idempotência (§4.4), falha parcial (§4.5) e quatro guards — entre eles o da falha que a tool existe para impedir.

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

### 2.1 Convenções do repositório que estas tools herdam

A revisão 3 achou que a spec descrevia comportamento e **omitia a maquinaria** — um plano derivado dela poderia violar quatro itens do `Don't do` sem perceber. Nenhuma destas é escolha desta spec; são invariantes do codebase, e o precedente vivo é [`remove_audience.py`](../../../src/mcp/tools/remove_audience.py):

- **Envelope de mutate não se monta à mão.** `preview_envelope` / `applied_envelope` / `error_envelope` de [`_mutate_common.py`](../../../src/mcp/tools/_mutate_common.py); erro canônico é `error_message` + `operation`; TTL vem de `DEFAULT_TTL_MINUTES`, nunca literal.
- **Blast radius é computado, não declarado.** `classify` de [`blast_radius.py`](../../../src/governance/blast_radius.py). O "always-CONFIRM" da tabela da §2 é o resultado esperado, não um `if` escrito à mão — e o F112 mostra que caminho fixo sem teste amarrando diverge em silêncio.
- **SDK só dentro de `run_blocking`** (F109), inclusive em tool que constrói o próprio client. Ao offloadar, ler o `request-id` **dentro** do closure.
- **Executor Google novo segue o padrão `reserved`** (F73): `before_call` global + `mgr:<uuid>` em transação externa, `record_actual` gated por `reserved`, **audit sempre**.
- **`bucket`:** as quatro nascem `defer`. São tools de operação pontual, não do caminho quente do gestor; o `[CORE]`/`[DEFER]` da description acompanha.
- **`limit` + `truncated`** em toda leitura que possa crescer — inclusive `get_ad_schedule`, que não tinha teto nenhum na revisão 2 (mesma classe do F98: ausência total de teto, não default alto).
- **Mutate em lote usa `__partial_failure__`**, como o `remove_audience`, e o `audit_log` registra o resultado linha a linha.

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

**Schema:** `customer_id` (required), `campaign_ids[]` (opcional; default = conta inteira), `status` (default `enabled`), `limit` (default 200, teto 1000) com `truncated` na resposta. Uma campanha pode ter até 7×24 janelas, então conta grande estoura o cap de token sem teto — é a classe do F98.

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

Quando `campaign_budget.explicitly_shared` é `true`, o orçamento é do portfólio e não da janela — então desligar uma faixa horária **não devolve dinheiro**, redistribui pressão sobre as faixas que sobram. Na `786-223-0676` isso significaria empurrar gasto de um CPA de R$ 18,59 para um de R$ 23,59.

**Separando o que está medido do que é expectativa** (a revisão 2 afirmava as duas coisas no mesmo tom, e esta sessão perdeu sete afirmações por isso):

- **Medido:** `explicitly_shared = true` nos dois orçamentos ENABLED da conta, e o ativo é o portfólio JPA+CAB a R$ 310/dia. Os CPAs por dia da semana também são medidos.
- **Expectativa, não medição:** *em quanto tempo* e *com que completude* a verba se redistribui. Isso é pacing intradiário do Google e não temos como probar por API.

O dry-run **DEVE** ler `explicitly_shared` e declarar o mecanismo — sem prometer magnitude, pela mesma razão do F132. É barato: um campo, uma query.

### 4.4 Idempotência: grade igual é no-op, não remove-e-recria

Se a grade desejada for idêntica à atual, a tool **não emite mutação nenhuma** — nem `remove` nem `add` — e devolve preview vazio com `no_changes: true`.

Não é otimização: recriar criteria idênticos é uma mudança estrutural aos olhos do Google e pode custar os mesmos **14 dias de re-learning** que a tool existe para não desperdiçar. Uma tool que recebe a grade completa (§4.1) é exatamente aquela em que reenviar o mesmo payload é o caso comum — um retry, um script, um gestor confirmando. O diff tem de ser calculado **por conteúdo da janela** (`day_of_week` + horas + minutos), não por `criterion_id`, porque o id muda quando o Google recria.

### 4.5 Lote e falha parcial

`campaign_ids` aceita várias campanhas, e uma pode falhar. Segue o `remove_audience`: `__partial_failure__`, resultado linha a linha no `audit_log` e na resposta, **sem rollback automático** das que passaram — reverter schedule por conta própria seria uma segunda mutação não pedida, e o gestor precisa saber exatamente onde parou. A resposta separa `aplicadas` de `falhas`, com o motivo de cada falha.

### 4.6 Confirmação de estado

Pós-apply, reconsultar por GAQL e devolver a grade resultante. As duas falhas silenciosas da UI nessa conta são a razão de existir da tool; confiar no ACK da mutação repetiria o problema num canal novo.

---

## 5. `get_assets` (read)

**O que resolve:** a limpeza de 02/09 previa 4 vínculos em `campaign_asset` e eram **6** — os mesmos assets existiam também em `customer_asset`, e só apareceram porque o gestor foi atrás por desconfiança no `run_gaql`. Vínculo que ninguém enxerga não é auditável, e continua servindo (ou deixando de servir) sem entrar em nenhuma conta. **Nota:** a versão anterior deste parágrafo dizia que os vínculos de conta estavam *dormentes* — a §5.1 refuta isso, e o parágrafo ficou contradizendo a própria seção. Corrigido na revisão 3.

```
get_assets(customer_id, field_type?, campaign_ids?, limit=200)
```

**Decisões:**

- **Todos os `field_type` por default**, com filtro opcional. Limitar à família text-extension que o `create_and_link_assets` cobre repetiria o erro do checklist: ele previu uma camada quando existiam duas.
- **`status` por linha, e sem filtrar status no default** — pelo motivo da §7. Junto vão `primary_status` e `primary_status_reasons`, que são o veredito do Google sobre servir (§5.1).
- **As três camadas juntas**: `customer_asset` + `campaign_asset` + `ad_group_asset`, cada linha marcando seu `level`.
- 🔴 **Cada linha traz o `resource_name` do vínculo.** É o identificador que o `remove_asset_link` (§6) recebe. A revisão 2 pedia `resource_name` na entrada de uma tool e não o devolvia na saída da outra: o gestor não conseguiria encadear as duas sem cair no `run_gaql`. É a classe do F81 — macro que emite um atributo enquanto o consumidor procura outro, e ninguém nota porque cada lado está certo sozinho.
- **Órfãos marcados**: asset sem vínculo ENABLED em nenhuma camada — o que inclui os que só têm vínculo PAUSED ou REMOVED (não "sem nenhum vínculo": um vínculo PAUSED ainda é um vínculo, só não conta como vivo). Dá inventário sem precisar de tool destrutiva.
- 🔴 **Se algum dia entrarem métricas nesta tool, rotule-as como do ASSET, nunca do vínculo.** `customer_asset` e `campaign_asset` aceitam `metrics.*`, mas o número é atribuído ao asset e as linhas de vínculo repetem o mesmo total por outro corte (§5.1, provado em 3 de 3). Um campo chamado `impressions` numa linha de vínculo seria lido como "este vínculo serviu N vezes", que é falso.

### 5.1 ✅ Probe rodada (2026-09-02) — o campo `effective` sai do desenho

A primeira versão desta spec pedia precedência **calculada** (`effective`, `shadowed_by`) e marcava a regra como questão aberta, com uma probe desenhada sobre métricas. **A probe rodou e derrubou as duas coisas: o método e o conceito.**

**Resultado 1 — a probe que eu desenhei não podia responder.** A ideia era: se o vínculo de conta acumula zero impressões nas campanhas que têm vínculo próprio, "o mais específico vence" está confirmado. Medido na `786-223-0676`, `LAST_30_DAYS`, três assets CALLOUT:

| asset | `customer_asset` | `campaign_asset` (JPA + CAB) | soma |
|---|---|---|---|
| `144113768043` (ENABLED nos dois níveis) | 300 imp / 8 cl | 178 + 122 / 4 + 4 | **300 / 8** |
| `144113768040` | 693 / 25 | 392 + 301 / 17 + 8 | **693 / 25** |
| `144113768046` | 850 / 41 | 520 + 330 / 31 + 10 | **850 / 41** |

Três de três, exato até a unidade. **A métrica é atribuída ao ASSET, não ao vínculo** — a linha de `customer_asset` é a mesma veiculação vista por outro recorte. Logo impressão em vínculo de conta não prova que ele serviu, e zero também não provaria o contrário. O sinal não existe. Se a probe tivesse sido lida como planejado, o `300 ≠ 0` teria produzido a conclusão "o vínculo de conta é efetivo" — sem base nenhuma.

**Resultado 2 — existe o campo certo, e ele contradiz a leitura de campo.** As três resources de vínculo expõem `primary_status`, `primary_status_reasons` e `primary_status_details` (lidos do SDK v24). É o veredito do próprio Google sobre servir ou não. Para o asset `144113768043`, presente nos dois níveis, os dois vínculos voltam **`primary_status: ELIGIBLE`**. O Google não marca o de conta como ofuscado.

**Resultado 3 — o conceito não existe na API.** `AssetLinkPrimaryStatusReason` tem exatamente cinco valores: `ASSET_LINK_PAUSED`, `ASSET_LINK_REMOVED`, `ASSET_DISAPPROVED`, `ASSET_UNDER_REVIEW`, `ASSET_APPROVED_LABELED`. **Nenhum é de precedência.** Não há como um vínculo declarar-se ofuscado por outro mais específico, porque o Google não modela isso como estado de vínculo.

#### Consequência para o desenho

**`effective` e `shadowed_by` saem.** Seriam um veredito inventado por nós, sobre um conceito que a API não tem, num campo em que o gestor agiria. Em lugar deles, o `get_assets` devolve **`primary_status` + `primary_status_reasons`** — a resposta autoritativa do Google, e mais rica do que precedência: cobre reprovação de política, revisão pendente, pausa e `LIMITED`, que o `effective` nunca cobriria.

Valores possíveis (SDK v24): `ELIGIBLE`, `PAUSED`, `REMOVED`, `PENDING`, `LIMITED`, `NOT_ELIGIBLE`.

**Isso desbloqueia a tool inteira.** A §9 recomendava entregar `get_assets` sem `effective` e incrementar depois da probe; a probe rodou, e o incremento não existe — existe um campo melhor, que entra desde a v0. Não há mais questão aberta bloqueando.

#### ⚠️ Correção de uma crença operacional

O relato de campo dizia que os vínculos de conta estavam **dormentes** porque "callout de campanha tem precedência". **Nada do que a API expõe sustenta isso**, e o que ela expõe diz o contrário: os dois vínculos coexistentes estavam `ELIGIBLE`.

O que segue verdadeiro é o essencial — os vínculos de conta existiam, eram invisíveis a quem só olhasse campanha, e eram 6 remoções e não 4. O que cai é a inferência de que fossem inertes: pelo veredito do Google eram elegíveis, então removê-los foi mudança real no que podia aparecer na SERP, não faxina de resto morto.

**Limite declarado:** se um vínculo elegível de fato apareceu num anúncio servido é decisão de leilão, e a API não responde isso por vínculo. A afirmação aqui é sobre elegibilidade, que é o que existe para ser lido — e é justamente por não haver resposta por vínculo que a tool não deve inventar uma.

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
7. 🔴 **`get_assets` consulta as TRÊS camadas** — teste que exercita uma conta com vínculo em `customer_asset` e nenhum em `campaign_asset` e exige a linha de conta na saída. **A revisão 2 não tinha este guard, que é o da falha que a tool existe para impedir:** uma implementação que consultasse só `campaign_asset` passaria em todos os outros testes e reproduziria exatamente o erro de 02/09.
8. **`get_assets` devolve `resource_name`** e ele é aceito pelo `remove_asset_link` — guard de acoplamento entre as duas (classe F81), porque cada lado está certo sozinho.
9. **Grade idêntica não emite mutação** (§4.4) — teste que reenviar a grade atual produz `no_changes: true` e **zero** operações. Sem ele, a implementação natural (apagar tudo e recriar) passa em todos os outros testes e queima re-learning.
10. **Envelope e blast radius vêm do compartilhado** — guard derivado do source, no espírito do F112, que falhe se a tool montar envelope à mão ou fixar o nível sem `classify`.

Todo guard deve ser verificado **contra o código pré-fix ou por sabotagem**, nunca por ter passado de primeira. Esta sessão registrou 7 ocorrências da família *guard que passou sem cobrir*, uma delas em cima do próprio mecanismo antissilêncio.

## 9. Ordem sugerida

1. `get_assets` **completo**, com `primary_status`/`primary_status_reasons` desde a v0 — resolve o gap de visibilidade que causou o erro de 02/09 e não depende de nada. A probe de precedência já rodou (§5.1) e **eliminou** o `effective` em vez de habilitá-lo, então não há etapa condicional aqui.
2. `remove_asset_link` — depende do `get_assets` para o gestor saber o que remover, e do §7 para o smoke.
3. `get_ad_schedule` — leitura barata, e a base do preview.
4. `update_ad_schedule` — por último: é o de maior blast radius e o que mais depende do preview estar certo.

## 10. Questões em aberto para o Wellington

- ~~Precedência (§5.1)~~ — **resolvida pela probe de 02/09**: `effective` saiu do desenho e `primary_status` entrou. Não precisa mais de decisão.
- **Janela default do preview de `update_ad_schedule`:** 30 dias cobre sazonalidade de semana; 90 dá n maior mas atravessa mudanças estruturais (esta conta teve geo e portfólio mexidos em agosto). Inclinação: 30, com override.
- **`update_ad_schedule` em lote sobre várias campanhas** partilhando um orçamento: o efeito de realocação (§4.3) atravessa campanhas do mesmo portfólio. Vale recusar lote parcial dentro de um mesmo `campaign_budget` compartilhado, ou só avisar?
