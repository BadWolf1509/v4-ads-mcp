# Gate de acesso Google — reconciliação, revogação soft e fila de delegação

**Data:** 2026-09-05 · **Fecha:** pendência 10 do `estado-atual.md` e a lacuna de
descoberta que a `Hust App` expôs em 04/09.

---

## 1. O problema, em duas frases

O `can_manager_access` do lado Google lê **uma tabela só** — sem `is_active`, sem
join, e a tabela não tem coluna de revogação, porque revogar é `DELETE`. O lado
Meta perdeu exatamente esse buraco em 20/08 (PR #21) e o lado Google ficou.

E nada avisa quando entra conta nova no MCC sem grant nenhum: a `Hust App`
(`948-545-9729`) ficou alcançável por ninguém até ser achada **por acaso**,
olhando o seletor de contas do Google.

## 2. O que foi medido antes de desenhar

Tudo abaixo é medição de 2026-09-05, não estimativa.

**O gate é a única fronteira por conta.** O `build_client_for_manager` usa o
refresh token do **próprio gestor**, mas com `login_customer_id` = o MCC
`6436352492`. Confirmado com o Wellington: as identidades Google dos gestores
são usuárias do MCC. Logo o token deles alcança as 26 contas de cliente, e o que
os limita às contas atribuídas é o `can_manager_access` — mesma forma do
*confused deputy* que motivou o desenho Meta.

**Há 34 grants `write` vivos em 9 contas que saíram do MCC.** São 138 grants
Google no total, então **25% deles apontam para ex-clientes**: `Dr. Vilson
Bezerra`, `Dra. Natália Vieira Bezerra`, `Expresso Turismo`, `MDO Alagoinhas`,
`MDO Nova Serrana`, `MDO Petrolina`, `MDO Pindamonhangaba`, `ML Antiguidades`,
`Monte Carmo`. O gate de hoje aprova os 34.

**Mas o Google nega esses hoje — e isso muda o argumento, não o achado.**
Probe direta em 05/09: `run_gaql` na `6909576142` (MDO Petrolina) passou pelo
nosso gate e voltou `Sem permissão pra esta operação` do Google. Para conta fora
do MCC, o provedor é uma segunda fronteira **hoje**.

Três consequências, e a terceira é o motivo do sprint:

1. O rollout do gate é **inerte para o usuário**: não nega nada que funcione.
2. Estamos delegando ao Google a aplicação de uma regra que é nossa.
3. **Conta que volta ao MCC restabelece acesso sem ninguém re-autorizar.** É o
   caso normal numa agência — cliente que pausa e retoma —, e é o buraco que
   `is_active` no gate não fecha sozinho.

**A fila de delegação nasceria vazia hoje:** zero contas ativas sem grant. A
`Hust App` já foi delegada em 04/09. Isso não é argumento contra a fila — é o
estado normal dela; ela existe para o dia em que não for.

**O lado Google desativa na PRIMEIRA ausência.** `mark_inactive_except` faz
`is_active = false` em tudo que não voltou do resync. Existe guard contra
desativar *tudo* (`allow_full_deactivation`), mas nenhuma carência por conta —
diferente do `missed_syncs` do Meta. Amarrar revogação a esse sinal como está
significa revogar grants reais na primeira leitura parcial (família do F93).

## 3. Escopo

Espelhar o desenho Meta contra a fonte autoritativa do Google — `customer_client`
do MCC, que o `account_resync` **já lê**. Isso torna este sprint mais barato que
o Meta foi: a fonte já está computada; falta carência, revogação soft e o laço.

**Fica de fora, deliberadamente:** o fluxo de **conceder**. Conta nova entra sem
acesso nenhum e espera um humano delegar, igual ao Meta. Auto-conceder resolveria
a `Hust App` criando coisa pior.

---

## 4. Parte 1 — O gate

Vai **primeiro e sozinho**, num PR próprio. Se esperasse a migration, o item
severo ficaria aberto o sprint inteiro.

```sql
SELECT m.access_level
  FROM manager_account_access m
  JOIN google_ads_accounts a ON a.customer_id = m.customer_id
 WHERE m.manager_id = $1 AND m.customer_id = $2
   AND a.is_active = true
```

Sem `revoked_at` — essa coluna chega na Parte 2, e o gate ganha
`AND m.revoked_at IS NULL` junto com ela.

**Antes de escrever o código:** `grep` de **toda** função que chama
`build_client_for_manager`, para confirmar que `ensure_account_access`
(`src/google_ads/access.py`) é o único caminho de request que decide acesso.
Adicionar gate "a todos os executores" sem varrer é literalmente o F57.

**Guard:** conta `is_active=false` + grant vivo → `can_manager_access` retorna
`False`. Contra o código pré-fix esse teste retorna `True`, então ele distingue
código bom de quebrado. Verificar por sabotagem (cópia do arquivo, nunca
`git checkout`), não por passar de primeira.

---

## 5. Parte 2 — Carência, revogação soft e reconciliação

### 5.1 Migration `008`

```sql
ALTER TABLE google_ads_accounts
    ADD COLUMN IF NOT EXISTS missed_syncs INTEGER NOT NULL DEFAULT 0;

ALTER TABLE manager_account_access
    ADD COLUMN IF NOT EXISTS revoked_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS revoked_reason TEXT;
```

Aditiva, colunas nullable ou com default. Nenhum backfill: `missed_syncs = 0`
para todo mundo é o estado correto de partida, e `revoked_at` nulo significa
"vivo", que é o que as 138 linhas existentes são.

### 5.2 O planejador puro

`src/google_ads/reconcile.py`, espelhando `src/meta_ads/reconcile.py`: **nenhuma
I/O**. Separar decisão de efeito é o que torna testável a única parte capaz de
revogar acesso indevidamente. O repositório aplica; este módulo escolhe.

```python
@dataclass(frozen=True, slots=True)
class InventoryRow:
    customer_id: str
    is_active: bool
    missed_syncs: int

@dataclass(frozen=True, slots=True)
class Plan:
    to_add: list[str]        # no MCC, fora do inventário ativo
    to_bump: list[str]       # ausente, ainda dentro da carência
    to_remove: list[str]     # ausente, carência cumprida
    to_reset: list[str]      # voltou a aparecer, zera contador
    blocked_reason: str | None
```

`build_plan(*, mcc_ids, inventory, complete, threshold=3,
max_removal_ratio=0.2, max_removal_abs=5)`.

Mesmas invariantes do Meta, e cada uma tem um bug atrás:

- **Aditivo sempre; destrutivo só com `complete=True`.** Metade da lista não
  sustenta a afirmação "esta conta saiu do MCC".
- **`missed_syncs + 1 >= threshold`** — o contador guarda as ausências
  anteriores; esta execução é a próxima.
- **Teto `max(1, min(abs, floor(ativas × ratio)))`.** Sem o piso, inventário
  pequeno zera o teto e o guard barra até a saída de uma conta só.

**Sem `unreachable`.** O Meta tem essa raia porque `su_reachable` separa "saiu da
parceria" de "SU não atribuído" — duas ações humanas diferentes. Ver §7 para a
sonda que decide se existe análogo no Google.

### 5.3 O laço, dentro do `account_resync`

O `account_resync.py` já faz OAuth → lê o MCC → upsert → `mark_inactive_except` →
audita. Passa a: **ler o inventário → planejar → aplicar ausências → (se completo
e com a trava ligada) desativar + revogar**.

Invariantes copiadas de propósito, cada uma comprada com uma revisão no sprint
Meta:

- **Ler o inventário ANTES do upsert.** O upsert marca `is_active=true` e zera
  `missed_syncs`; se rodasse primeiro, `to_add` e `to_reset` sairiam vazios
  sempre e a auditoria nunca reportaria conta nova.
- **Uma transação só para o bloco de escrita.** Metade aplicada — carência
  somada sem desativar, ou desativada com grant vivo — é exatamente a
  inconsistência que o recurso existe para evitar.
- **`leitura_completa` ≠ `aplicado`.** Confundir os dois foi o C2 da revisão
  Meta. Upsert e carência escrevem em toda execução, inclusive no dry-run — é o
  dry-run que dá sentido ao soak. Só desativar e revogar ficam atrás da trava.
- **Auditoria do run FORA da transação.** Bookkeeping não pode desfazer
  reconciliação já aplicada (família do F83).

Linha `google_reconcile` no `audit_log`, com `params_summary` espelhando o Meta:
`added`, `bumped`, `removed`, `reset`, `revoke_candidates`, `revoked_grants`,
`applied`, `complete`.

#### A carência governa a DESATIVAÇÃO; a revogação segue de `is_active`

Ponto onde este desenho **diverge do Meta de propósito**, e a razão é uma
medição, não uma preferência.

No Meta, `to_remove` dirige as duas coisas: desativa e revoga. Funciona lá
porque as 4 contas Meta inativas têm **zero** grants vivos — o caso nunca
apareceu. No Google há **9 contas já inativas com 34 grants vivos**, e elas
nunca entrariam em `to_remove`: o planejador parte de `ativos = [r for r in
inventory if r.is_active]`, então conta que já está inativa está fora do
conjunto desde a primeira linha.

Copiar o Meta aqui deixaria os 34 grants de fora **em silêncio** — o sprint
fecharia verde sem tocar no que motivou o item severo.

Então a invariante que o laço mantém é mais simples e mais forte:

> **Nenhum grant vivo em conta inativa.**

A carência decide quando uma conta vira inativa. A revogação decorre do estado
`is_active=false`, para **toda** conta nessa condição — não só a que acabou de
cruzar. Um `revoke_for_inactive_accounts(conn, reason='left_mcc')` sob a mesma
trava, na mesma transação, cobre o legado e o fluxo novo com um caminho só, sem
script de migração de dados à parte.

`revoked_grants` no `audit_log` passa a contar isso — mas ele conta revogação
**real**, e por isso fica em **zero** o tempo todo enquanto
`GOOGLE_RECONCILE_APPLY` está `false`, que é exatamente o estado do soak
inteiro: vigiar `revoked_grants` não distingue "nada a revogar" de "a trava está
segurando 34". **O campo que soakar é `revoke_candidates`**, contado SEMPRE —
inclusive no dry-run — via `count_grants_on_inactive_accounts` (backlog: grants
vivos em conta já inativa) somado a `count_grants_on_accounts` sobre
`plano.to_remove` (grants vivos nas contas que ESTA execução desativaria). Hoje
vale **34**, medido em 05/09 (138 grants, 34 vivos em 9 contas inativas). A
primeira versão somava só o backlog e reportava zero na véspera de uma conta
cruzar a carência — achado e corrigido nesta mesma branch.

### 5.4 Revogação soft

⚠️ **Corrigido em 05/09, contra o código pós-implementação** (o texto abaixo já
é a versão corrigida). Não existe `DELETE` de offboarding — nunca existiu
call-site de offboarding aqui. O único `DELETE ... WHERE manager_id = $1` cru
vivia dentro de `copy_access` (substituição de conjunto no destino), e **são
cinco** funções que passam a tratar `revoked_at`, não duas: `grant`,
`grant_all_active`, `bulk_grant`, `copy_access` e `list_accounts_for_manager`
(que não filtrava revogado) — mais o próprio `can_manager_access` (§4), que já
lê a coluna.

`manager_account_access.revoke` (o toggle do painel) deixa de ser `DELETE` e
passa a gravar `revoked_at` + `revoked_reason`.

Razões distintas, porque a restauração depende delas: `left_mcc` (churn,
restaurável com um clique) e `admin_revoked` (deliberada, **não** volta).

`bulk_grant`, `grant` e `grant_all_active` precisam limpar
`revoked_at`/`revoked_reason` no `ON CONFLICT` — hoje é `DO NOTHING`, e com soft
revoke isso deixaria o gestor readicionado bloqueado para sempre. Foi
exatamente o que o Meta corrigiu.

`copy_access` **também não fica com `DELETE` cru**, ao contrário do que esta
spec dizia: a justificativa original — "o INSERT abaixo não tem ON CONFLICT,
uma linha soft-revogada sobrevivente bateria na PK" — descrevia o código
daquele momento, não uma restrição real, e foi resolvida assim (espelhando o
achado C1 já em produção no gêmeo Meta): o destino é soft-revogado com razão
própria (`bulk_copy_replaced`, só sobre `revoked_at IS NULL` — não toca
revogação anterior por outro motivo) e o `INSERT` ganha `ON CONFLICT ... DO
UPDATE` pra restaurar em vez de recriar. Sem isso, copiar acesso apagaria a
trilha `left_mcc` que o destino já tinha, e uma conta que depois voltasse ao
MCC restauraria só metade dos gestores certos, em silêncio.

### 5.5 Trava de rollout

`GOOGLE_RECONCILE_APPLY`, default `false`, para soakar como o Meta soakou.

⚠️ **Ela vive no `JOB_ENV_VARS` do `deploy.yml`** e é lida só pelo job. Medido em
05/09 com a trava Meta: `gcloud run jobs update` é revertido em silêncio no push
seguinte, porque o workflow reescreve a chave nos três jobs a cada deploy.

---

## 6. Parte 3 — Fila e alerta

### 6.1 A fila, em `/admin/accounts`

`list_queues` num repositório, listas no contexto do template — a forma exata do
`admin_accounts_meta`. Duas raias:

- **Aguardando delegação** — conta ativa com zero grants vivos. Hoje: 0 linhas.
- **Voltaram ao MCC** (`voltaram_ao_mcc`) — ⚠️ **corrigido em 05/09**: esta
  linha dizia que a fila chaveava em ter "cruzado a carência, ainda com grants
  vivos", ou seja `is_active = false`. Errado: chavear em `is_active = false`
  faria a conta **sumir** da fila no instante em que ela volta a ser
  restaurável, porque `upsert_many` a reativa (`is_active = true`) na MESMA
  execução em que ela reaparece no MCC. A chave real é ter **grant revogado
  por churn PENDENTE** — conta **ativa** (já voltou) **e**
  `revoked_reason = 'left_mcc'` (ainda não restaurado); só entram contas JÁ
  acionáveis. Um clique restaura exatamente esses grants.

Contas em carência (`missed_syncs > 0`) **não** viram raia: são coluna de estado
na tabela que já existe. Fila é ação pendente; carência é estado em trânsito, e
transformar as duas em fila ensina a ignorar as duas.

Acessibilidade obrigatória, do `convencoes/painel.md`: tabela dentro de
contentor de scroll com `tabindex="0" role="region" aria-label` (F118/F125),
`<th scope>` (F104), zero JS ou CSS inline (CSP sem `unsafe-*`).

### 6.2 O alerta — e por que o caminho barato não serve

Verificado antes de propor. Existem canal de e-mail e duas policies, e **nenhuma
serve de carona**:

- A policy log-based de `severity>=ERROR` é escopada ao **serviço**; quem detecta
  isso é o **job**.
- A policy de **Cloud Run Job failed** só dispara em falha. Fazer o job falhar de
  propósito mentiria sobre o estado e mascararia falha real.

Então: **métrica log-based nova + policy no canal de e-mail existente**, sobre um
campo estruturado que o job emite (`google_accounts_sem_grant`).

🔴 **Parte disto não é código.** As policies não estão versionadas em lugar
nenhum — foram criadas à mão, e o `infra-setup.md` registra que se recria por
REST da Monitoring API porque o componente `gcloud alpha monitoring` não está
instalado. Então o sprint entrega **o log estruturado + o runbook exato** (comando
REST, payload da métrica e da policy) no `infra-setup.md`, e a **criação da policy
é ação do Wellington**, registrada como pendência aberta até existir.

Sem a policy, ninguém recebe nada. A spec não finge que a métrica é o alerta.

---

## 7. A sonda que precede o código

**Task 0, antes de qualquer implementação.** `customer_manager_link.status`
existe e é GAQL válida (verificado em 05/09 por `validate_gaql`). Falta saber se
ela dá um sinal útil de vínculo **pendente** — o análogo do `su_reachable`.

Não decidir isto por analogia é regra do repo: teste que codifica convenção
errada de API externa é pior que teste ausente (F87, F89).

Os dois desfechos, ambos especificados para não restar ambiguidade:

- **A sonda encontra links `PENDING` úteis** → `Plan` ganha `unreachable`, a fila
  ganha uma terceira raia ("Vínculo pendente no MCC"), e essas contas **nunca**
  são desativadas nem revogadas — só sinalizadas, igual à §3/§5 do desenho Meta.
- **Não encontra** → o desenho fica como está nesta spec, e a ausência do
  análogo entra escrita no código, com a data da medição.

---

## 8. Testes

**Unitários, sem mock, contra o planejador puro** — é onde mora a decisão de
revogar: ausência dentro da carência não remove; ausência que a cruza remove;
`complete=False` bloqueia destrutivo e ainda assim devolve `to_add`; o teto
percentual barra remoção em massa e o piso `max(1, …)` deixa passar a saída de
uma conta só.

**Guard do gate** (§4), verificado por sabotagem.

**Integração com DB** (testcontainers, `check_pre_push_full.py`) para: o
`ON CONFLICT` do `bulk_grant` limpando `revoked_at`; a transação do bloco de
escrita não deixando estado meio-aplicado; e `list_queues` com dado que exercita
as duas raias.

**O que os testes não cobrem, e por isso vira smoke:** que o Google devolva o que
supomos em `customer_manager_link`. Isso é a Task 0, e é medição, não teste.

---

## 9. Ordem de entrega

1. **PR 1 — o gate.** Inerte para o usuário (§2), fecha o item severo.
2. **Task 0 — a sonda** do `manager_link_status`.
3. **PR 2 — migration `008` + planejador + laço + trava** (default `false`).
4. **Soak.** Igual ao Meta: observar `google_reconcile` no `audit_log` até a
   previsão bater.
   **Previsão a registrar ANTES da primeira execução**, para que o soak possa
   falhar: as 26 contas ativas estão todas no MCC e todas com grant, então
   `added=0`, `bumped=0`, `removed=0`, `reset=0`, `complete=true`,
   `applied=false`. Com a trava desligada, `revoked_grants=0` — mas o plano deve
   **reportar** `revoke_candidates=34`, senão o dry-run não observa o que a
   virada fará. Qualquer outro número significa que o desenho está errado **e
   ninguém perdeu acesso**: é para isso que a trava existe.
5. **PR 3 — fila + log estruturado + runbook da policy.**
6. **Virar `GOOGLE_RECONCILE_APPLY`** no `deploy.yml`, com o raio medido no dia —
   como foi feito com a trava Meta em 05/09.
7. **Criar a policy de alerta** (ação do Wellington).

O passo 6 revoga **34 grants em 9 contas**, pela invariante da §5.3 — é o
objetivo do sprint, não efeito colateral. **O número tem de ser reconferido no
dia**, nunca herdado desta spec: entre a escrita e a virada, contas entram e
saem do MCC.
