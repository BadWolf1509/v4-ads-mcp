# Sessão 2026-06-30 — Handoff

> Investigação: "por que nem todas as contas parceiras do BM `619664032237208` aparecem no MCP?" → diagnóstico fechado (F64 + F65) + avaliação de migração GCP. **Nenhum código alterado** (diagnóstico via probes read-only com token temporário). Próximo nó é operacional/infra, não código.

## TL;DR

1. **F64 — contas faltando:** o sync Meta usa `/me/adaccounts`, que é **token + app-scoped**. O token de produção (`meta-system-user-token` no GCP, app **V4 Ads MCP** `1522411803012799`) foi gerado com **lista FIXA de contas** (granular `ads_management` com `target_ids`, não `all targets`) → **contas novas não entram** até o token ser regenerado com "todas as contas atuais e futuras". A atribuição do system-user está correta; o token é que está velho.
2. **F65 — cache inflado:** `resync_meta` nunca chama `mark_inactive_except` (o lado Google chama) → o cache `meta_ad_accounts` acumula órfãs (conta pessoal do Wellington, WJX fechada, etc.). Fix = Onda 5.
3. **Gargalo:** regravar o token no GCP exige acesso ao **Secret Manager** = o **IAM GCP pendente**. Avaliada a migração de projeto: **não recomendada** — o grant de IAM no projeto atual resolve com 1/15 do esforço e ~zero risco (ver §Migração).

## Topologia Meta confirmada (empírica, via `debug_token`/`/me`)

- **1 system-user** só: `v4-ads-mcp-integracao`, ID real `61590110716028`.
  - ⚠️ `/me` retorna **app-scoped IDs (ASIDs)** distintos por app (`122108…`, `122103…`) — *parecem* SUs diferentes mas são o mesmo. Não confiar em `/me .id` pra contar SUs; use o ID do Business Manager.
- **3 apps Meta** (developers.facebook.com):
  - **V4 Ads MCP** `1522411803012799` (Ativo) = **produção**. Token fresh deste app, com `ads_management`/`ads_read`/`business_management` em **all targets**, enxerga tudo (incl. `CA - MDO Goiânia`).
  - V4 MDO Stories `4419481288293195` (Em desenvolvimento) — **sem** scopes `ads_*` (token antigo do BTW falhava com "Missing Permissions").
  - WJX `1430576745025253` (Ativo, empresa WJX).
- **owned_ad_accounts do BM = 0** → a V4 não tem contas próprias; tudo é parceria/cliente.
- **Números:** `client_ad_accounts` (universo do BM) = **21**; token de produção via `/me/adaccounts` reflete **18→19** (cache MCP mostra 22, mas inflado por órfãs — ver F65).

### Conta ativa que motivou tudo
`CA - MDO Goiânia` (`act_1292624998332379`, ATIVA) — atribuída ao SU (Acesso total, confirmado no painel), mas ausente do `/me/adaccounts` de produção por causa do token com targets fixos (F64). As outras 2 faltantes (`CHUTE 07`, `Mestre da obra JP`) estão FECHADAS — irrelevantes.

## Próximos passos (ordem)

1. **Destravar IAM GCP** — pedir ao Org Admin V4 o grant no projeto `v4-ads-mcp-prod` (pacote pronto: ver §IAM). Destrava o Secret Manager (e rollback/Cloud Run manuais).
2. **Regenerar o token de produção** no app *V4 Ads MCP*, system-user `v4-ads-mcp-integracao`, marcando **"todas as contas, atuais e futuras"** → gravar como nova versão de `meta-system-user-token` no GCP → re-rodar o resync. Resolve F64 e qualquer cliente futuro automaticamente.
3. **Onda 5 (código)** — plugar `mark_inactive_except` no `resync_meta`, agrupado por `business_id`. Resolve F65 (limpa as órfãs). Deploy via push (não bloqueado por IAM). Abrir com `brainstorming`.

## Migração GCP — avaliação (não recomendada agora)

Gatilho seria o IAM travado. Mas migrar exige o **mesmo Org Admin** que poderia simplesmente conceder owner no projeto atual (1 comando vs ~15 passos). Risco-chave: a `aes-master-key` cifra os refresh tokens OAuth no Supabase — sem extraí-la do projeto atual (o que o IAM travado impede), migrar força **reconexão OAuth em massa** dos gestores. Inventário do que migraria: Cloud Run + 2 Jobs + Scheduler + Artifact Registry + Cloud Build + SAs + WIF + 13 secrets + OAuth redirect URIs + `~/.claude.json` de cada cliente. DB (Supabase) é externo, não migra. **Migrar só se** o org atual for genuinamente inacessível ou por decisão estratégica (billing/governança próprios). Perguntas em aberto: motivação real? Org Admin acessível? Backup da `aes-master-key`/`session-signing-key` fora do GCP?

## IAM — pacote pro Org Admin V4

Conta a habilitar: `wellington.ribeiro@v4company.com` · Projeto: `v4-ads-mcp-prod`.

```bash
# Mínimo pra ler/gravar secrets (destrava o token Meta):
gcloud projects add-iam-policy-binding v4-ads-mcp-prod \
  --member="user:wellington.ribeiro@v4company.com" \
  --role="roles/secretmanager.admin"

# Recomendado pra ops completas (Cloud Run, rollback, jobs, logs):
gcloud projects add-iam-policy-binding v4-ads-mcp-prod \
  --member="user:wellington.ribeiro@v4company.com" \
  --role="roles/owner"
```

Contexto: a conta admin original (owner) foi excluída; a atual tem ZERO IAM no projeto. Deploys (WIF/`GCP_DEPLOY_SA`) funcionam, mas ops manuais (secrets, Cloud Run, rollback) não. Detalhe histórico: [session-2026-06-19-handoff.md](session-2026-06-19-handoff.md).

## Higiene pendente

- **Revogar o access token do Bitwarden Secrets Manager** que o Wellington compartilhou nesta sessão (usado só pra probes read-only; nenhum secret foi impresso).
- Bitwarden tem **2 secrets "Meta"**: `7ffe144d…` (app V4 Ads MCP, all-targets, bom) e `e9281039…` (app V4 MDO Stories, sem `ads_*`). Considerar remover o segundo pra não confundir.
