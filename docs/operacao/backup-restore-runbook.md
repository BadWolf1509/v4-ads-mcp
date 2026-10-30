# Backup & Restore — runbook (V4 Ads MCP)

> DR do DB Supabase (Postgres). O DB guarda refresh tokens cifrados, a matriz de acesso e o audit trail de compliance — perder o DB é o pior cenário do sistema. Este runbook cobre o backup automático semanal e o restore manual.

## O que existe

- **Job:** Cloud Run Job `v4-ads-mcp-backup` (projeto `v4-ads-mcp`, região `southamerica-east1`), process `/cnb/process/backup` (código em [`src/jobs/backup.py`](../../src/jobs/backup.py)).
- **Schedule:** Cloud Scheduler `v4-ads-mcp-backup-weekly` — **domingo 05:00 BRT** (`0 5 * * 0`, `America/Sao_Paulo`), invoca o job via SA `v4-ads-mcp-scheduler` (mesma do resync diário).
- **Destino:** `gs://v4-ads-mcp-backups/<YYYY-MM-DD>/<tabela>.csv.gz` — um CSV gzipado por tabela do schema `public` (inclui `_migrations`). Bucket com **lifecycle: delete > 90 dias** (UBLA, southamerica-east1).
- **Auditoria:** cada execução grava `audit_log` via `record_job_run(operation="db_backup")` — visível no painel `/audit` e coberto pelo alerta de job-failed (Onda 2.1).
- **Retenção:** 90 dias no GCS (o `audit_log` em si NÃO é purgado — decisão de compliance, ver `purge.py`).

O job usa a SA de runtime `v4-ads-mcp-runtime` (tem `roles/storage.objectCreator` no bucket) e lê `DATABASE_URL` do Secret Manager. Sem credenciais explícitas (ADC).

## Rodar um backup sob demanda

```powershell
gcloud run jobs execute v4-ads-mcp-backup --project=v4-ads-mcp --region=southamerica-east1 --wait
# conferir os objetos gerados:
gcloud storage ls "gs://v4-ads-mcp-backups/$(Get-Date -Format yyyy-MM-dd)/"
```

## Restore (manual — sem psql no Windows)

O restore é **manual e deliberado** (não há automação — restore automático é perigoso).

> **Integridade referencial (desde 2026-08-15, F94):** todas as tabelas de uma pasta de data vêm do **mesmo snapshot** — o job usa uma conexão numa transação `REPEATABLE READ` pra descobrir e dumpar tudo. Antes, cada tabela era dumpada num momento diferente, então uma linha criada no meio do run gerava FK órfã (ex.: `mcp_sessions.manager_id` sem a linha correspondente em `managers.csv`, porque `managers` vem antes na ordem alfabética) e o restore quebrava no meio. **Se a pasta tiver menos arquivos que o esperado, não complete com outra data** — o `params_summary.failed_tables` do `audit_log` diz o que faltou, e misturar datas recria justamente o problema que o snapshot resolve.

Passos:

1. **Baixar** o snapshot do dia desejado:
   ```powershell
   gcloud storage cp -r "gs://v4-ads-mcp-backups/2026-07-04/*" .\restore\
   ```
2. **Não precisa descompactar:** o módulo do passo 3 lê `.csv.gz` direto.
3. **Restaurar** contra um DB **limpo** com o schema já migrado (`python -m src.db.migrate`):
   ```powershell
   python -m src.jobs.restore .\restore\ --confirmar-host <host-do-DATABASE_URL>
   ```
   **Duas travas:** o `--confirmar-host` é obrigatório e tem de bater com o host do `DATABASE_URL` em uso (sem ele, ou com host diferente, sai com código 2 mostrando o host — nunca usuário/senha — antes de conectar); e o módulo **recusa destino não vazio** (qualquer tabela com linha), sem alterar nada. O módulo ([`src/jobs/restore.py`](../../src/jobs/restore.py)) restaura na ordem de FK (`managers` → `google_oauth_connections`/`google_ads_accounts`/`mcp_sessions` → `manager_account_access`/`pending_confirmations`/`audit_log`/`rate_counters` → tabelas Meta), **numa transação só**, e recusa pasta incompleta ou com tabela fora da ordem **antes** do primeiro COPY. Três coisas que o procedimento manual antigo errava e o módulo faz:
   - **Pula `_migrations`**: o dump a inclui, mas ela conflita com o schema já migrado.
   - **Recoloca a sequence do `audit_log`** (`setval` no fim; única tabela com SERIAL). Sem isso o COPY grava `id` explícito, a sequence fica em 1 e o INSERT seguinte do app falha com `UniqueViolationError (id)=(1)` — medido em Postgres 16.
   - **COPY sem `command_timeout`** (`timeout=None`): o limite padrão de 30 s do pool não vale para uma tabela grande.

   Colunas `BYTEA` (ex. `google_oauth_connections.refresh_token_enc`) são serializadas pelo Postgres em hex (`\x...`) no CSV e re-lidas corretamente pelo `COPY FROM ... FORMAT CSV` — sem transformação no meio.
4. **Validar:** `SELECT count(*)` por tabela vs o esperado; `/health?deep=1` db=ok; um login no painel + um `tools/list` autenticado.

> ⚠️ **Chaves de cifra:** os refresh tokens no backup foram cifrados com a `aes-master-key` VIGENTE no momento do dump. Restaurar num ambiente com chave diferente (ex. projeto novo pós-migração) → os tokens não decifram e os gestores precisam reconectar (mesma dinâmica da migração 2026-06-30 / F70). O backup preserva o dado cifrado, não a chave — a `aes-master-key` vive no Secret Manager e deve ser tratada como parte do DR.

## Teste de restore (fazer 1× e sempre que o schema mudar muito)

Contra um Postgres descartável (testcontainer local com Docker, OU um DB temporário no Supabase):
1. `python -m src.db.migrate` no DB limpo (cria o schema).
2. Rode `python -m src.jobs.restore <pasta> --confirmar-host <host>` (passo 3 acima) e confira as contagens que ele imprime.
3. Confirme que o `refresh_token_enc` (BYTEA) sobreviveu ao roundtrip (decifra com a chave correspondente) e que um INSERT em `audit_log` funciona (a sequence foi recolocada).

O roundtrip completo (dump → restore → contagens → INSERT no `audit_log`) é coberto por `tests/integration/test_backup_restore.py`.

## Alertas relacionados (Onda 2.1)

- **Job failed:** a policy `Cloud Run Job: execucao FALHOU` cobre `v4-ads-mcp-backup` (metric `run.googleapis.com/job/completed_execution_count{result=failed}`) → e-mail pro Wellington. Um backup que falhar semanalmente NÃO passa despercebido.
