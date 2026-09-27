# F154 — o alcance do system user medido pela leitura, não pelo índice

**Data:** 2026-09-27 · **Finding:** F154 (MEDIUM) · **Decisão:** Wellington, 27/09 — leitura mínima
por conta (entre três abordagens, abaixo).

## 1. O problema

`meta_ad_accounts.su_reachable` diz ao painel se o system user (SU) alcança a conta. Ele é
escrito pelo job diário (`src/jobs/meta_resync.py`) a partir de `/me/adaccounts` — o
inventário **próprio** do SU —, e o painel o apresenta como *"o SU lê esta conta"*. Não são
a mesma pergunta.

**Medido em 27/09** (Graph API, token do SU, read-only):

| | resultado |
|---|---|
| contas Meta ativas no inventário | 25 |
| `/me/adaccounts` | 24 contas |
| `su_reachable = false` | 1 — **CHUTE 07** (`act_1428319651342125`), marcada assim pelo menos desde 24/09 |
| o SU lê a CHUTE 07? | **sim** — nó `200`, `/insights` `200` |
| controle: conta sem acesso (`act_1234567890123`, `act_1`) | `403`, `code=200` — *"(#200) Ad account owner has NOT grant ads_management or ads_read permission"* |
| controle: token inválido | `401`, `code=190` |

O confundidor que o F154 deixou aberto em 05/09 (*"alguém atribuiu o SU entre as duas
leituras"*) cai: o sinal está `false` há dias com a leitura funcionando. A
`CA - V4 Lima Soares`, a outra conta de 05/09, hoje aparece em `/me/adaccounts`. Por isso o
índice é intermitente para ela e persistente para a CHUTE 07 — **o índice não é prova de
alcance**.

**Consequências hoje:**

1. A fila **"Sem o system user atribuído"** (`/admin/accounts/meta`) manda o admin atribuir
   no Business Manager um SU que já lê a conta. É um alarme que pede ação impossível, e isso
   ensina a ignorar a fila.
2. A mesma conta fica **fora** de "Aguardando delegação", porque as filas são exclusivas e
   `sem_su` tem precedência (`list_queues`).
3. O `unreachable` do relatório da reconciliação conta 1 todo dia, e é artefato. A leitura
   de 20/08 ("25 na edge do BM, 23 em `/me/adaccounts`: duas sem SU") provavelmente já era
   esse artefato.
4. **O M10 (registrado no código, não corrigido):** o desligamento de contas que saíram da
   parceria exige `parceria.complete AND alcance.complete`. Uma indisponibilidade de
   `/me/adaccounts` — que desde a spec 2026-08-20 §3 **não define o inventário** — congela o
   offboarding e grava `status=error` todo dia.

**O que o sinal NÃO toca** (conferido por grep): o gate de acesso (`can_manager_access`)
não lê `su_reachable`, e a reconciliação nunca desativa por ele (spec 2026-08-20 §3: *"Nunca
desativa"*). O dano é de verdade no painel e no relatório, não no acesso.

## 2. Decisão

**O alcance passa a ser medido pela capacidade que ele promete:** uma leitura mínima de cada
conta da parceria, a mesma chamada que as tools fazem. O padrão é o *health check pela
capacidade* — verifica-se a coisa que importa, não um índice que a aproxima.

Recusadas, com o motivo:

- **Híbrido** (índice + confirmação só das omitidas): mais barato (1–2 chamadas/dia), mas o
  sinal fica com duas fontes, e o desligamento segue preso ao índice (M10).
- **Só renomear a fila** ("Fora do inventário próprio do SU"): custo zero, mas a CHUTE 07
  continua fora de "Aguardando delegação" sendo lida.

## 3. Desenho

### 3.1 A sonda e os três estados

No job, para **cada conta da parceria**, uma chamada `/insights` montada por
`build_insights_call(level="account", start=ontem, end=ontem, limit=1)` — a forma exata das
tools (F194). "Ontem" é no fuso da conta (`account_today`, sobre o mesmo instante `agora` que o
job já lê uma vez — F141). Conta sem entrega ontem devolve `200` com `data` vazia: continua
sendo **lê**, porque a pergunta é o acesso, não o gasto. O resultado é um de três estados:

| resposta | estado | efeito em `su_reachable` |
|---|---|---|
| `200` | **lê** | `true` |
| `4xx` com `error.code == 200` (a única recusa medida) | **recusa** | `false` |
| qualquer outra: `190` (token), limite, `5xx`, timeout, erro de rede, código de recusa não medido | **não medido** | **não grava** — fica o último valor medido |

- "Não medido" nunca vira `false` (a família do F191/F194: ausência de medição não é
  resposta). Um código de recusa que ainda não vimos aparece como não medido no relatório, em
  vez de marcar conta como inalcançável sem prova.
- Custo: ~25 chamadas/dia, sequenciais, fora do caminho de request, com **timeout de 15 s
  por sonda** (o cliente do job usa 60 s; 25 contas penduradas seriam 25 minutos de job).
  Timeout é não medido. Sem audit por chamada
  (como o `/me/adaccounts` de hoje): o registro é o `params_summary` do `record_job_run`.
- A classificação é uma função pura (`classificar_sonda(status, corpo) -> "le" | "recusa" |
  "nao_medido"`), testável por tabela, e a sonda é injetável no job.

### 3.2 O que muda no job e no planejador

- **`/me/adaccounts` sai do job.** `_fetch_all_adaccounts` fica: o OAuth pessoal
  (`src/auth/meta_oauth.py`) o usa.
- **`set_reachable`** passa a receber os dois conjuntos medidos — `le` e `recusa` — e grava
  `true` num e `false` no outro. Conta não medida não é tocada. Continua escopado à parceria
  (M4) e no-op quando nada foi medido.
- **`build_plan`** troca `reachable_ids` por `refused_ids` (as recusas medidas):
  `unreachable = parceria ∩ recusadas`. Antes era `parceria − índice`, que punha no
  `unreachable` também o que não foi lido.
- **Completude = só a parceria.** `leitura_completa = parceria.complete`. O desligamento
  deixa de depender do alcance — **fecha o M10** e realinha o job à §3 de 2026-08-20.
- **Relatório** (`params_summary` do `meta_reconcile`): `unreachable` passa a contar só as
  recusas medidas, e entra `alcance_nao_medido` (quantas contas da parceria não tiveram
  resposta classificável). `complete` passa a descrever só a parceria.

### 3.3 O painel

O texto da fila **"Sem o system user atribuído"** fica: com a sonda, ele passa a ser
verdade (`#200` é exatamente "o owner não concedeu leitura ao SU"). Nenhuma fila nova para
"não medido": a conta mantém o último estado medido, e a contagem sai no relatório (§5).

## 4. Testes

- **Classificação** (unit, por tabela): `200` → lê; `403`+`code 200` → recusa; `401`+`190`,
  `429`, `500`, timeout/erro de rede, `400` com outro código → não medido. As assinaturas
  vêm da medição de 27/09.
- **Planejador** (unit): conta recusada entra em `unreachable`; conta não medida não entra; o
  desligamento de conta fora da parceria roda **com o alcance inteiro não medido** — é o
  vermelho do M10 contra o código atual.
- **Repositório** (integração, testcontainers): `set_reachable` com `le`/`recusa` grava os
  dois lados; conta não medida mantém o valor anterior (`true` e `false`); fora da parceria
  não é tocada.
- **Job** (unit, com a sonda injetada): o `/me/adaccounts` não é chamado; o `params_summary`
  traz `alcance_nao_medido`; com a parceria completa e todas as sondas não medidas, o plano
  destrutivo não é bloqueado.
- Cada teste novo é medido vermelho contra o código atual antes do conserto.

## 5. Fora do escopo

- **O gêmeo Google** do `unreachable`: outra fonte, outra medição.
- **O `/me/adaccounts` do OAuth pessoal** (fluxo dormente desde o Modelo B).
- **Fila ou marcação de "não medido" no painel.** Só entra se o relatório mostrar que a
  sonda falha com frequência.
- **Alerta** para `alcance_nao_medido` alto: o job já tem a policy "Cloud Run Job failed",
  e a sonda não medida não é falha do job.
- **O motivo de `/me/adaccounts` omitir a CHUTE 07** (atribuição pelo BM vs. direta ao SU):
  não muda a decisão, e a sonda torna a pergunta irrelevante para o sinal.

## 6. Verificação em produção

Depois do deploy, na execução seguinte do job (ou numa sob demanda do
`v4-ads-mcp-resync`): a CHUTE 07 com `su_reachable = true`, o `unreachable` em `0`,
`alcance_nao_medido` em `0`; no painel, a CHUTE 07 em "Aguardando delegação" (se não tiver
gestor) e a fila "Sem o system user atribuído" vazia.
