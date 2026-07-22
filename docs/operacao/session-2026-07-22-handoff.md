# Sessão 2026-07-22 — Handoff (investigação de erros de produção → 2 fixes + refutação de hipótese)

> Thread contínua a partir do print da **Auditoria global** (filtro "só erros"): investigar os erros → refutar a tese "MCP corrompe acento" (do modelo que o Pedro usa) → destravar os deploys (smoke bearer morto) → **F76** (500 intermitente por conexão DB stale) → observabilidade (`level`→`severity`) → destravar o ruff local (Smart App Control). Tudo via TDD, CI+deploy verdes. Produção em **`v4-ads-mcp-00027-kmw`**, `/health?deep=1` db=ok.

## TL;DR

| Item | Entrega | Commits |
|---|---|---|
| **Investigação dos erros** | 3 categorias, **nenhuma é bug de código** — ver abaixo | — |
| **Regressão de acento (pin A7)** | Refutei a tese de encoding com prova byte-a-byte (builder + protobuf v24) + testes que travam UTF-8 nos RSA builders | `2909143` |
| **Deploy fail-well (smoke)** | Smoke autenticado derrubava TODO deploy (bearer morto) → hardened p/ skip em 401. **Smoke F58 agora DORMENTE** | `a60af7f` |
| **F76 — resiliência do pool DB** | 500 intermitente `mcp_auth_error` por conexão asyncpg stale (Supabase fecha idle). `run_with_reconnect` + `max_inactive_connection_lifetime` 300→120s | `ac5f25d`, `631d977` |
| **Observabilidade** | structlog emitia `level`; Cloud Run não elevava → alertas por severidade cegos. `add_cloud_logging_severity` espelha `level`→`severity` | `727c5ab` |
| **Doc** | F76 catalogado + sub-nota observabilidade | `52df8ad` + este handoff |

## Investigação dos erros (Auditoria global, 14d) — 3 categorias, 0 bug de código

- **(A) Reprovação de política Google (10 erros) — `create_rsa`/`update_rsa`, pedro.vytor.** `UNACCEPTABLE_SPACING, SYMBOLS` — o Google reprovou o **texto do anúncio** (espaçamento incomum / símbolos repetidos). MCP tratou certo (barrou + msg PT-BR). Contas: Carambeí `8621075294` (14/07) e `7621086021` (06/07, com 3 create + 1 update **com sucesso** intercalados → é copy, não bloqueio sistêmico). **Ação: do gestor (revisar copy), não do sistema.**
- **(B) GAQL malformada (2 erros) — wellington, `7862230676`.** `The following field must be present in SELECT clause: 'segments.conversion_action'` — filtra no WHERE um campo de segmento que não está no SELECT. `validate_gaql` pegou em 06/07; mesma query reapareceu no `run_gaql` 13/07. Erro de uso, guiado pela mensagem enriquecida (F62).
- **(C) Meta #200 (3 erros) — pedro.vytor, `act_2399051240507488` = "CA - ROL GEAN" (BM "MDO - ROL GEAN").** `(#200) Ad account owner has NOT grant ads_management or ads_read`. A matriz interna concede a **4 gestores** (desde 19/06), mas o **system-user compartilhado NÃO está atribuído a essa conta no BM** → gap do Modelo B. É a **4ª conta faltante** (além de ML Antiguidades/MDO Pinda/`act_34358720650393626`). Teve **1 leitura OK em 01/07**, falha desde então. **Ação: atribuir o SU no BM (humana).** Bônus shipado: `to_friendly_meta_error` **não trata `code==200`** → gestor vê texto cru em inglês (candidato a melhoria futura; não feito).

## F76 — o fix principal (validado firsthand nos logs)

- **Root cause:** Cloud Run mantém conexões asyncpg ociosas no pool; o Supabase fecha o socket idle; o próximo request pega a conexão morta e `mcp_sessions.find_by_hash` levanta `ConnectionResetError [Errno 104]` → `asyncpg.ConnectionDoesNotExistError` no _statement prep_ → 500 (`mcp_auth_error`). **~5 em 14 dias, TODOS no auth path, desde 2026-07-09** (revisões `00020`/`00025`, pré-fix) — não é regressão de deploy (código/deps inalterados). Fail em ~14ms (falha imediata, não timeout downstream).
- **Fix (`src/db/connection.py`):** `run_with_reconnect(op, attempts=2)` readquire uma conexão **NOVA** e re-roda o op idempotente em `(asyncpg.PostgresConnectionError, ConnectionError)`; `UnauthorizedError`/query-errors propagam sem retry. `resolve_session_to_context` embrulha o lookup nele (read → seguro). `max_inactive_connection_lifetime` 300s (default asyncpg) → **120s** pra reap idle antes do remoto matar.
- **TDD (Docker-free):** helper (recover / no-retry-em-app-error / reraise-após-esgotar) + `init_pool` bounded lifetime + recovery na resolução de sessão. `tests/unit/test_db_connection.py` + `test_mcp_session.py`.
- **Validação Gemini Cloud Assist:** o root cause do Gemini estava **certo**; a remediação **não** (sugeriu SQLAlchemy `pool_pre_ping` — projeto é asyncpg cru; `max_inactive_connection_lifetime=300` — já é o default → no-op; retry `tenacity` **reusando a mesma conn morta** → falharia igual). O par correto pra raw asyncpg é retry-com-**reacquire** + lifetime < idle-timeout do remoto.

## Observabilidade — `level`→`severity` (`727c5ab`)

`log.exception("mcp_auth_error")` sai com `jsonPayload.level=error`, **mas** a *entry severity* do Cloud Run fica `DEFAULT` (structlog emite `level`, não `severity`) → alertas por severidade (do pacote 07-04) **não pegavam** esses 500 (por isso passaram ~2 semanas). Processor `add_cloud_logging_severity` em `src/logging.py` espelha `level`→`severity` (só no pipeline JSON, depois do `add_log_level`, antes do renderer); console inalterado. `_build_processors()` extraído pra testabilidade. Verificado end-to-end: log renderizado carrega `"severity":"ERROR"`.

## Ambiente de dev — ruff/SAC (resolvido)

**Smart App Control** (Win11 Home, build 26200) bloqueava o `ruff.exe` (binário Rust **unsigned**) via Code Integrity (eventos 3077/3033: "did not meet the Enterprise signing level requirements"). Efeito: `check_pre_push` não rodava ruff local → o `UP047` (PEP 695 type params) só apareceu no CI, exigindo 1 fix-forward (`631d977`). Diagnóstico via PowerShell (SAC `VerifiedAndReputablePolicyState=1`, ruff `NotSigned`). **Wellington desligou o SAC** (é porta de mão única — só religa resetando o Windows). `check_pre_push` completo (ruff+format+mypy+unit+non-DB) volta a rodar local; **testcontainers ainda não** (Docker não instalado nesta máquina — coberto pelo CI).

## Pendente / follow-ups

1. **[TIME-SENSITIVE] Verificar a taxa de `mcp_auth_error` em D+1/D+2 (23-24/07, após janela ociosa).** O retry está no ar desde `00026` (15:41 UTC 22/07). Em ~2h só houve tráfego quente (43×200, 0×500 nas revisões pós-fix), o gatilho (conexão **ociosa**) não ocorreu, `db_dropped_connection_retry`=0. Os 5 eventos históricos foram em **baixo tráfego** (03:31/04:26/21:xx) → o teste real é após a madrugada ociosa. **Sinais:** `db_dropped_connection_retry`>0 = prova positiva (retry recuperou); `mcp_auth_error` em `00026`+ = raro caso das 2 tentativas falharem (subir `attempts`/baixar lifetime). Queries (gcloud authed `wellington.ribeiro@`):

```bash
# taxa de 500 (baseline 5/14d, todos pré-fix em 00020/00025):
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="v4-ads-mcp" AND jsonPayload.event="mcp_auth_error"' --project=v4-ads-mcp --freshness=14d --format="value(timestamp,resource.labels.revision_name)"
# prova positiva (o retry pegou uma conexão morta e recuperou):
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="v4-ads-mcp" AND jsonPayload.event="db_dropped_connection_retry"' --project=v4-ads-mcp --freshness=14d --format="value(timestamp,resource.labels.revision_name)"
```
2. **Meta #200 — atribuir o SU (`v4-ads-mcp-integracao`) à conta CA-ROL GEAN** (`act_2399051240507488`, BM "MDO - ROL GEAN") com `ads_read`/`ads_management`. Consolidar com o item 4 do CLAUDE.md (contas Meta faltantes).
3. **Smoke F58 dormente** — recriar gestor smoke sem grants + repor `SMOKE_MCP_BEARER` no GitHub se quiser re-armar (a lógica fail-well re-arma sozinha). Memory: `ci-smoke-bearer-dormant-2026-07`.
4. **(Opcional) `to_friendly_meta_error` p/ `code==200`** — mensagem PT-BR "conta interna sem acesso no BM, peça pro admin" em vez do texto cru.

## Convenções novas (também no CLAUDE.md)

- **DB hot-path resiliente:** use `connection.run_with_reconnect(op)` pra reads idempotentes — asyncpg **não faz pre-ping**; conexão fechada pelo remoto só falha no próximo statement. NÃO reusar a mesma conn no retry (readquirir do pool). Mutações NÃO devem ter retry cego (podem ter commitado). Ver F76.
- **Logs Cloud Logging:** `severity` (não `level`) é o campo que o Cloud Run eleva; `add_cloud_logging_severity` já cobre — qualquer novo pipeline JSON deve mantê-lo antes do renderer.
