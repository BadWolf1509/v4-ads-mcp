# V4 Ads MCP — Design Spec

**Data:** 2026-05-03
**Autor:** Wellinton Ribeiro (V4 Company) + Claude (Opus 4.7)
**Status:** Draft — aguardando review do usuário

---

## 1. Visão geral

MCP server remoto que dá ao Claude (e demais clientes MCP — Codex, Cursor, etc.) controle nativo, read + write, sobre contas Google Ads (Fase 1) e Meta Ads (Fase 2). Substitui o uso de Supermetrics na V4 Company com auditoria, governança e custo operacional menor.

**Objetivo de negócio:** permitir que gestores da V4 manipulem campanhas em linguagem natural, com rastreabilidade no Change History do Google e segurança contra erros destrutivos.

**Escopo deste spec:** apenas Google Ads. Meta entra em spec próprio depois.

---

## 2. Decisões fundamentais

| Tópico | Decisão |
|---|---|
| Substituir Supermetrics | Sim — leitura + escrita nativas via Google Ads API |
| Modelo de usuários | 1 MCC + vários gestores (escala pra multi-MCC) |
| Deploy | MCP remoto via Streamable HTTP |
| Plataforma | Google Ads primeiro, Meta depois |
| Stack | Python 3.12 + `google-ads` SDK oficial + FastAPI + MCP Python SDK |
| Escopo write MVP | Robusto: campanhas, ad groups, KWs, negativas, RSAs, extensões, audiências, conversões, bulk via GAQL, recommendations (~25 tools) |
| Escopo read MVP | 16 ferramentas curadas + `run_gaql` escape hatch |
| Auth | OAuth por gestor (rastreabilidade no Change History) |
| Hospedagem | Cloud Run (region SP) + Supabase Free (com mitigações) → Pro depois |
| Domínio | `*.run.app` no MVP, custom depois |
| Onboarding | Painel web servido pelo próprio FastAPI (Supabase Auth restrito @v4company.com) |
| Idioma | PT-BR |
| Audit log | Metadata de toda mutação, 30d Postgres + Parquet em GCS |
| Rate limit | Aviso em 80%, bloqueia em 100% (15k ops/dia/developer token) |
| Freio de operações | Por blast radius (>5 entidades ou orçamento/lance pede confirmação) |
| Compatibilidade clientes | Claude Desktop/Code, Codex, Cursor (qualquer cliente MCP HTTP) |
| Design system | V4 Company brand book — light-first, Montserrat (fallback de Proxima Nova), símbolo "V4" |

---

## 3. Arquitetura: monolito FastAPI

Único serviço Cloud Run servindo `/mcp` (transporte MCP Streamable HTTP), `/oauth/google/*`, e o painel web. Camadas internas isoladas pra permitir refatoração futura em microserviços sem custo agora.

### 3.1 Componentes internos

```
src/
├── app.py                    # FastAPI bootstrap, monta rotas /mcp, /, /oauth
├── config.py                 # Settings (env vars, validação Pydantic)
├── mcp/
│   ├── server.py             # Servidor MCP (Streamable HTTP transport)
│   ├── session.py            # Resolve Bearer token → user/account context
│   └── tools/                # 1 arquivo por tool (read e write)
│       ├── account_overview.py
│       ├── campaign_performance.py
│       ├── ... (16 read + ~20 write tools)
│       ├── run_gaql.py
│       └── _registry.py      # Auto-registra todas as tools no servidor
│
├── google_ads/               # Wrapper sobre google-ads SDK
│   ├── client.py             # Factory: monta GoogleAdsClient com refresh_token do gestor
│   ├── queries/              # GAQL templates parametrizados (1 por tool de leitura)
│   ├── mutates/              # Operations builders (1 por tipo de mutação)
│   └── errors.py             # Traduz GoogleAdsException → erros amigáveis PT-BR
│
├── auth/
│   ├── oauth.py              # Flow OAuth Google (autorize/callback/refresh)
│   ├── tokens.py             # Encrypt/decrypt refresh_tokens (AES-GCM, chave Secret Manager)
│   ├── sessions.py           # Bearer tokens MCP (geração, validação, revogação)
│   └── supabase_auth.py      # Login do painel via Supabase Auth (Google SSO V4)
│
├── governance/
│   ├── blast_radius.py       # Calcula impacto, decide se exige confirmação
│   ├── dry_run.py            # Gera preview + token de confirmação curto
│   ├── rate_limit.py         # Contador diário por dev token, alertas 80%/100%
│   └── audit.py              # Append-only log de toda mutação
│
├── web/
│   ├── routes.py             # /, /sessions, /accounts, /audit, /admin/*
│   ├── templates/            # Jinja2
│   └── static/               # v4-tokens.css, v4-base.css, v4-components.css, fonts/, logo/
│
├── jobs/                     # Cloud Run Jobs (entrypoints)
│   ├── audit_rotation.py
│   ├── account_resync.py
│   ├── db_keepalive.py
│   └── session_cleanup.py
│
└── db/
    ├── connection.py         # asyncpg pool
    ├── migrations/           # SQL puro, versionado (sem ORM)
    └── repositories/         # 1 por agregado (managers, sessions, audit, rate_counters)
```

### 3.2 Princípios de boundaries

- `governance/`, `auth/`, `google_ads/` **não importam de `mcp/` nem de `web/`** — domínio puro, reusável amanhã num backend Core.
- `mcp/tools/` é "1 arquivo, 1 tool". Cada tool faz só: validar input → chamar `governance` → chamar `google_ads` → registrar `audit` → formatar response.
- `web/` é Jinja2 + CSS puro V4 (sem build step JS, sem Tailwind).
- `db/` usa SQL puro com `asyncpg` (sem ORM); schema é pequeno e estável.

---

## 4. Modelo de dados (Postgres / Supabase)

### 4.1 Schema

```sql
-- Gestores (id = supabase auth.users.id)
CREATE TABLE managers (
    id              UUID PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    full_name       TEXT,
    role            TEXT NOT NULL DEFAULT 'gestor',    -- gestor | admin
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ
);

-- OAuth Google do gestor (escopo adwords)
CREATE TABLE google_oauth_connections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manager_id          UUID NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    google_email        TEXT NOT NULL,
    refresh_token_enc   BYTEA NOT NULL,                -- AES-GCM
    scopes              TEXT[] NOT NULL,
    connected_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at          TIMESTAMPTZ,
    UNIQUE (manager_id, google_email)
);

-- MCC + contas-cliente sincronizadas
CREATE TABLE google_ads_accounts (
    customer_id     TEXT PRIMARY KEY,                  -- ex: '1234567890'
    mcc_id          TEXT NOT NULL,
    descriptive_name TEXT NOT NULL,
    currency_code   TEXT,
    time_zone       TEXT,
    is_test_account BOOLEAN NOT NULL DEFAULT false,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Autorização interna do MCP (separada da OAuth do Google)
CREATE TABLE manager_account_access (
    manager_id      UUID NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    customer_id     TEXT NOT NULL REFERENCES google_ads_accounts(customer_id) ON DELETE CASCADE,
    access_level    TEXT NOT NULL DEFAULT 'write',     -- read | write
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by      UUID REFERENCES managers(id),
    PRIMARY KEY (manager_id, customer_id)
);

-- Sessões MCP (Bearer tokens)
CREATE TABLE mcp_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manager_id      UUID NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,              -- SHA-256
    label           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at    TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ
);

-- Tokens de confirmação (dry-run → apply)
CREATE TABLE pending_confirmations (
    token           TEXT PRIMARY KEY,                  -- 8 chars
    session_id      UUID NOT NULL REFERENCES mcp_sessions(id) ON DELETE CASCADE,
    customer_id     TEXT NOT NULL,
    operation_type  TEXT NOT NULL,
    payload         JSONB NOT NULL,
    blast_summary   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,              -- 10 min
    consumed_at     TIMESTAMPTZ
);

-- Audit log append-only
CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    manager_id      UUID REFERENCES managers(id),
    session_id      UUID REFERENCES mcp_sessions(id),
    customer_id     TEXT,
    action_type     TEXT NOT NULL,                     -- mutate | read | auth | system
    operation       TEXT NOT NULL,
    target_count    INT,
    params_summary  JSONB,
    google_request_id TEXT,
    status          TEXT NOT NULL,                     -- success | error | denied
    error_message   TEXT,
    duration_ms     INT
);
CREATE INDEX idx_audit_manager_time ON audit_log (manager_id, occurred_at DESC);
CREATE INDEX idx_audit_account_time ON audit_log (customer_id, occurred_at DESC);

-- Rate limit (Google Ads quota: 15k/dia)
CREATE TABLE rate_counters (
    developer_token_id TEXT NOT NULL,                  -- hash do dev token
    date            DATE NOT NULL,                     -- America/Sao_Paulo
    operations_used INT NOT NULL DEFAULT 0,
    last_alert_pct  INT NOT NULL DEFAULT 0,
    PRIMARY KEY (developer_token_id, date)
);
```

### 4.2 Notas de design

1. **Encriptação dos refresh tokens** — AES-GCM, chave master no Google Secret Manager. Envelope encryption permite rotação anual sem downtime.
2. **`mcp_sessions` separada de `google_oauth_connections`** — 1 conexão Google : N sessões MCP (uma por cliente/máquina).
3. **`pending_confirmations` TTL 10 min** — limpeza por filtro `WHERE expires_at < now()` na query de busca.
4. **`audit_log` sem FK strict em `customer_id`** — nunca quebrar audit por DELETE de conta.
5. **Rotação `audit_log`** — cron diário 03:00 BRT move > 30 dias pra Parquet em `gs://v4-mcp-audit/year=YYYY/month=MM/day=DD.parquet`, então `DELETE`.
6. **`manager_account_access` é defesa em profundidade** — mesmo que o Google permita acesso à conta, o MCP só deixa operar contas explicitamente atribuídas pelo admin.

---

## 5. Autenticação

### 5.1 Três fluxos compostos

**Fluxo A — Login do painel (Supabase Auth):** SSO Google restrito a `@v4company.com`. Cookie httpOnly assinado.

**Fluxo B — Conexão Google Ads do gestor (OAuth `adwords`):**
- `/oauth/google/start` gera state HMAC, redireciona pro consent screen com `access_type=offline&prompt=consent` (necessário pra Google emitir refresh_token).
- `/oauth/google/callback` valida state, troca `code` por `refresh_token`, cifra com AES-GCM, INSERT em `google_oauth_connections`.
- Roda `list_accessible_customers` pra detectar contas do MCC.
- Atribuição de contas a gestores comuns é manual via admin (defesa em profundidade); admin recebe atribuição automática.

**Fluxo C — Sessão MCP (Bearer token):**
- Gestor cria no painel → token de 32 bytes urlsafe (formato `mcp_<base64url>`) → SHA-256 gravado em `mcp_sessions.token_hash`.
- Token original mostrado **uma vez só** (padrão GitHub PAT).
- Painel renderiza snippets prontos pra Claude Desktop, Claude Code, Codex CLI, Cursor.
- Expiração padrão 90 dias, configurável (30/60/90/180).

### 5.2 Resolução em uma chamada MCP

```
POST /mcp { "method": "tools/call", "params": {...} }
Header: Authorization: Bearer mcp_xxx
  ↓
[auth middleware]      SHA-256 do Bearer → mcp_sessions → manager_id
[tool handler]         valida params, identifica customer_id
[governance.access]    SELECT manager_account_access → 403 se não tem
[governance.rate]      checa quota (FOR UPDATE) → 429 se 100%
[google_ads.client]    decifra refresh_token → monta GoogleAdsClient
                       (login_customer_id = MCC_ID)
[google_ads]           executa GAQL ou Mutate
[governance.audit]     INSERT em audit_log
  ↓
response → Claude → renderiza pro gestor
```

Refresh do access_token é automático no SDK Google. App nunca lida com access tokens no DB.

---

## 6. Catálogo de ferramentas MCP

### 6.1 Convenções

- `customer_id` (string sem traços) obrigatório em toda tool de conta.
- Datas ISO `YYYY-MM-DD` ou relativas: `LAST_7_DAYS`, `LAST_30_DAYS`, `THIS_MONTH`, `LAST_MONTH`, `YESTERDAY`, `TODAY`, range `{from, to}`.
- Filtros consistentes: `status` (`enabled|paused|removed|all`, default `enabled`), `limit` (default 100, max 10000).
- Erros traduzidos PT-BR via `google_ads/errors.py`.

### 6.2 Leitura — 16 tools

**Visão geral:** `get_account_overview`, `get_budget_pacing`, `get_recommendations`.

**Análise de performance:** `get_campaign_performance`, `get_ad_group_performance`, `get_device_performance`, `get_geo_performance` (param `geo_level`), `get_hourly_performance`.

**Otimização tática:** `get_keyword_performance` (com 3 componentes de Quality Score), `get_search_terms_report`, `get_negative_keywords_audit`, `get_ad_performance` (RSAs + asset ratings), `get_audience_performance`, `get_conversion_actions`.

**Relatório cliente:** `get_funnel_metrics`, `get_top_keywords_creatives`.

### 6.3 Escrita — 25 tools

**Campanhas:** `create_campaign` (sempre nasce paused), `update_campaign_status`, `update_campaign_budget`, `update_campaign_bidding`.

**Grupos de anúncios:** `create_ad_group`, `update_ad_group_status`, `update_ad_group_bid`.

**Palavras-chave:** `add_keywords`, `update_keyword_status`, ~~`update_keyword_match_type`~~, `update_keyword_bid`.

> **~~`update_keyword_match_type`~~ — DESCARTADO (Sprint 3b.3 pivot 2026-05-12).** API immutability finding: `KeywordInfo.text` + `KeywordInfo.match_type` formam a IDENTIDADE do `AdGroupCriterion` (não são campos modificáveis post-creation). Para "trocar match type" de uma keyword, o workflow correto Google Ads é: (1) pausar criterion antigo via `update_keyword_status(new_status=PAUSED)`, (2) criar nova criterion com match_type desejado via `add_keywords`. O Quality Score history fica no criterion antigo (não migra). V4 skills `analise-performance-google-ads` + `auditoria-google-ads` já alinham com esse workflow ("pause + replace"). Sprint 3b.3 pivotou para `add_keywords` por essa razão — entregou a metade additiva do workflow. A pause-half já estava shipped via Sprint 3a `update_keyword_status`.

**Negativas:** `add_negative_keywords` (`level` = campaign|ad_group|shared_set), `add_negatives_from_search_terms`.

**RSAs:** `create_rsa` (valida 3-15 headlines, 2-4 descriptions), `update_rsa` (recriação atômica pause+create), `update_ad_status`.

**Assets/extensões:** `create_asset`, `link_assets`.

**Audiências:** `apply_audience` (modo observation|targeting), `upload_customer_match_list` (exige hashes SHA-256, rejeita plaintext por LGPD/Google Policy).

**Conversões:** `create_conversion_action`, `import_offline_conversions`.

**Bulk:** `bulk_pause_by_query` (sempre dry-run obrigatório).

**Recomendações:** `apply_recommendation`, `dismiss_recommendation`.

### 6.4 Utilitários — 7 tools

`list_my_accounts`, `run_gaql`, `validate_gaql`, `list_gaql_resources`, `apply_change(confirmation_token)`, `get_my_rate_limit_status`, `get_my_audit_log(filters)`.

**Total:** 48 tools (16 leitura + 25 escrita + 7 utilitários).

### 6.5 Decisões de UX

1. `customer_id` sempre obrigatório (sem fallback "última usada").
2. Tools de escrita retornam `{status, dry_run_required, confirmation_token?, blast_summary, preview, audit_id, google_request_id?}`. Claude usa `dry_run_required` pra perguntar ao gestor.
3. Não expõe `mutate_*` cru do SDK — cada tool tem semântica e validação. Casos não cobertos viram tool nova ou caem em `bulk_pause_by_query`/`run_gaql`.
4. `upload_customer_match_list` rejeita plaintext (não hashea automático — força gestor a saber o que está fazendo).

---

## 7. Governança

### 7.1 Blast radius (defaults conservadores)

| Operação | Auto-aprova | Exige confirmação |
|---|---|---|
| Pause/enable de 1 entidade | Sempre | Nunca |
| Pause/enable em bulk | ≤ 5 | > 5 |
| Mudança de orçamento de campanha | Nunca | Sempre |
| Mudança de estratégia de lance | Nunca | Sempre |
| Mudança de lance (KW/ad group) | Variação ≤ 20% **e** ≤ 5 entidades | > 20% **ou** > 5 |
| Add KWs | ≤ 20 KWs em 1 ad group | > 20 ou múltiplos ad groups |
| Add negativas | Sempre auto | Nunca |
| Create campaign/ad group/RSA | Sempre auto (nasce paused) | Nunca |
| Update RSA (recriação) | Nunca | Sempre |
| Customer Match upload | Nunca | Sempre |
| Conversion action create/update | Nunca | Sempre |
| Apply recommendation | Sempre | Nunca |
| `bulk_pause_by_query` | Nunca | Sempre |
| Remove (delete) qualquer coisa | Nunca | Sempre |

### 7.2 Fluxo dry-run → apply

1. Tool de escrita chamada → `governance.dry_run.compute(operation, params)` monta GAQL preview, lista entidades alvo, calcula `blast_summary` em PT-BR.
2. INSERT em `pending_confirmations` com TTL 10 min.
3. Resposta pra Claude inclui `confirmation_token` e summary.
4. Claude pede confirmação ao gestor → chama `apply_change(token)`.
5. `governance.dry_run.consume(token)`: SELECT FOR UPDATE, valida `consumed_at IS NULL` + `expires_at > now()` + `session_id == current`, marca consumido, executa mutate com **payload salvo** (não re-executa query — previsibilidade).
6. Audit log gravado com `google_request_id`.

### 7.3 Rate limit (Google Ads API: 15k ops/dia/dev token)

- `before_call(estimated_ops)`: `SELECT FOR UPDATE rate_counters` → bloqueia se ultrapassaria 100% → alerta se ultrapassaria 80% (com `last_alert_pct` pra evitar repetição).
- `on_response(headers)`: reconcilia `operations_used` com `X-Quota-Remaining` (mais preciso que estimate).
- Reset diário em America/Sao_Paulo (não em PT — diferença pequena, alinhado com expectativa do gestor).
- Quota agregada por developer token (todos os gestores compartilham).
- V1.1: solicitar Standard Access (1M ops/dia) — só troca constante.

### 7.4 Audit log

Logado: toda **mutate** + reads sensíveis (audit, contas). Reads de relatório **não** são logados (alto volume, baixo valor).

Payload guardado: metadata resumida (não o body completo de criações grandes nem queries GAQL inteiras — só hash da query).

Rotação: cron diário 03:00 BRT exporta > 30d pra Parquet em `gs://v4-mcp-audit/...`, então DELETE.

---

## 8. Painel web (design system V4)

### 8.1 Design tokens

CSS variables em `web/static/v4-tokens.css` derivadas do brand book V4 Company:

- **Primária:** `--v4-red: #e50914` + variações dark
- **Neutras claras:** `#e5e5e5`, `#cccccc`, `#b3b3b3`
- **Neutras escuras:** `#333333`, `#262626`, `#1a1a1a`, `#000000`
- **Secundárias:** verde `#52cc5a` (sucesso), ouro `#ffc02a` (atenção)
- **Tipografia:** Montserrat (Bunny Fonts, GDPR-friendly) — fallback de Proxima Nova. Hierarquia exata do brand book (H1 72/58, H2 60/58, H3 22/29, H4 18/20).
- **Logo:** símbolo "V4" (`v4-symbol.svg`), versão vermelha em fundo branco, respeita 11 restrições do brand book.

**Tema:** light-first. Fundo `--v4-white`, superfícies `--v4-gray-100`, texto `--v4-gray-900`, CTA vermelho.

**Sem Tailwind, sem build step JS.** ~600-800 linhas de CSS puro + Jinja2.

### 8.2 Telas

**Gestor (5 telas):** `/login`, `/` (dashboard), `/accounts` (conexões Google), `/sessions` (criar Bearer + snippets pra Claude/Codex/Cursor), `/audit` (próprio log).

**Admin (5 telas):** `/admin/managers`, `/admin/accounts` (sincronizadas do MCC), `/admin/access` (matriz manager × conta), `/admin/audit` (global), `/admin/quota` (uso por gestor).

Identificação de admin: `managers.role = 'admin'`. Primeiro usuário a logar vira admin automaticamente; depois é promovido por admin existente.

### 8.3 Snippets multi-cliente na criação de sessão

Tela de "token criado" gera 4 blocos copiáveis:
- Claude Desktop (`claude_desktop_config.json`)
- Claude Code (`claude mcp add ...`)
- Codex CLI (`~/.codex/config.toml` na seção `[mcp_servers]`)
- Cursor (`.cursor/mcp.json`)

Token mostrado **uma vez só** com aviso explícito.

### 8.4 Acessibilidade

Contraste mínimo 2.25:1 (regra V4). Texto branco sobre vermelho dá ~4.5:1, sobre fundo escuro dá ~16:1. Foco visível em interativos: outline 2px ouro. Touch targets ≥ 44x44px.

---

## 9. Deployment & infra

### 9.1 Topologia

- **Cloud Run service `v4-ads-mcp`** — region `southamerica-east1`, 1 vCPU/512MB, `min_instances: 0` (free tier), concurrency 80, ingress público, autenticação app-level.
- **Cloud Run Job `v4-ads-cron`** — mesma imagem, entrypoints diferentes (`python -m src.jobs.<name>`), disparado por Cloud Scheduler.
- **Google Secret Manager** — `google-oauth-creds`, `google-ads-dev-token`, `aes-master-key`, `supabase-service-key`, `session-signing-key`, `supabase-anon-key`.
- **Supabase Free** (Postgres + Auth) — migra pra Pro ($25/mês) quando bater triggers (DB > 400MB, > 10 gestores ativos, primeiro cliente "real" que não tolera 24h de perda, > 5 MCCs).
- **GCS** — `v4-mcp-audit` (Parquet, lifecycle 90d archive / 7 anos delete), `v4-mcp-backups` (pg_dump diário, retention 30d).

### 9.2 Cron jobs

- `audit-rotation` (03:00 BRT) — exporta `audit_log > 30d` → GCS Parquet → DELETE.
- `account-resync` (04:00 BRT) — `list_accessible_customers` → atualiza `google_ads_accounts`.
- `db-keepalive` (a cada 6h) — `SELECT 1` no Supabase Free pra evitar pause.
- `session-cleanup` (02:00 BRT) — marca sessões expiradas como revoked.

### 9.3 CI/CD (GitHub Actions)

- Push em `main` → lint (`ruff`) + types (`mypy`) + tests (`pytest`) → build via Cloud Buildpacks → deploy `gcloud run deploy` + `gcloud run jobs update`.
- Auth GCP via Workload Identity Federation (sem JSON key no GitHub).
- Migrações DB rodam como step do deploy (idempotentes, controle por tabela `_migrations`).
- Sem staging environment no MVP — push em main = produção. Smoke test pós-deploy faz rollback automático se health check falhar.

### 9.4 Observabilidade

- Logs JSON estruturados via `structlog` → Cloud Logging.
- Cada log tem `request_id`, `manager_id`, `session_id`, `customer_id`, `tool_name`.
- Métricas Cloud Run nativas (latência, error rate, instance count).
- 3 alertas Cloud Monitoring iniciais: error rate > 5%/5min, p95 > 3s/10min, quota Google Ads > 80%.

### 9.5 Custos consolidados

| Item | MVP | Escala (50+ gestores) |
|---|---|---|
| Cloud Run service | $0 | $10-30 |
| Cloud Run jobs + Scheduler | $0 | $0 |
| Secret Manager | ~$2 | $5-10 |
| Cloud Logging | $0 | $0-5 |
| GCS (audit + backup) | ~$0.05 | ~$1 |
| Supabase | $0 (Free) | $25 (Pro) |
| **Total** | **~$2-3/mês** | **~$45-70/mês** |

---

## 10. Estratégia de testes

### 10.1 Pirâmide

- **Unit (~150)** — `governance/`, `auth/tokens`, `auth/sessions`, `google_ads/queries|mutates|errors`. Snapshot tests em GAQL/protobuf.
- **Integration (~30)** — Postgres efêmero (`testcontainers`), mocks HTTP via `respx`, `fakegcs-server`. Cobre auth middleware, OAuth, dry-run→apply, audit rotation, rate limit concorrente, manager_account_access.
- **E2E (~5)** — contra conta de teste Google Ads + Supabase staging. Onboarding completo, read básico, write com confirmação, bulk dry-run, erros amigáveis.

### 10.2 Política

- **TDD obrigatório** em `governance/` e `auth/`.
- Cobertura mínima 80% nesses módulos (60% no painel web, manual).
- E2E roda manual + pré-release (não em todo PR).
- Smoke test pós-deploy (3 verificações em <5s) com rollback automático.
- E2E em test account não consome quota produtiva (Google trata test accounts com quota separada).

---

## 11. Roadmap em fases

### Fase 0 — Fundação (1-2 dias úteis)
Repo provisionado, deploy contínuo, "hello MCP" no ar. **Critério:** push em main faz deploy em <5min, `/mcp` responde MCP handshake.

### Fase 1 — Auth ponta a ponta (2-3 dias)
Login painel + OAuth Google + sessões MCP + tool `list_my_accounts`. **Critério:** primeiro gestor loga, conecta Google, atribui contas, configura Claude Desktop, recebe lista de contas.

### Fase 2 — Leitura completa (3-4 dias)
16 tools de leitura + GAQL livre + painel de audit. **Critério:** gestor faz queries de overview, search terms, keyword performance via Claude com resposta correta PT-BR.

### Fase 3 — Escrita com governança (4-5 dias)
25 tools de escrita + dry-run + blast radius. **Critério:** fluxo "pausa todas KW com CTR<0.5%" funciona ponta a ponta com confirmação, audit, e Change History do Google mostra ação como vinda do gestor.

### Fase 4 — Polimento e operação (5-10 dias distribuídos)
Onboarding pros 5-10 primeiros gestores, alertas, backups, documentação, ajustes baseados em uso real. **Critério:** 5 gestores ativos diariamente por 2 semanas sem incidente.

**Total MVP: ~3-4 semanas calendário (1 dev sênior) ou ~2-3 semanas (2 devs em paralelo após Fase 1).**

### Pós-MVP (fora deste spec)
Meta Marketing API, multi-MCC, modo expert (`--no-confirm`), recommendations proativas via Slack, migração Supabase Pro + `min_instances: 1`, domínio custom `mcp.v4company.com`.

---

## 12. Risk register

| Risco | Mitigação |
|---|---|
| Aprovação do developer token pra Standard Access demora (1-4 semanas no Google) | MVP roda em Basic Access (15k ops/dia já cobre 5-10 gestores). Solicitar Standard cedo. |
| Supabase Free pausa por 7d sem atividade | Job `db-keepalive` a cada 6h. |
| Mudança de schema da Google Ads API entre versões | SDK suporta múltiplas versões; pinning explícito (ex: v17). Migração planejada por release. |
| Refresh token revogado pelo gestor | Detecção via `RefreshError` → marca `google_oauth_connections.revoked_at` → painel pede nova conexão. |
| Erro humano via tool destruidora | Defaults conservadores de blast radius + Change History do Google = sempre dá pra reverter. |
| Vazamento de DB | Refresh tokens cifrados com AES-GCM, chave fora do DB (Secret Manager). DB sozinho é inútil. |
| Pendências de licenciamento de Proxima Nova | Decisão tomada: usar Montserrat (free, Bunny Fonts), visual próximo. |

---

## 13. Pendências e decisões abertas

- **Identidade do GCP project** — criar `v4-ads-mcp-prod` (ou usar projeto existente da V4?).
- **DNS pro custom domain** — fora do MVP, mas reservar `mcp.v4company.com` no DNS V4 já agora.
- **Standard Access do developer token** — submeter solicitação na Fase 0 pra ganhar tempo (aprovação leva 1-4 semanas).
- **Supabase Pro upgrade trigger** — monitorar e migrar quando atingir.
- **Lista nominal de admins iniciais** — pelo menos wellinton@v4company.com; outros?

---

## 14. Glossário

- **MCC (My Client Center / Manager Account)** — conta-pai do Google Ads que agrega contas-cliente; CID próprio; necessário no `login_customer_id` da API.
- **GAQL (Google Ads Query Language)** — SQL-like da Google Ads API pra reads.
- **Bearer token MCP** — credencial opaca que o cliente MCP envia em `Authorization: Bearer ...`; identifica a sessão.
- **Refresh token (OAuth)** — credencial de longa duração emitida pelo Google; permite obter access tokens sem nova autorização do usuário.
- **RSA (Responsive Search Ad)** — formato de anúncio de pesquisa do Google com 3-15 headlines e 2-4 descriptions combinados dinamicamente.
- **Blast radius** — escopo de impacto de uma operação (quantas entidades afeta, qual o gasto envolvido).
- **Dry-run** — preview de uma operação destrutiva sem executá-la, devolvendo um token de confirmação consumível.
