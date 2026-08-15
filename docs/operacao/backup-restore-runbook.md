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
2. **Descompactar** cada `.csv.gz` (gzip).
3. **Restaurar via `COPY FROM`** com um script Python + asyncpg (padrão do projeto — sem psql). Ordem importa por causa das FKs: restaure na ordem de criação das tabelas (`managers` → `google_oauth_connections`/`google_ads_accounts`/`mcp_sessions` → `manager_account_access`/`pending_confirmations`/`audit_log`/`rate_counters` → tabelas Meta). Cada tabela:
   ```python
   # por tabela, contra um DB LIMPO (schema já migrado via `python -m src.db.migrate`):
   with open("managers.csv", "rb") as f:
       await conn.copy_to_table("managers", source=f, format="csv", header=True)
   ```
   Colunas `BYTEA` (ex. `google_oauth_connections.refresh_token_enc`) são serializadas pelo Postgres em hex (`\x...`) no CSV e re-lidas corretamente pelo `COPY FROM ... FORMAT CSV` — sem transformação no meio.
4. **Validar:** `SELECT count(*)` por tabela vs o esperado; `/health?deep=1` db=ok; um login no painel + um `tools/list` autenticado.

> ⚠️ **Chaves de cifra:** os refresh tokens no backup foram cifrados com a `aes-master-key` VIGENTE no momento do dump. Restaurar num ambiente com chave diferente (ex. projeto novo pós-migração) → os tokens não decifram e os gestores precisam reconectar (mesma dinâmica da migração 2026-06-30 / F70). O backup preserva o dado cifrado, não a chave — a `aes-master-key` vive no Secret Manager e deve ser tratada como parte do DR.

## Teste de restore (fazer 1× e sempre que o schema mudar muito)

Contra um Postgres descartável (testcontainer local com Docker, OU um DB temporário no Supabase):
1. `python -m src.db.migrate` no DB limpo (cria o schema).
2. Restaure 1 tabela pequena com FK (ex. `google_oauth_connections`, que depende de `managers`) seguindo os passos acima.
3. Confirme count + que o `refresh_token_enc` (BYTEA) sobreviveu ao roundtrip (decifra com a chave correspondente).

## Alertas relacionados (Onda 2.1)

- **Job failed:** a policy `Cloud Run Job: execucao FALHOU` cobre `v4-ads-mcp-backup` (metric `run.googleapis.com/job/completed_execution_count{result=failed}`) → e-mail pro Wellington. Um backup que falhar semanalmente NÃO passa despercebido.
