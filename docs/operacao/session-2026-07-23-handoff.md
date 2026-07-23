# Sessão 2026-07-23 — Handoff (alerta do Cloud Run → validação F76 + F77)

> Estado final autoritativo: commit **`23fccfea3fcf3b18de65dc8a8c2f17c935775460`** em `main`, CI/deploy [run 30047283991](https://github.com/BadWolf1509/v4-ads-mcp/actions/runs/30047283991) verde, produção em **`v4-ads-mcp-00028-lvc`** com 100% do tráfego. `/health?deep=1` retorna 200 `db=ok`; nenhum log `severity>=ERROR` foi observado após o deploy.

## TL;DR

| Item | Resultado |
|---|---|
| Alerta recebido | Dois probes `/health?deep=1` retornaram 503 por conexão asyncpg stale; o serviço e o MCP continuaram disponíveis |
| F76 D+1 | **Validado positivamente em produção:** retry detectou conexão morta, readquiriu outra e o request MCP terminou 200 |
| F77 | O deep health ainda usava `pool.acquire()` cru; passou a usar `run_with_reconnect` com deadline global de 5s |
| Testes | 3 regressões novas + pre-push 5/5 + integração DB no CI |
| Deploy | `23fccfe` → revisão `00028-lvc`; migrations e smoke verdes |

## O que realmente disparou o alerta

O e-mail “Cloud Run Revision with a log matching the query has appeared” veio da policy log-based:

- policy ID: `6765708543993578761`;
- filtro: `resource.type="cloud_run_revision" AND resource.labels.service_name="v4-ads-mcp" AND severity>=ERROR`;
- rate limit: 1 notificação/hora; auto-close: 24h;
- “No severity” no e-mail significa que a **policy não tem severidade de incidente configurada** — não que o log estava sem severity.

Entradas que acionaram a policy, na revisão `v4-ads-mcp-00027-kmw`:

| UTC | Request | App log |
|---|---|---|
| 2026-07-23 20:54:17 | `GET /health?deep=1` → 503 | `health_deep_db_failed`: `connection was closed in the middle of operation` |
| 2026-07-23 20:56:35 | `GET /health?deep=1` → 503 | mesmo erro |

Entre as duas falhas, um ping MCP às 20:55:12 retornou 200. O health voltou a 200 às 20:57:31 sem intervenção. Portanto, foi falha transitória da conexão retirada do pool, não indisponibilidade sustentada do serviço ou do banco.

O uptime check é menos sensível: HTTPS `/health?deep=1`, período 300s, timeout 10s, matcher `"db":"ok"`, `STATIC_IP_CHECKERS`; a policy exige mais de uma série falsa sustentada por 300s. Ela não abriu incidente. O alerta amplo de logs viu cada request 503 como `ERROR` e notificou.

## Evidência histórica e causa-raiz

Desde a criação do deep health (2026-06-20), houve 6 falhas, todas em 4-5ms e com a mesma mensagem:

- 2026-07-09 21:27:43 — revisão `00020`;
- 2026-07-16 21:19:17 e 21:27:32 — revisão `00025`;
- 2026-07-22 17:21:35 — revisão `00027`;
- 2026-07-23 20:54:17 e 20:56:35 — revisão `00027`.

Três ocorreram depois de `max_inactive_connection_lifetime=120`. Esse parâmetro reduz a janela de risco, mas asyncpg não faz pre-ping: ainda existe corrida entre o remoto fechar o socket e o pool reaproveitá-lo.

O gap era local ao handler: `src/app.py` fazia `pool.acquire()` + `SELECT 1` diretamente, sem o `run_with_reconnect` criado no F76. A reprodução stale→healthy confirmou que o handler antigo devolvia 503 após um único acquire; o boundary resiliente recuperava com dois acquires.

## F76 — validação D+1 concluída

Em **2026-07-23 21:16:14.903695 UTC**, produção registrou:

- `db_dropped_connection_retry`, `attempt=1`, com o mesmo erro de conexão fechada;
- o request MCP correspondente terminou **200 em 174,9ms**;
- não houve `mcp_auth_error` nas revisões pós-fix.

Isso é a prova positiva que faltava no handoff de 22/07: o retry-com-reacquire recuperou exatamente o modo de falha real. Não há motivo atual para aumentar `attempts` nem reduzir novamente o lifetime.

## F77 — solução implementada

Em `src/app.py`, o deep health agora:

1. executa o `SELECT 1` por `connection.run_with_reconnect(...)`;
2. permite uma nova conexão na segunda tentativa;
3. envolve a operação inteira em `asyncio.timeout(5.0)`, abaixo dos 10s do uptime checker;
4. continua fail-closed: retorna 503 `db=error` se as duas tentativas falharem ou se o prazo estourar;
5. registra `error` e `exc_type` no warning final.

Não foi aplicado retry genérico a mutações: o probe é um read idempotente; uma mutação pode ter commitado antes de a conexão cair.

Regressões em `tests/unit/test_health_resilience.py`:

- stale→healthy: 200, `db=ok`, dois acquires;
- stale→stale: 503, `db=error`, dois acquires;
- operação lenta: deadline interno encerra com 503 antes do timeout externo.

## Verificação e deploy

- `python scripts/check_pre_push.py`: **5/5 PASS**;
- Docker/testcontainers indisponível localmente; integração DB passou no GitHub Actions;
- commit: `23fccfea3fcf3b18de65dc8a8c2f17c935775460`;
- CI/deploy: run `30047283991`, jobs `test` e `deploy` success;
- migrations: success; smoke: success; rollback: skipped;
- revisão: `v4-ads-mcp-00028-lvc`, 100% do tráfego;
- health pós-deploy: 200 às 21:49:19, 21:49:25 e 21:49:52 UTC;
- logs `severity>=ERROR` pós-deploy: zero na janela validada.

## Próxima sessão — ordem recomendada

1. **Ação humana time-sensitive (25/07):** reconectar o Meta OAuth pessoal do Wellington.
2. **Operacional:** cutover de `lucassoares` e `anderson`; só então decomissionar `v4-ads-mcp-prod`.
3. **Meta:** atribuir o system user às contas faltantes, especialmente CA-ROL GEAN `act_2399051240507488`.
4. **Produto:** decidir checkpoint de volume Meta e iniciar M.5 se mantida a prioridade; não tombstonar os 8 reports Google antes de novo soak real.
5. **Infra:** F67 custom domain via Load Balancer.
6. **CI:** smoke autenticado F58 segue dormente; rearmar apenas se desejado.

Não há follow-up ativo para F76/F77. Reabrir somente se surgir `mcp_auth_error` pós-`00026`, `health_deep_db_failed` persistente pós-`00028`, ou incidente do uptime check.

## Queries operacionais

```powershell
# Falhas do deep health
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="v4-ads-mcp" AND jsonPayload.event="health_deep_db_failed"' --project=v4-ads-mcp --freshness=14d --format="table(timestamp,resource.labels.revision_name,jsonPayload.error)"

# Prova/reincidência do retry
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="v4-ads-mcp" AND jsonPayload.event="db_dropped_connection_retry"' --project=v4-ads-mcp --freshness=14d --format="table(timestamp,resource.labels.revision_name,jsonPayload.attempt,jsonPayload.error)"

# Regressão do auth path
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="v4-ads-mcp" AND jsonPayload.event="mcp_auth_error"' --project=v4-ads-mcp --freshness=14d --format="table(timestamp,resource.labels.revision_name)"

# Errors na revisão atual
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.revision_name="v4-ads-mcp-00028-lvc" AND severity>=ERROR' --project=v4-ads-mcp --freshness=7d --format="table(timestamp,severity,jsonPayload.event,httpRequest.status)"
```
