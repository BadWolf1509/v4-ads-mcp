# Resync com um cliente só — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** fazer o resync diário sair com 0 num projeto de um cliente só, sem tocar no teto de segurança.

**Architecture:** três partes independentes:
- uma trava de configuração (Meta);
- a revogação de credencial no desligamento, mais um backfill;
- um comando de descomissionamento auditado.

Os comandos ficam no `src/scripts/admin.py`.

**Tech Stack:** Python 3.13, asyncpg, pytest (unit), testcontainers (integration).

**Spec:** `docs/superpowers/specs/2026-11-25-resync-um-cliente-design.md`

## Global Constraints

- `meta_habilitada` tem padrão `True`.
- Motivos de revogação: só os existentes (`motivos.LEFT_MCC_REASON` e `motivos.PARTNERSHIP_ENDED_REASON`).
- Comandos `admin` novos: dry-run por padrão, `--apply` para escrever e audit com `had_effect` (F179).
- **Nunca** apagar linha.
- Status do audit ∈ {success, error, denied}.

## Review Focus

1. `--manter-google` com id inexistente ou inativo → recusa, sai com 2 e não escreve nada. Teste na Task 3.
2. Descomissionar duas vezes → a segunda não muda nada e o audit sai com `had_effect=false`. Teste na Task 3.
3. Toggle de **reativação** → não restaura conexões OAuth. Teste na Task 2.
4. Meta desligada **com** BM configurado → continua desligada (a trava vence). Teste na Task 1.
5. Gestor ativo com conexão viva → o backfill não toca. Teste na Task 2.

---

### Task 1: Meta desligada explícita

**Files:**
- Modify: `src/config.py`
- Modify: `src/jobs/account_resync.py` (`_etapa_meta`)
- Modify: `.github/workflows/deploy.yml`
- Test: `tests/unit/test_account_resync_meta_desligada.py`
- Test: `tests/unit/test_deploy_sem_literais_do_projeto.py`

**Testes:**
- `test_meta_desligada_grava_audit_e_nao_falha`:
  - env `META_HABILITADA=false`;
  - `reconcile_meta` não é chamado;
  - `record_job_run` é chamado com `operation="meta_reconcile"`, `status="success"` e `params_summary={"desligada": True}`;
  - retorno `False`.
- `test_meta_desligada_vence_bm_configurado`: o mesmo cenário com `META_BUSINESS_ID=123`.
- `test_meta_habilitada_por_padrao_chama_reconcile`.
- `test_deploy_passa_meta_habilitada`: `META_HABILITADA=${{ vars.META_HABILITADA || 'true' }}` aparece no `--set-env-vars` do serviço e no `JOB_ENV_VARS`.

- [ ] Escrever os testes e vê-los falhar → implementar → ver passar → commit `fix(ci): Meta desligada explícita não derruba o resync`.

### Task 2: Desligamento revoga conexões OAuth, mais o backfill

**Files:**
- Modify: `src/db/repositories/google_oauth_connections.py`
  - novo: `revoke_all_for_manager(conn, manager_id: UUID) -> int`
  - novo: `list_live_of_inactive_managers(conn) -> list[asyncpg.Record]`
- Modify: `src/web/routes/admin_overview.py` — ramo `elif mudou:` soma `conexoes_revogadas`.
- Modify: `src/scripts/admin.py` — subcomando `revogar-conexoes-de-inativos [--apply]`.
- Test: `tests/integration/test_revogar_conexoes_db.py` (DB)
- Test: o teste de rota existente do toggle (unit), se houver.

**Testes (DB):**
- `revoke_all_for_manager` revoga só as conexões vivas daquele gestor e devolve a contagem.
- `list_live_of_inactive_managers` ignora gestor ativo e conexão já revogada.
- `cmd_revogar_conexoes_de_inativos`:
  - sem `--apply` não escreve;
  - com `--apply` revoga e grava `cli_revoke_inactive_connections` com `had_effect` correto;
  - a segunda rodada sai com `had_effect=false`.
- Toggle desativar → as conexões do alvo ficam com `revoked_at` não nulo.
- Toggle reativar → as conexões continuam revogadas.

- [ ] TDD → commit `fix(auth): desativar gestor revoga as conexões OAuth dele`.

### Task 3: Descomissionamento

**Files:**
- Modify: `src/scripts/admin.py` — subcomando `descomissionar --manter-google ID [ID…] --manter-meta ID [ID…] [--apply]`.
- Test: `tests/integration/test_descomissionar_db.py` (DB)

**Comportamento:**
- **Validação:** cada id de `--manter-*` tem de ser uma conta ativa do inventário. Senão, imprime quais não são e sai com 2, sem escrever nada.
- **Dry-run:** imprime as contas ativas fora da lista (Google e Meta) e a contagem de grants vivos nelas.
- **`--apply`:** numa transação:
  - `google_ads_accounts.deactivate(fora)`;
  - `manager_account_access.revoke_for_inactive_accounts(reason=LEFT_MCC_REASON)`;
  - `meta_ad_accounts.deactivate(fora)`;
  - `manager_meta_account_access.revoke_for_account(reason=PARTNERSHIP_ENDED_REASON)` para cada conta Meta fora da lista;
  - `audit_log.record(operation="cli_decommission", had_effect=<algo mudou>)`, com contagens.

**Testes (DB):**
- Recusa um id de `--manter-google` desconhecido (rc 2, nada muda).
- O dry-run não escreve.
- O `--apply` desativa só as de fora e revoga só os grants nelas. A mantida conserva os grants.
- A segunda rodada tem `had_effect=false`.

- [ ] TDD → commit `feat(admin): descomissionar contas fora do escopo com trilha`.
