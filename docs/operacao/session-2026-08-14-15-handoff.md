# Sessão 2026-08-14/15 — Handoff (investigação ampla → 18 findings fechados)

> Pedido de uma frase: *"investigue bugs e gaps no projeto"*. Sem escopo prévio. Resultado: **19 findings novos catalogados (F82-F100)** e **18 fechados** em duas ondas — 11 na investigação e os 7 restantes no pedido seguinte (*"corrija todas as restantes"*). O F82 ficou aberto **só na causa raiz**, por escolha documentada.
>
> Detalhe por finding está no [`findings-catalog.md`](findings-catalog.md) — cada entrada corrigida tem um bloco **✅ CORRIGIDO** com o que foi feito, o que foi deixado de fora e por quê. **Este handoff é o mapa, não a enciclopédia.**

## TL;DR

| Finding | O que estava errado | Estado |
|---|---|---|
| **F82** | Segredos do Meta (token system-user, `client_secret`) na URL → Cloud Logging | **vazamento fechado**; causa raiz parcial |
| **F83** | Mutação aplicada virava erro e sumia do audit se o `finally` falhasse | ✅ |
| **F84** | `status` e `is_active` divergiam; Bearer MCP sobrevivia a offboarding | ✅ |
| **F85** | Resposta vazia do Google desativava as 25 contas do MCC | ✅ |
| **F86** | SDK Google síncrono congelava o event loop (e o `/health`) | ✅ |
| **F87** | Escape GAQL usava doubling de SQL; quebrava nome com apóstrofo | ✅ |
| **F88** | Tools Meta truncavam na página 1 e ordenavam depois — "top" que não era top | ✅ |
| **F89** | Parser Meta devolvia 4 campos que a query nunca pedia (constantes) | ✅ |
| **F90** | `audit_competitor_keywords` sem status do ad_group pai (classe F52) | ✅ |
| **F92** | Pool 10×10 instâncias vs 60 do Supabase + `acquire` aninhado | ✅ |
| **F93** | Job reportava `success` sobre inventário parcial; crash sem audit | ✅ |
| **F100** | Data fixa em teste venceu a janela de 90 dias e derrubou o CI | ✅ |

## 2ª onda — os 7 restantes (mesmo dia, pedido "corrija todas")

| Finding | O que mudou | Estado |
|---|---|---|
| **F98** | `limit` + `LIMIT limit+1` nos 3 reads sem teto; `budget_pacing` ganhou `ORDER BY` | ✅ |
| **F96** | `revoke` responde `204`+`HX-Refresh`; template perdeu a compensação | ✅ |
| **F97** | `sticky-head` com offset variável; barra de `/admin/audit` passou a ser medida | ✅ |
| **F95** | 3 secrets Supabase removidos + guard cruzando `deploy.yml` × `Settings` | ✅ |
| **F91** | 9 reads quentes por `run_with_reconnect`, sem arrastar a escrita junto | ✅ |
| **F94** | Backup em snapshot único (`REPEATABLE READ`) e em stream pro GCS | ✅ |
| **F99** | doc-drift do CLAUDE.md (fechado em `c3bc1cd`) | ✅ |
| **F82** | probe resolveu a dúvida do header; migração segue pendente de token válido | **guard entregue** |

**O padrão que dominou esta onda: quase todo fix criava um risco novo, e o trabalho estava em enxergá-lo.**

- **F98** — pôr `LIMIT` no `budget_pacing`, que ordena por gasto **depois** de receber as linhas, entregaria N campanhas arbitrárias reordenadas entre si: um "top" que não é top, a classe **F88**. Precisou de `ORDER BY` na query, com teste assertando que ele vem **antes** do `LIMIT`.
- **F91** — envolver o gate em retry re-executaria a **escrita** do audit de negação. Resolvido diferente nos dois lados pelo custo: no Meta o read e a escrita foram separados de fato; no Google, onde a mudança de assinatura custaria ~40 arquivos de teste, a escrita foi envolvida em `best_effort` pra que a exceção não chegue ao retry.
- **F94** — `blob.open("wb")` abre o upload **antes** do COPY, então uma falha no meio poderia deixar um `.gz` truncado no bucket, pior que arquivo ausente. **Verificado na fonte instalada** (google-cloud-storage 3.12.0): `__exit__` chama `terminate()` na exceção e cancela o upload resumable. E a transação única propaga falha — um `PostgresError` aborta o snapshot, então o resto é marcado de uma vez em vez de gerar N erros de "current transaction is aborted".
- **F95** — a "mudança coordenada" que o finding pedia não era necessária (`extra="ignore"`), o que importa porque os **Cloud Run Jobs** foram criados à mão e seguem montando os 3 secrets.

**Probe empírica de novo decidindo um finding, e desta vez sem gastar segredo.** O F82 estava travado na dúvida `OAuth` vs `Bearer`. Mandar um token **falso** resolveu: `Bearer` → code 190 *"Cannot parse access token"*, `OAuth` → 190 idêntico, **sem header** → code 2500 *"An active access token must be used"*. O erro diferente sem header prova que o token foi lido do header nos dois casos. Falta só confirmar com token válido (`gcloud auth login` + [`scripts/probe_meta_auth_header.py`](../../scripts/probe_meta_auth_header.py)) — e como `_fetch_all_adaccounts` roda no job diário de produção, a migração **não** foi shipada com validação parcial. Foi entregue um guard AST que impede call-site novo.

**Guard que quase nasceu furado, 3ª vez na sessão:** o do F82 só via dict literal inline e dava verde justamente em `_fetch_all_adaccounts`, que monta o dict numa **variável** por causa da paginação. Os guards do F95 e do F91 foram provados por sabotagem antes de contar como feitos.

## Como a investigação foi conduzida

6 auditorias paralelas read-only sobre áreas disjuntas: tools MCP, painel web, auth/acesso, DB/jobs/governança, núcleo Google/Meta, CI/tooling/doc-drift. **Todo finding foi reaberto e confirmado no código antes de ser catalogado** — nada entrou por relato de subagente.

Dois sinais de que a paralelização funcionou: duas auditorias convergiram sozinhas no mesmo achado (audit Meta lendo `customer_id` do `params_summary`), e uma hipótese forte levantada a priori foi **refutada** na verificação (`meta_list_my_ad_accounts` vazando inventário entre gestores — não procede, o tool filtra pela matriz).

## Padrões que se repetiram — leia isto antes do próximo fix

### 1. Teste que fixa o comportamento errado é pior que teste ausente

Aconteceu **três vezes**:

- **F87**: dois testes asseriam que o escape SQL (`''`) era o correto, com comentários afirmando *"must be doubled per GAQL string literal rules"*.
- **F89**: cinco testes fixavam campos fantasma, alguns cobrindo cenários **impossíveis** (verificar o label de um status que nunca chega; um par `with_daily_budget`/`no_daily_budget` fingindo cobrir a distinção CBO quando ambos davam `None`).
- **F84/F89**: mocks que **não conseguiam expressar o bug** — um `_FakeManager` com só `is_active`, e bodies de resposta Meta contendo campos que a API nunca devolve.

Não faltava cobertura: a cobertura existia e apontava para o lado errado, o que **desliga a suspeita**. É provavelmente por isso que esses bugs sobreviveram a várias sprints.

**Regra prática:** asserção sobre superfície de API externa precisa nascer de probe empírica, não de analogia ("GAQL parece SQL"). E mock que simplifica demais apaga a categoria de bug que deveria pegar.

### 2. Guard que passa de primeira merece desconfiança

**Duas vezes** um guard meu passou vazio na primeira versão:

- **F87**: grep de linha casou a **própria docstring** que explicava a regra (4ª ocorrência dessa armadilha, já registrada em 08-11).
- **F92**: exigi que `.acquire` pendesse de `get_pool()` no AST, mas o idioma do codebase é `pool = get_pool()` e depois `pool.acquire()` — dois nós separados.

**Regra prática:** guard novo tem que ser verificado contra o código **pré-fix** (sabotagem ou `git stash`). Se passa de primeira, provavelmente não está casando o que você acha.

### 3. A correção pode criar o próximo bug — silenciosamente

- **F86**: mover o SDK para thread quase apagou o `provider_request_id` de **todo** audit. O interceptor grava num ContextVar, e `to_thread` copia o contexto sem propagar de volta. O campo é opcional — nada reclamaria.
- **F92**: ler `Settings` dentro de `init_pool` derrubou a suíte inteira de integração no CI.

**Regra prática:** ao mover código para outro contexto de execução (thread, processo, transação), pergunte o que era implícito no contexto antigo. E primitivo de infraestrutura não depende da config completa da app.

### 4. Probe empírica antes de mexer em superfície de API externa

O **F87** foi decidido testando as duas hipóteses contra a API real via `validate_gaql` **antes** de escrever código:

| GAQL | válido |
|---|---|
| `IN ('O\'Brien')` | **true** |
| `IN ('O''Brien')` (o código antigo) | **false**: `invalid value 'Brien'` |
| `IN ('Promo \')` | **false** — o erro mostra a string engolindo o `')` |
| `IN ('Promo \\')` | **true** |

Pelo mesmo princípio, **duas coisas ficaram deliberadamente de fora**: a migração dos 3 call-sites do F82 para o header `Authorization` (formato é quirk do Meta, doc mostra `OAuth` e não `Bearer`) e o sort server-side do F88 (`sort=spend_descending` não validado). Ambas precisam de probe antes.

## Mecanismos novos que passaram a existir

| Mecanismo | Onde | Para quê |
|---|---|---|
| `best_effort` | [`governance/bookkeeping.py`](../../src/governance/bookkeeping.py) | Bookkeeping em `finally` não pode derrubar a operação (F83); reusado no audit de crash de job (F93) |
| `run_blocking` | [`google_ads/_blocking.py`](../../src/google_ads/_blocking.py) | Chamada síncrona do SDK sai do event loop (F86) |
| `gaql_string_literal` | [`queries/_gaql.py`](../../src/google_ads/queries/_gaql.py) | Escape GAQL correto, sem dependências (F87) |
| `record_job_crash` | [`jobs/_audit.py`](../../src/jobs/_audit.py) | Crash de job deixa linha no audit (F93) |
| `Manager.is_deactivated` | [`repositories/managers.py`](../../src/db/repositories/managers.py) | Predicado único de desativação (F84) |
| `AdAccountsFetch` | [`auth/meta_oauth.py`](../../src/auth/meta_oauth.py) | Inventário parcial não se passa por completo (F93) |

**4 guards estruturais novos** em `tests/unit/test_structural_guards.py` (todos AST, todos verificados contra o código pré-fix): `finally` sem `best_effort`, doubling de aspas em GAQL, helper auto-adquirente dentro de `acquire`, e o de parser lendo campo não pedido (este em `test_insights_no_phantom_fields.py`).

## Verificação

- `check_pre_push.py` verde antes de cada commit; **CI confirmado por `gh run view --json conclusion`**, nunca pelo exit code do watch.
- **Dois CI vermelhos**, ambos diagnosticados e corrigidos: o F100 (data fixa) e o F92 (acoplamento com Settings). Nos dois o gate `needs: test` pulou o deploy — produção nunca recebeu código quebrado.
- **Monitores de CI não funcionaram** (4 alarmes falsos: reportavam "não concluiu" para runs já fechados). A hipótese é que o `gh` não resolve no shell deles. O que funciona é `Bash` com `run_in_background` e um `until` loop — mesmo ambiente onde o `gh` comprovadamente roda.

## Estado da produção

Última revisão verificada verde com `/health?deep=1` = `{"status":"ok","db":"ok"}` e `/mcp` = 401. **Mudanças de comportamento observável** que valem saber:

1. As linhas `HTTP Request: ...` do httpx **sumiram** do Cloud Logging (F82 — efeito pretendido, não perda acidental de observabilidade).
2. O `meta_resync` grava `status="error"` quando o inventário vem truncado (F93) — a linha de erro é sinal de que o job **se protegeu**, não de que quebrou.
3. O pool caiu de 10 para 5 conexões por instância (F92). Se aparecer lentidão, `DB_POOL_MAX_SIZE` é env var e sobe sem tocar em código.
4. As tools Meta agora devolvem `truncated` (F88) e **não** devolvem mais `effective_status`/`creative_id`/`daily_budget_brl`/`billing_event` (F89).
