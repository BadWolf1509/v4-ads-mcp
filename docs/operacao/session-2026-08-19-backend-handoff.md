# Sessão 2026-08-19 — Handoff (investigação de backend → 4 findings fechados)

> Segunda varredura do dia, agora no núcleo (tools MCP, executores Google/Meta, DB, auth, jobs, governança) — cinco dias depois da varredura ampla de 08-14/15. **4 achados (F109-F112), todos fechados**, um commit por onda. A investigação de frontend do mesmo dia está em [`session-2026-08-19-frontend-handoff.md`](session-2026-08-19-frontend-handoff.md).

## TL;DR

| # | Achado | Commit |
|---|---|---|
| **F109** | 3 caminhos que servem request bloqueavam o event loop — F86 fechado **sem guard nenhum** | `0bdc5a0` |
| **F110** | `get_my_rate_limit_status` reportava a quota que não bloqueia o chamador | `5204566` |
| **F111 + F112** | Audit Meta derivava a conta de dict opcional; política de blast radius consultiva em 17/26 tools | `cb0203a` |

`check_pre_push.py` 5/5 verde em cada commit.

## O achado que organiza a sessão

**O F86 foi fechado em 08-14 sem guard nenhum.** `run_blocking` não aparecia em lugar algum de `tests/` — nem guard estrutural, nem teste. O fix cobriu 4 executores e parou; três caminhos que atendem request ficaram bloqueando o event loop por cinco dias:

| Site | O que rodava no loop |
|---|---|
| `validate_gaql` | `ga_service.search()` direto. É o tool que **não passa pelos executores** — o mesmo motivo que o deixou sem o gate do F57 |
| `run_recommendation_action` | chamava os executores sync direto, com `run_mutation` fazendo certo **180 linhas acima no mesmo arquivo** |
| `run_meta_graph_get` | `api.call()` dentro de um `while` de até **5 páginas** — round-trips sequenciais ao `graph.facebook.com` |

Cada um congela a instância inteira: com `--concurrency=80` os requests serializam e o `asyncio.timeout(5)` do `/health?deep=1` **nem começa a contar**, porque o timer só dispara quando o loop volta a girar.

O detalhe que dói: **a lista dos 6 sites já existia.** É a que o CLAUDE.md enumera pro gate do F57 — `run_report`, `run_mutation`, `run_conversion_upload`, `run_offline_user_data_job`, `run_recommendation_action`, `create_pending` e `validate_gaql`. O F86 usou outra, mais estreita ("os executores"), e a diferença entre as duas listas é exatamente o que ficou para trás. O CLAUDE.md até manda "grep TODA função que chama `build_client_for_manager`" — a regra existia, para outra classe.

É a contraparte da lição da investigação de frontend do mesmo dia. Lá o padrão era *guard verde não é cobertura*; aqui não havia guard.

## O guard exigiu duas correções antes de valer

Escrevi o guard primeiro, de propósito: ele **é** o teste que falha para os três sites de uma vez. Só que a primeira versão mentia nos dois sentidos.

1. **Faltava fecho transitivo.** `run_recommendation_action` não chama o SDK — chama `execute_apply_recommendation`, um helper sync em outro módulo, que chama. Um guard que só procurasse nomes de método do SDK dava verde nele. O fecho tem que subir: função sync que chama função sync bloqueante também é bloqueante.

2. **Faltava distinguir a forma da chamada.** Com o fecho transitivo, o guard passou a acusar `apply_change` — falso positivo, porque `run_offline_user_data_job` é **ao mesmo tempo** um método do SDK Google e o nome do nosso executor async (que já offloada). Métodos de SDK são sempre chamada de **atributo** (`service.foo()`); exigir a forma resolve.

Só depois disso o guard ficou RED nos 5 sites reais com zero falso positivo — e é assim que ele entrou.

O `api.call` do Meta entrou por uma regra própria (`.call` num receptor chamado `api`): `call` é genérico demais pra casar por nome, e o receptor é o idioma do arquivo, já contido pelo guard do F57-Meta.

## Duas decisões de desenho que valem além do fix

### `_blocking.py` mudou de casa

Estava em `src/google_ads/`, com docstring falando só de gRPC. O fix do Meta precisaria de `meta_ads` importando de `google_ads` — dependência invertida. Foi pra [`src/blocking.py`](../../src/blocking.py), com o docstring cobrindo os dois SDKs e o escopo reescrito: não é mais "os executores", é **todo caminho que atende request**, com `accounts.py` nomeado como a exceção (só o job de resync o importa — verificado).

### O blast radius não foi reescrito, foi amarrado por teste

`classify` se descreve como quem "decide auto-apply vs require-confirmation", mas só 9 das 26 tools leem `.level`. As outras 17 computam o veredito, usam só o `.reason` como texto, e têm o caminho fixo no código.

Verifiquei os dois lados: **não há divergência hoje**. A tentação era reescrever as 17 pra consultarem `.level`. Não vale o tamanho — **o risco não é a tool errar, é a política e a tool divergirem**, e isso um teste pega por uma fração do custo. O guard deriva a lista do source (quem lê `.level` é pulado; quem só emite token tem que ser CONFIRM; quem só chama executor tem que ser AUTO) e falha alto se uma tool não couber em nenhum caso, então tool nova entra sozinha.

Como ele passou de primeira, foi **provado por sabotagem**: apertar a política para `remove_negative_keywords` deixa o guard RED exatamente nessa tool; revertido, verde.

## Verificação

- `check_pre_push.py` 5/5 em cada commit. Docker não está instalado aqui, então os testes de integração só rodam no CI — todos os guards novos são unit (AST sobre o source, ou chamada direta da função).
- `FacebookAdsApi.call` foi inspecionado **na fonte instalada** (`inspect.getsource`), não deduzido de doc: não é coroutine e usa `self._session.requests.request(...)`.
- O guard do event loop foi provado contra o código pré-fix (RED nos 5 sites); o do blast radius, por sabotagem; o do audit Meta ficou RED naturalmente em 2 dos 3 sites (o de negação já estava certo).
- Guards novos: 4 arquivos, ~25 casos.

## O que foi verificado e estava limpo

A maior parte da varredura não virou achado, e isso vale registrar:

- Nenhum `datetime.now()`/`utcnow()` sem timezone em `src/`.
- Nenhuma SQL montada com dado de usuário — todas parametrizadas por `$N`, com o `WHERE` montado de literais.
- Os 7 call-sites de `ensure_account_access` usam o nível certo (`write` nas mutações, `read` nas leituras), e `can_manager_access` é simétrico entre Google e Meta.
- `dry_run.consume` é race-safe (`SELECT ... FOR UPDATE` + `consumed_at`), amarrado à sessão e com TTL checado.
- A aritmética do rate limit está correta sob o `FOR UPDATE`; o `pct` como fração (0–1) é deliberado e o consumidor renderiza `pct * 100`.
- Os 28 `except` que "engolem" exceção são todos envelope de erro ou observabilidade defensiva documentada.
- OAuth e resync usam `httpx` (async) — o bloqueio era só nos dois SDKs de ads.

**Hipótese que caiu:** `apply_change` checa `status == "error"` num ramo e não nos outros dois. Parecia inconsistência defensiva; é o contrário — só `run_conversion_upload` devolve dict de erro, os outros dois levantam. A checagem está exatamente onde há erro pra checar. Terceira vez seguida (com `meta_list_my_ad_accounts` e a barra sticky do `/admin/audit`) que uma suspeita plausível cai ao ser confrontada com o código.

## Pendente

Nada deste pacote. Os 4 estão fechados e commitados na `main`.
