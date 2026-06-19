# Handoff — Sessão 2026-06-19 (recuperação de conta + Meta 12→22 + GAQL error UX + resync Meta)

> Sessão **operacional** (não-sprint): recuperação pós-exclusão da conta admin antiga + escala do portfólio Meta + hardening de UX de erro GAQL + automação de resync. Estado: prod verde em `84024a5`, `/health` 200. Sem novo MCP tool (fixes + 1 Cloud Run Job).
>
> **Contexto:** repo clonado em `D:\v4-ads-mcp` numa máquina nova — sem Python/gh/gcloud (instalados na sessão: Python 3.13 + venv + deps, gh 2.95, gcloud 573).

## O que mudou (5 workstreams)

1. **Recuperação da conta admin** — a conta antiga `wellinton.ribeiro@v4company.com` (typo, sem 'g') foi **EXCLUÍDA** no Google → Google OAuth refresh token morto (`invalid_grant: Account has been deleted`) + manager `not_invited` no painel. Fix via Supabase SQL Editor: `UPDATE managers SET email='wellington.ribeiro@v4company.com'` no **mesmo** `manager_id` (`fc67c099-...`) → grants/sessões MCP/audit_log preservados; revoke das `google_oauth_connections` mortas; re-login do painel re-gravou o refresh token Google. Bearer MCP inalterado (amarrado ao manager_id).

2. **Portfólio Meta 12 → 22 contas** — três camadas: (a) **F61** fix de paginação em `/me/adaccounts` (`_fetch_all_adaccounts` segue `paging.next`); (b) re-sync no painel `/admin/accounts/meta` ("Sincronizar contas") → inventário `meta_ad_accounts` 12→22 (o system user `v4-ads-mcp-integracao`, id `61590110716028`, Admin, **alcança o portfólio** — não precisou atribuir conta a conta); (c) grants Modelo B em `/admin/access/meta` ("Selecionar todas pra gestor") pros 4 gestores → todos com 22 (Anderson `invited`, ativa no 1º login). Verificado: MCP `meta_list_my_ad_accounts` 12→22 + spot-check de `meta_get_account_overview` numa conta nova (Pinda) = success.

3. **GAQL error UX (F62/F63)** — investigação dos erros do Pedro no `audit_log` (via Supabase MCP) revelou que eram **queries inválidas do cliente Codex** (auction insights `metrics.search_overlap_rate`/etc inexistentes na GAQL + `get_change_history` >30 dias), não bug do MCP. Hardening: `to_friendly` (`errors.py`) trata o oneof `query_error` (mantém o campo cru + dica `list_gaql_resources`/`validate_gaql`); descrição do `run_gaql` orienta validar antes; `get_change_history` clampa `start_date` custom (não só preset) pro teto de 30 dias.

4. **Cleanup pós-migração** — `BOOTSTRAP_ADMIN_EMAILS=wellington.ribeiro@v4company.com` no `deploy.yml --set-env-vars` (estava **vazio** em prod → DR footgun se a tabela `managers` esvaziar); e-mail de contato LGPD nos templates legais (`privacy`/`terms`/`data_deletion` apontavam pra conta excluída) + `CLAUDE.md` + `admin.py`.

5. **Resync Meta agendado** — `src/jobs/meta_resync.py` (`resync_meta()`) é chamado no fim do `account_resync` (mesmo Cloud Run Job `v4-ads-mcp-resync` + Cloud Scheduler diário) → `meta_ad_accounts` atualizado zero-touch quando entra cliente novo. `META_SYSTEM_USER_TOKEN` montado no job via `deploy.yml --update-secrets` (deploy SA aplica). Best-effort (no-op se token ausente; falha Meta não quebra o resync Google). Grants seguem manuais (Modelo B).

## Findings novos

**F61** (paginação Meta `/me/adaccounts`) · **F62** (`run_gaql` QUERY_ERROR não acionável) · **F63** (`get_change_history` custom-date não clampava). Detalhe: [findings-catalog.md](findings-catalog.md).

## Lições

- **Single point of failure de conta = risco real.** A conta admin antiga era owner do GCP + único manager admin; ao ser excluída, travou Google Ads (token), painel (manager) e GCP (IAM). **Peça 2 owners humanos** (GCP + manager) sempre. (Eco da lição RotaMestre de 3 contas perdidas.)
- **Inventário ≠ acesso (Modelo B by-design).** `meta_list_my_ad_accounts` filtra por grant (`manager_meta_account_access`), não pelo inventário — re-sync enche o inventário mas grants são opt-in manual.
- **Erros de cliente LLM precisam de mensagem auto-corretiva.** Codex chutava campos GAQL e repetia o erro 11× porque a mensagem crua do Google não apontava a correção; enriquecer o erro (→ `list_gaql_resources`) fecha o loop pra qualquer cliente.
- **CI/CD least-privilege é bom — e fecha auto-recuperação de IAM.** A deploy SA não pode habilitar API nem conceder IAM (verificado via workflow break-glass efêmero, depois removido). Boa segurança, mas a recuperação de IAM da conta nova exige um Org Admin V4 (`roles/owner` via Console → IAM).

## Validação

- **CI + Deploy verdes** em todos os commits (`17a8145`, `653e724`, `ee4dde0` + commits de docs). Confirmado via `gh run view <id> --json conclusion`.
- **`check_pre_push` 5/5** local em cada code change (toolchain instalada na sessão).
- **Smoke em prod:** MCP `meta_list_my_ad_accounts` retorna 22; `meta_get_account_overview` numa conta nova = success; `run_gaql` com campo inválido retorna a mensagem enriquecida (F62).
- **DB introspection** via Supabase MCP: 4 managers × 22 grants Meta confirmados.
