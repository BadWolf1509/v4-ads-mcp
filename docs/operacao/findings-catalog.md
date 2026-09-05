# Findings Catalog — V4 Ads MCP

> **Purpose:** Central index of all bugs/findings/lessons learned across sprints. Avoids re-introducing same bug class in future sprints. Cross-referenced from o `Don't do` do CLAUDE.md, das convencoes em [`docs/convencoes/`](../convencoes/) e dos runbooks de smoke.
>
> **Maintainer note:** Add a new entry here whenever a finding is documented in a smoke runbook. Keep entries scannable — link to runbook for detail.
>
> **Last updated:** 2026-09-03 — **F141–F146 fechados** em tres PRs (#28 bloco fuso+freshness; #29 structural_change; #30 fuso do upload offline) mais o F142 (whitelist de client_type) direto na main. Ontem, 02/09: **+F131–F140** da sessao de campo MO-JP, fechados no PR #27 e nos fixes seguintes. Narrativa completa e licoes de metodo no handoff [`session-2026-09-02-03-handoff.md`](session-2026-09-02-03-handoff.md); o historico anterior (F82–F130, 08/14 a 08/20) esta nos handoffs de 08-14-15 e 08-19.
>
> **Abertos hoje:** **nenhum** do bloco F131–F146. Fora do bloco seguem os de sempre: A4, F67 (custom domain) e F129 (governanca do system user — acao humana). **F130 fechado em 05/09** ([#45](https://github.com/BadWolf1509/v4-ads-mcp/pull/45), merge `8ad7689`). **+F154 ABERTO** (`/me/adaccounts` nao e prova de alcance — a fila do painel pede acao impossivel em 2 contas, e isso reinterpreta a medicao de 20/08 que fundou o desenho). **+F153** aberto e fechado no mesmo dia: a correcao do F91 reabriu o F91, e o guard do F91 continuou verde porque a mesma onda lhe acrescentou um mock da leitura nova.
>
> **Como ler:** ~1490 linhas, **151 IDs** (F1-F152 com lacunas, A1-A7, D1-D3). Faça busca dirigida por palavra-chave (`GAQL`, `pool`, `Meta`, `audit`, `ContextVar`), nunca leitura integral. Entradas corrigidas trazem um bloco **✅ CORRIGIDO** com o que foi feito **e o que ficou deliberadamente de fora**.

---

## How to use this catalog

1. **Before designing new mutate tools:** scan "Silent-acceptance design gap" family (A1, A3-A5, F11, F12, F16, F17-F19, F25, F27, F30, F33-F35, F37) to anticipate Google API contract gaps the SDK doesn't expose.
2. **Before writing pre-flight helpers:** scan "Pre-flight + test convention" family to avoid mock-target mistakes.
3. **Before shipping a smoke runbook:** ensure per-value empirical probe step exists for new enum whitelists (Sprint 3b.19A.1 convention).
4. **Bug suspected in production:** grep this file for symptoms first; may be a known class with documented fix.

---

## Bug class 1: Silent-acceptance design gap (Google API contract gaps via SDK ambiguity)

**Pattern:** SDK descriptor (proto enum, field name) accepts a value that Google API runtime rejects, OR Google silently does something different than the SDK suggests. Caught by smoke `apply` step (dry_run + builder tests pass; only real API call reveals).

**Mitigation convention:** Sprint 3b.19A.1 — per-value empirical probe step in smoke runbook (Sprint 3b.24 added per-strategy probe). For each enum whitelist value, create a minimal real entity with that value.

| # | Severity | Discovered | Fixed | Summary |
|---|---|---|---|---|
| **A1** | MED | 3b.3 | not-a-bug | Google silent-dedupes duplicate keyword adds (vs spec assumption `CRITERION_EXISTS` error). Idempotency works via Google's behavior, not our `_classify_partial` mapping. [phase-3b-3-bootstrap.md] |
| **A3** | HIGH | 3b.4 | 3b.5 | Google silent-drops `user_interest` criterion when taxonomy_type incompatible with ad_group channel (VERTICAL_GEO em SEARCH). Returns `applied_count=1` mas criterion não persiste. Fix: pre-flight GAQL taxonomy whitelist (IN_MARKET + AFFINITY only). [phase-3b-4-bootstrap.md] |
| **A4** | HIGH | 3b.4 | 3b.5 + open | Google silently overrides `negative=true` → `false` em CampaignCriterion user_list creates. T3 apply criou criterion como POSITIVE observation, não exclusion. Sprint 3b.5 mitigated via pre-flight rejection do combo `(campaign + exclusion + user_list)` direcionando gestor pra ad_group level. **Real biz mechanism for V4's "-10% CPA via exclusion" playbook ainda pendente investigação** (Sprint 3b.27 candidate). [phase-3b-4-bootstrap.md, phase-3b-5-bootstrap.md] |
| **A5** | HIGH | 3b.6 | 3b.6 | `CampaignCriterion.resource_name` é compound `{campaign_id}~{criterion_id}` (não flat). Builder construía path flat; Google silently aceitou (`applied_count=1`) mas NÃO removia o criterion. Fix: usar SDK path helpers (`campaign_criterion_path`). [phase-3b-6-bootstrap.md] |
| **A6** | HIGH | M.2a smoke real | M.2a hotfix (`e93a05b`) | Meta OAuth callback aplicava `is_allowed_email(fb_email)` rejeitando qualquer conta FB que não fosse `@v4company.com` — semântica errada porque contas Facebook são PESSOAIS (gmail/hotmail/etc), não corporativas. Wellington bloqueado em smoke real (fb_email = `wellington.ribeiro.eng@gmail.com`, V4 panel session = `wellinton.ribeiro@v4company.com`). **Fix:** removido `is_allowed_email` check do callback Meta. Authoritative auth é o `manager_id` no state HMAC (assinado quando gestor já estava logado V4 em /admin). `fb_email` continua armazenado em `meta_oauth_connections` como metadata cosmético. Distinção vs Google: Google OAuth força V4 domain porque gestor faz LOGIN com Google account corporate; Meta flow é diferente — gestor já está autenticado V4 quando clica "Conectar Meta", FB account só adiciona credentials Meta, não autentica V4. Test `test_oauth_callback_blocks_non_v4_email` substituído por `test_oauth_callback_accepts_personal_fb_email` (semântica oposta). [phase-M-2a-bootstrap.md] |
| **A7** | MED | dogfood 2026-07-06 (MO Goiânia, Codex) | not-a-bug (Google-side) + error-UX fix (`errors.py`) | **Suspeita de "MCP não cria anúncio com acento" REFUTADA — é falso-positivo do classificador AUTOMÁTICO do Google (`UNACCEPTABLE_SPACING`/`SYMBOLS`), NÃO bug de encoding.** Report: `create_rsa`/`update_rsa` com acento reprovava, sem acento passava (A/B real: token `OLZDN8BZ` com acento → erro; `4439RG2A` idêntico sem acento → sucesso). Investigação provou: (1) payload em `pending_confirmations` é **NFC limpo** — 0/941 campos com marcas combinantes NFD, zero NBSP/símbolos → nada a normalizar; (2) `run_gaql` mostra dezenas de anúncios acentuados **APROVADOS e ENABLED criados por ESTE MCP** nas MESMAS contas (7621086021: "Escoras em Goiânia"/"Locação Para Construção"; 7862230676 JP inclui o typo humano "Locacão de Martelete" aprovado) → **o MCP não corrompe Unicode; acento chega íntegro ao Google**; (3) logo acento NÃO é gatilho determinístico (mesma conta tem acento aprovado E reprovado) → classificador flaky, agravado por reenvio em rajada (11:16→12:10). **Hipótese DESCARTADA:** NFC-normalize nos builders (seria consertar não-bug — idempotente no input já-NFC). **Ação (B):** `to_friendly` POLICY_FINDING_ERROR agora dá guidance específica pra `_CLASSIFIER_PRONE_TOPICS` (spacing/symbols) — reenviar/revisão manual em vez de "remova o que viola" (que empurrava a tirar acento); tópicos PROHIBITED etc. mantêm a guidance original. **Lição:** correlação≠causa; validar contra ground-truth (payload armazenado + estado real no Google via `run_gaql`) ANTES de shippar fix de encoding. Family: suspected-bug-refuted-by-ground-truth (irmã de A1 not-a-bug). |
| **F11** | LOW | P3 dogfood | 3b.5 | `update_*_status(REMOVED)` passa dry-run mas Google API rejeita REMOVED em `.status.update`. Sprint 3b.5 fix: schema-restrict enum para `["ENABLED", "PAUSED"]`. Remove* tools (Sprint 3b.28 future) precisarão API path diferente. |
| **F12** | MED | P3 dogfood | 3b.8 | Google silently ignora `cpc_bid_micros` em campaigns com auto-bidding strategy (MAX_CONVERSIONS, TARGET_CPA, etc). Pre-flight whitelist `{MANUAL_CPC, ENHANCED_CPC}` em `update_keyword_bid` + `update_ad_group_bid`. |
| **F16** | HIGH | 3b.16 | 3b.16.1 | RSA builder usava `rsa.headlines.add()` (raw protobuf API) — tests passaram com ProtoFieldCapture mock mas proto-plus em real SDK só tem `.append(typed_instance)`. Mock fidelity gap. [phase-3b-16-bootstrap.md] |
| **F17** | HIGH | 3b.19A | 3b.19A | `LEAD` removido do google-ads SDK v20 — design assumiu legacy docs. Replacement = `SUBMIT_LEAD_FORM`. [phase-3b-19A-bootstrap.md] |
| **F18** | HIGH | 3b.19A | 3b.19A | Lead lifecycle categorias `IMPORTED_LEAD`/`QUALIFIED_LEAD`/`CONVERTED_LEAD` são system-managed (Google's lead workflow), rejeitadas em create-via-API. [phase-3b-19A-bootstrap.md] |
| **F19** | HIGH | 3b.19A.1 | 3b.19A.1 | `DOWNLOAD` ConversionAction rejected em WEBPAGE + UPLOAD_CLICKS types — provável require `GOOGLE_PLAY_DOWNLOAD` (app-install niche). [phase-3b-19A-bootstrap.md] |
| **F25** | HIGH | 3b.19B | 3b.22 | `NO_CONDITION` em ConversionValueRule só é permitido em Store Visits/Sales RuleSets (STORE out of scope v0). Schema fix: removed from `condition_type` enum. [phase-3b-19B-bootstrap.md, phase-3b-22-bootstrap.md] |
| **F27** | HIGH | 3b.19B | 3b.22 | `conversion_action_categories` filter só aceita `[]`/`[STORE_VISIT]`/`[STORE_SALE]` — semantically different from `ConversionAction.category` field. 13-cat V4 whitelist herdada de 3b.19A era inválida. Schema fix: removed field entirely. [phase-3b-19B-bootstrap.md, phase-3b-22-bootstrap.md] |
| **F30** | HIGH | 3b.24 | 3b.24.1 (attempt) + 3b.24.4 (final) | Bidding strategy oneof not initialized — bare `campaign.maximize_conversions` access em proto-plus NÃO inicializa oneof. Fix: for scalar-bearing strategies use bare access (`campaign.X.field = Y` auto-inits); for no-scalar strategies (MANUAL_CPC, etc) explicit assignment `campaign.X = client.get_type("X")`. [phase-3b-24-bootstrap.md] |
| **F33** | HIGH | 3b.24.3 | 3b.24.4 | `client.get_type("X")()` invalid — SDK returns INSTANCE not class, can't call `()` on instance. TypeError. F33 = reversal of wrong F30 attempt. [phase-3b-24-bootstrap.md] |
| **F34** | HIGH | 3b.24 | 3b.24.4 | `campaign.contains_eu_political_advertising` REQUIRED on Campaign create (Google EU compliance, May 2024+). V4 BR-invariant: hardcoded `DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING`. [phase-3b-24-bootstrap.md] |
| **F35** | MED | 3b.24 | 3b.24.4 | `manual_cpc.enhanced_cpc_enabled` deprecated by Google — `OPERATION_NOT_PERMITTED_FOR_CONTEXT` on create. Schema fix: removed `enhanced_cpc` field entirely. [phase-3b-24-bootstrap.md] |
| **F37** | HIGH | 3b.24 | 3b.24.5 | `Campaign.start_date`/`end_date` are NOT valid v24 proto fields — only `start_date_time`/`end_date_time` (YYYYMMDD HH:MM:SS format). Builder converts YYYY-MM-DD schema input. [phase-3b-24-bootstrap.md] |
| **F38** | HIGH | 3b.25 | 3b.25.1 + 3b.25.2 | `StructuredSnippetAsset.header` é STRING (not proto enum) — Google rejects ALL_CAPS values like `"SERVICE_CATALOG"`/`"BRANDS"`. API expects PT-BR display strings (V4 invariant). Sprint 3b.25.1 fix had wrong value `"Catálogo de serviços"` (context7 translation off); Sprint 3b.25.2 corrected to `"Serviços"` (matches Nutry existing asset 259782606115 + T6 re-test PASS). Schema enum now: Bairros, Comodidades, Cursos, Cursos de graduação, Destinos, Estilos, Hotéis em destaque, Marcas, Modelos, Programas, **Serviços**, Tipos, Tipos de cobertura do seguro. Verified empirically: Serviços ✅ + Marcas ✅ (T7); other 11 PT-BR values tentative — sprint candidate 3b.25.x per-value probe. [phase-3b-25-bootstrap.md] |
| **F39** | HIGH | 3b.25 | 3b.25.1 | `PromotionAsset.language_code = "pt"` rejected by Google with "The language code is not supported." BCP 47 says `pt` is valid (less specific) but Google PROMOTION requires region-qualified (`pt-BR`). Discovered in T10+T11 smoke. Fix: builder line `promo.language_code = "pt-BR"`. T10 re-test PASS bit-a-bit via GAQL. [phase-3b-25-bootstrap.md] |
| **F40** | HIGH | 3b.25.1 | 3b.25.2 | `PromotionAsset.discount_modifier="NONE"` rejected — Google's `PromotionExtensionDiscountModifierEnum` only has UNSPECIFIED + UP_TO (NOT NONE). Discovered when T11 re-test still failed pós-F39 fix (different root cause). Fix: schema enum `["NONE","UP_TO"]` → `["UP_TO"]`; field moved out of required (optional now — omit for exact discount, UP_TO for "até X% off"); builder only sets if present. T11 re-test PASS pós-fix. [phase-3b-25-bootstrap.md] |
| **F42** | HIGH | 3b.26 | 3b.26.1 | `UploadClickConversionsRequest.debug_enabled` field removed em google-ads SDK v24 — builder line `request.debug_enabled = False` raised `AttributeError: Unknown field for UploadClickConversionsRequest: debug_enabled`. Blocked TODAS upload calls (T7 partial_failure path inacessível). Discovered em smoke T7 (5 fake gclids). Root cause via Cloud Logging traceback. Fix: remove single line + delete dedicated `test_upload_request_debug_enabled_false` unit test. Pattern Java setDebugEnabled→python `debug_enabled` field deprecated by Google sem aviso de migração. T7 re-test PASS pós-fix com 5 UNPARSEABLE_GCLID errors retornados em failures array. [phase-3b-26-bootstrap.md] |
| **F43** | HIGH | dogfood 2026-05-19 MO-JP | 3b.27 | `update_keyword_status` aceita batch silenciosamente quando inclui criterion_id com `negative=true` flag, mas `apply_change` falha com erro Google genérico (`Negative ad group criteria are not updateable`) que NÃO identifica quais IDs do batch eram negative. Discovered em sessão cleanup massivo MO-JP cirurgia GERADORES (22 IDs batch, 5 eram negative). Fix Sprint 3b.27: novo helper `validate_keyword_criterion_types` em `_common.py` faz GAQL `SELECT ad_group_criterion.criterion_id, ad_group_criterion.negative, ad_group_criterion.type FROM ad_group_criterion WHERE criterion_id IN (...)` + split em `positive_ids_safe` / `negative_ids_blocked` / `missing_ids` (missing curto-circuita antes do negative check). Hard reject com `to_retry_with` template. Smoke T9-T12 validou em produção 14/14 PASS (T11 mistura 3+2 retornou split correto). [dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md §B1, phase-3b-27-bootstrap.md] |
| **F44** | HIGH | 3b.27 | 3b.27.1 | `ConversionAction.include_in_conversions_metric` é IMMUTABLE em update operation v24 do Google Ads API, mesmo que SDK descriptor aceite o field. Builder tests via ProtoFieldCapture passaram, dry_run passou, mas apply falhou com `"The field attempted to be mutated is immutable."` Discovered em smoke T7 (batch 3 actions com 3 fields combinados). Diagnosis isolado: `primary_for_goal=False` sozinho OK (request `vw3Dp2KQqcgS2wqd4VjWtQ`), `include_in_conversions_metric=False` sozinho falha. Fix Sprint 3b.27.1: field removido do schema V0 + builder + classify + tests (commit `c903eb8`). V0 final = 2 fields mutáveis (`name`, `primary_for_goal`). Pra desligar conv metric tracking, gestor usa Google Ads UI. Tool description atualizada cita F44 explicitly. [phase-3b-27-bootstrap.md §F-findings] |
| **F46** | MED | 3b.33 | 3b.34 | `change_event.change_date_time BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'` em GAQL trata end_date como **midnight 00:00:00 start-of-day exclusive**, não inclusive end-of-day. Resultado pré-fix: single-day window `start_date=end_date=2026-05-20` retornava **0 rows silenciosamente** (mesmo que dia tenha changes); multi-day window excluía changes de end_date depois do meio-dia. Discovered em smoke 3b.33 T3 (Pedro Vytor cluster 20/05 10:12-10:13 não retornou com window 19→20, retornou só com 19→21). Affected: `get_change_history` (3b.1), `get_negative_keywords_audit` via `negative_criterion_creations_query` (3b.21), `detect_drift` (3b.33). **Fix Sprint 3b.34 (commit `0785dbf`):** novo helper `_format_change_date_between(start, end)` em `change_history.py` aplica `timedelta(days=1)` ao end_date antes do isoformat. Google passa a interpretar como `<= midnight do dia seguinte`, capturando o dia inteiro inclusive. Helper compartilhado entre `change_history_query` e `negative_criterion_creations_query` pra consistência. 3 regression tests F46-specific. Range validation (30-day cap) preservada — usa user-facing end_date, NÃO o transformed end+1. Família design-gap-via-Google-API-semantics. 15ª variante da silent-acceptance family (returns empty silently instead of erroring). [phase-3b-33-bootstrap.md] |
| **F47** | HIGH (procedural) | M.2a smoke real | M.2a runbook fix | **PowerShell pipe `\|` no Windows converte LF→CRLF mesmo com `python sys.stdout.buffer.write()` binary** — secret upload via `python -c "sys.stdout.buffer.write(b'...')" \| gcloud secrets versions add ... --data-file=-` resultou em **`\r\r\n` trailing** no GCP Secret Manager. Causou Meta OAuth flow falhar com "ID do app inválido" (`client_id=1522411803012799%0D%0A` na URL — `%0D%0A` = `\r\n` URL-encoded). Mesma classe de bug atingiu `meta-app-id` (v1) e `meta-app-secret` (v1-v5 todas com 3 bytes trailing). Plus a verification side via `gcloud secrets versions access \| python ...` também mente — pipe adiciona `\r\n` no read side, fazendo `clean=False` mesmo quando o secret stored estava limpo. **Root cause:** Windows pipes são text-mode default; Python sequer alcança raw bytes através do pipe. **Mitigation:** SEMPRE usar arquivo binary intermediário pra secret creation. Procedure pra runbooks futuros: `python -c "open('tmp.bin', 'wb').write(b'<value>')"` + `(Get-Item tmp.bin).Length` (valida tamanho binary exato) + `gcloud secrets versions add ... --data-file=tmp.bin` (gcloud lê arquivo direto, binary-safe) + `Remove-Item tmp.bin` + `Clear-History`. Bash não tem esse problema (Linux/WSL/Git-Bash pipes são byte-clean). **Secret rotation forçada** porque Wellington colou o secret comprometido em chat durante diagnosis — Meta App Reset + nova versão v6 limpa + v1-v5 disabled (defense in depth). [phase-M-2a-bootstrap.md] |
| **F49** | MED | M.2b smoke real T8 | M.2b same-session fix | **`{{ button() }}` macro em `src/web/templates/_components.html:80` tem default `type="button"`** — quando chamado dentro de `<form>` sem `type="submit"` explícito, NÃO submete o form. Bug introduzido em M.2b Task F linha 63 do `admin/index.html`: `{{ button("Atualizar lista", variant="secondary", size="small") }}` (sem type) → button renderiza como `<button type="button">` que JS browser default ignora pra form submission. Resultado: click no botão "Atualizar lista" no admin UI não dispara POST `/oauth/meta/refresh-accounts` (verificado em prod: ZERO audit_log row `meta_refresh_accounts` após múltiplos clicks). **Por que não foi pego em testing:** integration test `test_meta_refresh_accounts.py` chama endpoint via HTTP client direto (não via browser), bypassando o template render. Code reviewer Task F também não pegou (revisou HTML mas não validou submit semantics dentro do `<form>`). **Fix:** explicitar `type="submit"` no chamado do macro (linha 63 patched same-session). **Mitigation regression:** grep verificou que esse é único call site `{{ button() }}` sem `type=` em todos templates — outros call sites já passam type explícito ou estão fora de form. Convention nova: SEMPRE passar `type="submit"` ao usar `button()` macro dentro de form. Family: HTML semantics + Jinja2 macro defaults. Caught via smoke real em prod, não em CI. [phase-M-2b-bootstrap.md] |
| **F48** | HIGH | M.2b smoke real T1 | M.2b same-session fix (commit `a281c00`) | **`facebook_business v21 FacebookAdsApi.__init__` aceita só `(session, api_version, enable_debug_logger)` — NÃO `access_token`/`app_id`/`app_secret` direto como kwargs**. M.2a `build_meta_api_for_manager` em `src/meta_ads/client.py` estava passando esses kwargs direto → `TypeError: FacebookAdsApi.__init__() got an unexpected keyword argument 'access_token'` em runtime. **Why not caught in CI:** integration tests da Meta family (test_meta_oauth_flow.py, test_meta_get_account_overview.py) mockam `run_meta_graph_get` no nível do orchestrator — nunca exercise real `build_meta_api_for_manager` factory. Bug surface só quando smoke real chama tool MCP em prod fazendo Graph call de verdade. **Why not caught in M.2a smoke:** `meta_list_my_ad_accounts` (1ª tool Meta shipped) usa cache local `meta_ad_accounts` table — não chama `build_meta_api_for_manager`. M.2b `meta_get_account_overview` é PRIMEIRA tool com real Graph call → bug surface aqui. **Fix:** construir `FacebookSession(app_id=..., app_secret=..., access_token=...)` primeiro, depois `FacebookAdsApi(session=session, api_version="v22.0")`. Mirror what `FacebookAdsApi.init()` does internamente mas mantém convention M.2a de NÃO usar global state. **Testing gap mitigation:** adicionado unit test `tests/unit/test_meta_client.py` que cobre `build_meta_api_for_manager` factory pattern (verifica session construction + api_version + sem TypeError). **Family:** facebook_business SDK signature contract change não detectado em testing. Mesma class de bug pode atingir outros SDK call sites em M.3+ se SDK signature mudar entre versões. [phase-M-2b-bootstrap.md, commit `a281c00`] |
| **F50** | HIGH | audit_log id=140 (2026-05-18 03:11:45 UTC) | já fixado em 3b.24.4 (commit `df0f451`) | **Retrospective: produção confirmou TypeError da F33 via audit_log.** `build_create_campaign` na versão Sprint 3b.24.3 (`ef781f8`, merged 03:07:41 UTC) usava `client.get_type("MaximizeConversions")()` com parens no branch `MAXIMIZE_CONVERSIONS` sem `target_cpa_brl`. Em produção, `client.get_type("X")` retorna INSTANCE (não classe) — chamar instância com `()` lança `TypeError: 'MaximizeConversions' object is not callable`. Audit_log params: `customer_id=1163862076`, `bidding_strategy_type=MAXIMIZE_CONVERSIONS`, `daily_budget_brl=10`, `geo_count=1`, `has_schedule=false`. **Timeline crítico:** bug introduzido em `ef781f8` (03:07:41 UTC), audit_log registrou falha 03:11:45 UTC (4 min depois — Cloud Run uptime), fix `df0f451` merged 03:26:37 UTC (19 min depois). **Por que CI não pegou:** `make_capture_client()` em `proto_capture.py` tinha `__call__` em CapturedOp nessa época (removido pra espelhar SDK reality apenas no commit df0f451 — circular: o fix de código e o fix do mock foram no mesmo commit). **Test gap:** `test_builder_happy_path_max_conversions_minimal` cobre exatamente esse path, mas mock fidelidade de `get_type()()` era falsa. Não há test gap residual — f33 fix + mock fix já commitados. **Lição nova vs F33:** audit_log preservou evidência de timing que confirma o deploy-to-failure window foi 4 minutos (Cloud Run cold-start pick-up do container pós-push). Referência cruzada: F33 (design-time catalog), commit `df0f451`. [audit_log id=140] |
| **F51** | HIGH | audit_log id=149 (2026-05-18 03:32:08 UTC) | já fixado em 3b.24.5 (commit `9488f7c`) | **Retrospective: produção confirmou AttributeError da F37 via audit_log.** `build_create_campaign` na versão Sprint 3b.24.4 (`df0f451`, merged 03:26:37 UTC) fixou F33 mas ainda continha `campaign.start_date = payload["start_date"]` / `campaign.end_date = payload["end_date"]`. Em Google Ads API v24, Campaign proto NÃO tem campos `start_date` / `end_date` — só tem `start_date_time` / `end_date_time` (formato `YYYYMMDD HH:MM:SS`). Atribuir campo inexistente em proto-plus lança `AttributeError: Unknown field for Campaign: start_date`. Audit_log params: `customer_id=1163862076`, `bidding_strategy_type=MAXIMIZE_CONVERSIONS`, `daily_budget_brl=15`, `geo_count=2`, `has_schedule=true`. **Timeline crítico:** fix F33 merged 03:26:37 UTC; Wellington testou com `has_schedule=true` em seguida (03:32:08 UTC — 5.5 min); F37 fix (`9488f7c`) merged 03:34:33 UTC. **Por que CI não pegou:** `test_builder_schedule_dates_set_when_provided` cobria esse path, mas o teste estava assertando `.start_date_time` / `.end_date_time` (campos corretos do futuro fix), enquanto o builder ainda setava `.start_date` / `.end_date`. Com `CapturedOp`, qualquer campo setado é capturado silenciosamente — `_SubCapture.__setattr__` não rejeita campo inexistente como proto-plus real faz. Test passou com mock mas falhou em produção. **Test gap residual:** nenhum — fix + test correto já em `9488f7c`. **Lição nova vs F37:** o mock `CapturedOp.__setattr__` captura QUALQUER atribuição de campo sem validação de schema proto — essa característica pode ocultar bugs de campo errado no builder em futuros sprints. Não há mecanismo de allowlist no mock pra garantir que só campos proto reais sejam setados. Referência cruzada: F37 (design-time catalog), commit `9488f7c`. [audit_log id=149] |
| **F53** | HIGH | M.3 smoke real 2026-05-27 T1 (ICSER) | M.3.1 (commit `984a7ae`) | **`effective_status` NÃO é valid Meta Insights API field nem em `fields=` nem em `filtering=` params** — `INSIGHTS_FIELDS_CAMPAIGN/ADSET/AD` em `src/meta_ads/insights.py` incluíam `"effective_status"` que Meta rejeita com `(#100) effective_status is not valid for fields/filtering param`. effective_status é Campaign/AdSet/Ad METADATA (queryable via `/campaigns`, `/adsets`, `/ads` endpoints), NÃO Insights metric field. Filtering block em `build_insights_call` tentava `[{"field":"effective_status","operator":"IN","value":["{status}"]}]` — Meta retorna mesmo erro. **Impacto:** TODAS 3 tools M.3 (campaign/adset/ad performance) broken em produção desde deploy 2026-05-26 — 100% error rate em T1-T6 happy paths. Caminho B+ Meta volume contribution = ZERO até hotfix. **Why not caught in CI/integration tests:** todos integration tests `test_meta_get_*_performance.py` mockam `run_meta_graph_get` no namespace do tool — nunca exercise real Meta API. Mesma family F48 (Meta SDK mock-no-real-call testing gap). **Fix M.3.1:** remove `effective_status` de 3 INSIGHTS_FIELDS_* lists + remove filtering block em `build_insights_call` + remove `effective_status` param da signature + remove do schema input + 3 tool files + update unit/integration tests. Parser `parse_insights_row` defensive code (`row.get("effective_status", "UNKNOWN")`) naturally returns `"UNKNOWN"`/`"DESCONHECIDO"` — zero parser changes needed. V0 trade-off: tools retornam TODAS entities regardless of status (gestor filtra client-side via prompt natural). V1 enhancement: 2-step query — fetch `/campaigns?fields=effective_status` pra obter IDs por status, depois `/insights?filtering=[{"field":"campaign_id","operator":"IN","value":[<ids>]}]`. Restaura filter sem violar Insights field rules. **Lição reinforced:** F17/F18/F19/F25/F27/F31/F32/F34/F36/F44 family — schema/field whitelists MUST ser empiricamente validadas, NUNCA assumidas do docs. Per-value probe convention 3b.19A.1 caught F53 (smoke runbook T6 pre-value probe vier antes do production smoke teria capturado em sandbox). Family: design-gap-via-API-field-whitelist (Meta variant). [phase-M-3-bootstrap.md] |
| **F55** | HIGH (design pattern) | 2026-05-27 teste empírico Meta MCP oficial connected | architectural lesson — V1 enhancement Sprint M.3.2 planejado | **Meta API tem 2 endpoints separados com field whitelists DIFERENTES — explicação root cause F53/F54.** Wellington conectou Meta MCP oficial (44 tools) e teste empírico `ads_get_field_context` revelou: `effective_status` é VÁLIDO mas em `levels=[campaign, adset, ad]` (endpoints `/campaigns`, `/adsets`, `/ads`); `daily_budget` válido `[campaign, adset]` (entity endpoints); `creative_id` válido `[ad]` (entity endpoint). NENHUM destes é válido em `/insights` endpoint. Meta separation: **`/insights` endpoint** = APENAS metrics fields (spend, impressions, ctr, cpc, reach, frequency, actions, action_values, purchase_roas); **`/campaigns`, `/adsets`, `/ads` endpoints** = metadata fields (effective_status, daily_budget, creative_id, name, objective, etc.). Sprint M.3 V0 implementou um único call `/act_X/insights?fields=...` misturando metadata + metrics → Meta rejeita metadata fields lá. **Meta MCP oficial faz 2-step query natively** (entity endpoint pra metadata + insights endpoint pra metrics, depois join client-side) — exatamente o V1 enhancement V4 planejado (Sprint M.3.2 candidate). **Lesson aprendida:** quando shipping nova tool Meta API, MUST consultar `ads_get_field_context` helper PRIMEIRO pra validar field belongs to which endpoint OR usar per-value probe contra Meta sandbox account. Helper teria evitado F53+F54 100% em ~2 minutos vs 2 deploy cycles + 1 hotfix iteration. **V1 enhancement Sprint M.3.2 (planejado):** implementa 2-step query em M.3 tools — fetch `/{level}s?fields=effective_status,daily_budget,creative_id&filtering=[...]` pra obter entity IDs filtered by status + metadata, depois `/{ad_account}/insights?level={level}&filtering=[{"field":"{level}_id","operator":"IN","value":[...]}]` pra metrics. Restaura status filter sem violar Meta API rules. Bonus: também restaura daily_budget_brl (adset) + creative_id (ad) na response. Family: design-gap-via-API-endpoint-architecture (Meta architecture clarity). Referência cruzada: F53 + F54 são manifestations específicos deste pattern raiz F55. [análise empírica session 2026-05-27 — Meta MCP oficial 44 tools connected pra testing] |
| **F54** | HIGH | M.3 smoke real 2026-05-27 T2/T3 (ML Antiguidades) | M.3.1.1 iteration 2 (commit `b3ba6b5`) | **MORE Meta Insights API field rejections pós-F53 fix: `billing_event`, `daily_budget` (adset level), `creative_id` (ad level)** — Smoke iteration 2 pós-M.3.1 deploy revelou que Meta também rejeita campos metadata adset/ad em Insights `fields=` param. Errors: `(#100) billing_event, daily_budget are not valid for fields param` (adset), `(#100) creative_id is not valid for fields param` (ad). Mesma family F53 — todos são entity METADATA (não Insights metrics). T1 campaign-level com `objective` field passou (objective IS valid Insights field), T2+T3 falharam. **Fix M.3.1.1:** remove `billing_event` + `daily_budget` de `INSIGHTS_FIELDS_ADSET`; remove `creative_id` de `INSIGHTS_FIELDS_AD`. Mantém `objective` (campaign — empirically valid) + `optimization_goal` (adset — empirically valid). Update 2 unit tests pra assertar removed fields. Parser defensive code já handle missing fields (daily_budget_brl=None, creative_id=None). **Smoke real validation pós-M.3.1.1:** T1+T2+T3 PASS em ML Antiguidades 90d (1 campaign engagement WhatsApp → 1 adset arquitetos+colecionadores → 1 ad "AD 01", math consistente: spend_brl=411.83 across 3 levels). audit_log 5 success entries com x-fb-trace-id populated (BeBREJnkUJk, A4yiXe8X1Vj, AZcBEtMACkf, etc). meta_rate_counters ML Antiguidades calls_used=5 throttle_pct=1%. **Iteration discipline lição:** F53 + F54 são MESMA family mas Meta API retorna 1 error por response. Cada deploy cycle revelava próximo invalid field. Lesson pra future Meta tools: pre-shipping per-value probe contra REAL Meta sandbox account (não só doc reference) catches all-at-once vs N deploy cycles. V1 enhancement same as F53 (2-step query enrichment). Family: same as F53 (design-gap-via-API-field-whitelist, Meta variant, multi-iteration manifestation). [phase-M-3-bootstrap.md] |
| **F52** | HIGH | dogfood 2026-05-25 MO-JP+CAB | 3b.38 | **`audit_zombie_keywords` não filtra `ad_group.status` — 60% das zumbis retornadas podem ser órfãs cosméticas em ad_groups REMOVED.** Dogfood 2026-05-25 MO-JP+CAB: tool retornou 280 zumbis em `LAST_30_DAYS`, investigação cross-check via `SELECT ad_group.status FROM ad_group` revelou que **170 (60.7%) estavam em ad_groups REMOVED** — `DELL` JPA (93 órfãs) + `[GPA][02][ANDAIME]` CAB (77 órfãs). Keywords ENABLED dentro de ad_group REMOVED não competem em leilão, não impactam Quality Score nem Smart Bidding — batch PAUSE seria **no-op** + narrativa pro cliente inflada 2.5× ("pausei 280" quando só 110 importavam). **Server-side filters atuais corretos** (`keyword.status=ENABLED` + `keyword.negative=FALSE`), filter ausente era `ad_group.status=ENABLED`. **Fix Sprint 3b.38 (Opção C — mínimo invasivo):** adicionar `ad_group_status` field na response (zero breaking change pra consumers existentes) + warning explícito na tool description ("filtre pelo campo `ad_group_status='ENABLED'` pra cleanup de impacto técnico real, OU mantenha tudo pra inventário cosmético"). Consumer pode filtrar client-side. `KeywordRow` + `ZombieKeyword` dataclasses + `parse_keyword_view_row` + `dict_to_keyword_row` + tool response dict — 3 source files + 3 test files (2 novos regression tests cobrindo F52 cenário DELL/GPA). **Lição V4 48 (nova) generalizável:** antes de batch via `audit_*` tool, validar status do **parent resource** (ad_group pra keywords, campaign pra ad_groups). Audit tools focam no resource específico mas podem retornar items "órfãos" tecnicamente — operação batch neles é no-op + infla narrativa. Family: design-gap-via-missing-parent-filter (variant da silent-acceptance family). [dogfood-2026-05-25-mestre-da-obra-jp-zombies-audit.md §B6] |
| **F56** | MED | dogfood 2026-05-27 MO-JP | 3b.40 | **`get_keyword_performance` retorna positive E negative `ad_group_criterion` indistintamente — workflow risk em mutate downstream.** Dogfood 2026-05-27 MO-JP+CAB cleanup massivo: fresh fetch `get_keyword_performance(status=enabled, limit=500)` retornou 500 keywords ENABLED. Cross-check com `audit_zombie_keywords` (filtra `negative=FALSE` server-side) revelou 280 zumbis totais → 108 em ENABLED ad_groups. **Diferença com fresh fetch: 39 keywords = negative ad_group_criterion com status ENABLED.** Workflow "extract criterion_ids zumbis pra PAUSE batch via fresh fetch" produz 147 candidatos (incorretos) vs 108 verdadeiros (positive ENABLED). Os 39 falsos positivos seriam rejeitados por `update_keyword_status` via pre-flight `validate_keyword_criterion_types` (F43 mitigation), mas inflam baseline de "zumbis" + forçam parse Python externo. **Root cause:** GAQL `keyword_view` resource expõe `ad_group_criterion.negative` mas tool atual omite no row_formatter. **Fix Sprint 3b.40 (Opção A+C — backward-compat):** adicionar field `negative: bool` na response (zero breaking change pra consumers existentes) + warning F56 explícito na tool description direcionando consumer pra `audit_zombie_keywords`/`audit_quality_score` (filtram `negative=FALSE` server-side). **Lição generalizável:** tools de listagem que feed mutate workflows MUST expor type discriminators (positive vs negative, criterion type) explícitos no output, mesmo que GAQL native exponha (tool layer não pode confiar que caller saiba inspecionar SDK proto fields). Family: design-gap-via-missing-discriminator-field (variant da silent-acceptance family, similar F52 missing parent filter pattern). [dogfood-2026-05-27-mestre-da-obra-jp-investigacao-senior.md §B9] |
| **F61** | HIGH | sessão 2026-06-19 | 2026-06-19 (`17a8145`) | **Meta `/me/adaccounts` sync não paginava → cache truncava silenciosamente.** O sync (callback OAuth + `/oauth/meta/refresh-accounts`) lia só a 1ª página (default 25). Com o system user `v4-ads-mcp-integracao` atribuído a 20+ ad accounts, o cache `meta_ad_accounts` travou em 12 → MCP `meta_list_my_ad_accounts` só via 12 das 22 contas do portfólio. (Causa primária nesta sessão foi o sync nunca ter sido re-rodado desde 28/05 — só 20 sincronizadas, <25 — mas a paginação trunca quando passar de 25.) **Fix:** helper `_fetch_all_adaccounts` segue `paging.next` (limit 200/página + cap defensivo) nos 2 call-sites + teste de regressão `test_refresh_accounts_follows_pagination`. Family: silent-truncation. [session-2026-06-19-handoff.md] |
| **F62** | MED | sessão 2026-06-19 (audit erros Pedro/Codex) | 2026-06-19 (`653e724`) | **`run_gaql` QUERY_ERROR cru não é acionável → cliente LLM repete o erro.** Sessões Codex do Pedro geravam GAQL com campo/métrica/recurso inexistente (ex.: `metrics.search_overlap_rate` — auction insights NÃO existem na GAQL, só na UI) e o MCP devolvia a mensagem crua do Google sem dica → o LLM errava os mesmos campos 11×. **Fix:** `to_friendly` em `errors.py` detecta o oneof `query_error`, mantém o campo cru E anexa dica (`list_gaql_resources`/`validate_gaql` + nota de nível-de-recurso e auction insights). Auto-corrige no próximo turno, pra qualquer cliente. + descrição do `run_gaql` orienta validar antes. Verificado em prod (smoke `metrics.search_overlap_rate`). Family: error-UX-não-acionável. [session-2026-06-19-handoff.md] |
| **F63** | LOW | sessão 2026-06-19 (audit erros Pedro) | 2026-06-19 (`653e724`) | **`get_change_history` com `start_date` custom > 30 dias erra em vez de clampar.** F23 (3b.38) clampava só preset; data custom honrava intent e o Google rejeitava ("start date too old"). **Fix:** clamp também pro custom (preset OU custom) com warning; janela inteira fora da retenção (`end < today-28`) → `ValueError` claro em vez de query vazia/quebrada. `test_tool_rejects_range_over_30_days` virou `test_custom_old_start_date_clamped` + `test_custom_window_entirely_outside_retention_errors`. Family: silent-acceptance (Google retention). [session-2026-06-19-handoff.md] |
| **F64** | MED | sessão 2026-06-30 | resolvido na migração 2026-06-30 (token all-targets regenerado) | **Meta `/me/adaccounts` é token+APP-scoped → sync perde contas do BM mesmo com o system-user já atribuído.** Pós-F61 (paginação), o sync ainda não reflete contas recém-atribuídas porque `/me/adaccounts` é avaliado por (system-user × **app do token**), não pelo BM. Diagnóstico 2026-06-30 (contas parceiras do BM `619664032237208` V4 Lima Soares): `CA - MDO Goiânia` (`act_1292624998332379`, ATIVA) atribuída ao **único** SU `v4-ads-mcp-integracao` (`61590110716028`) mas invisível ao token de produção. `client_ad_accounts` (business-cêntrico) = **21** vs `/me/adaccounts` (token-cêntrico) = 18→19. **Causa raiz:** o token no GCP `meta-system-user-token` (app **V4 Ads MCP** `1522411803012799`) tem granular `ads_management`/`ads_read` com **target_ids FIXOS** (não `all targets`) → contas novas não entram até **regenerar** o token. Confirmado via `debug_token`: token fresh all-targets (mesmo app+SU) VÊ a conta; o de produção não. **Armadilha de diagnóstico:** `/me` retorna **app-scoped IDs (ASIDs)** distintos por app (`122108…` vs `122103…`) — parecem SUs diferentes mas são o MESMO SU. **Fix:** regenerar o token de produção marcando "todas as contas atuais e futuras" + gravar no GCP (**bloqueado pelo IAM GCP pendente**). Alternativa de código: enumerar business-cêntrico (`/{bm}/client_ad_accounts`+`/owned_ad_accounts`), mas listar≠operar. Family: token+app-scoped-enumeration (evolução de F61). [session-2026-06-30-handoff.md] |
| **F65** | MED | sessão 2026-06-30 | 2026-07-02 (`0356a5d`, Onda 5) | **`resync_meta` nunca chama `mark_inactive_except` → cache `meta_ad_accounts` acumula órfãs.** O resync Meta ([meta_resync.py](../../src/jobs/meta_resync.py)) só faz `upsert_many` (sempre `is_active=true`); a função `mark_inactive_except` existe (`src/db/repositories/meta_ad_accounts.py:81`, com testes) mas **nunca é chamada** — só o lado Google a chama (`account_resync.py:100`). Resultado: contas que o SU/app perde acesso (ou que fecham/saem do portfólio) ficam `is_active=true` pra sempre. Diagnóstico 2026-06-30: cache = 22 incluindo a conta **pessoal** `Wellington Ribeiro` + `WJX Construções` (FECHADA) + 2 contas fora do `client_ad_accounts` atual. **Fix (Onda 5 do roadmap 2026-06-20):** plugar `mark_inactive_except` no `resync_meta`, **agrupado por `business_id`** (o SU vê múltiplos BMs via `/me/adaccounts`; desativar tudo que não veio numa página derrubaria contas de outro BM). Family: data-staleness / missing-cleanup (Meta espelho do deletion-detection que o Google já faz). [session-2026-06-30-handoff.md] |
| **F66** | HIGH | sessão 2026-06-30 (migração GCP) | 2026-07-02 (gcloud + `ab14268`) — `/cnb/process/<type>` | **Cloud Run Job com imagem Buildpacks ignora `--command`/`--args` e roda o process `web` do Procfile.** Ao migrar pro projeto novo, os jobs `migrate`/`resync` criados com `--command=python --args=-m,src.db.migrate` → container falha no exec ("Application exec likely failed" — `python` não está no PATH sem o entrypoint do buildpack). Tentativas: `--command=/cnb/lifecycle/launcher --args=migrate` → exec fail; SEM command + `--args=migrate` (process type) OU `--args=python,-m,src.db.migrate` → **sobe o `web` (uvicorn)** e o job nunca termina (execução pendurada). O buildpack Google só honra o process `web` no entrypoint; process types não-web do Procfile não são invocáveis por `--args`. **Impacto:** `deploy.yml` step "Run database migrations" (`jobs execute …migrate --wait`) **falha** → bloqueia o deploy via CI. **Mitigação:** deploy do serviço feito manualmente (`gcloud run deploy`, entrypoint web = correto); migrate pulado (schema já existe no Supabase compartilhado — idempotente). **Fix (2026-07-02):** causa-raiz DUPLA — (1) a imagem CNB expõe cada process via symlink `/cnb/process/<type>` (CNB Platform ≥0.4, confirmado no config OCI); `--command=/cnb/process/migrate --args=""` invoca o certo; (2) o estado sujo do job resync era `command: C:/Program Files/Git/cnb/lifecycle/launcher` — o **Git Bash no Windows manglou `/cnb/...` pra caminho Windows** numa tentativa anterior (por isso o launcher "falhava"). Comandos one-time com arg iniciando em `/` DEVEM rodar em PowerShell. Aplicado via gcloud + repassado no `deploy.yml` (self-healing) + step de migrations reativado + guard no rollback. Lição: buildpack/CNB entrypoint contract + MSYS path mangling. [session-2026-06-30-handoff.md, investigação 2026-07-02] |
| **F67** | MED | sessão 2026-06-30 (custom domain) | open (usar Load Balancer) | **`southamerica-east1` não permite Cloud Run domain mappings** — `gcloud beta run domain-mappings create` retorna `501 UNIMPLEMENTED` ("Creating domain mappings is not allowed in southamerica-east1"). O erro "domain não verificado" aparece ANTES (ordem do check), mascarando que o bloqueio real é a região. **Impacto:** custom domain (`mcpv4.fluxocerto.dev.br`) não mapeável direto. **Fix:** Global External Application Load Balancer + Serverless NEG → Cloud Run + SSL gerenciado + 1 registro A no DNS (domínio já verificado no Search Console). Alternativa mais barata: Firebase Hosting proxy. Family: limitação regional GCP. [session-2026-06-30-handoff.md] |
| **F68** | HIGH | investigação 2026-07-02 | 2026-07-02 (`becea99`) | **O serviço NOVO anunciava a URL do projeto ANTIGO — sabotava o cutover.** Pós-migração GCP, `src/config.py` tinha a URL velha (`…jf26mmrgqa-rj`) como default de `public_base_url` e os 4 snippets de conexão de `/help` eram hardcoded com ela; o `deploy.yml` não setava `PUBLIC_BASE_URL`. Um gestor que relogava no painel novo e copiava o snippet de `/help` ou `/sessions` configurava o endpoint a decomissionar — funcionava até o dia do desligamento. Confirmado no `audit_log`: Pedro operou via serviço antigo em 07-02. **Fix:** default = URL nova; `/help` injeta `mcp_url` via contexto (drift-proof, não mais hardcode); `PUBLIC_BASE_URL` no `--set-env-vars`; README/admin.py. OAuth redirect_uri NÃO deriva de `public_base_url` (usa `request.url_for`) → mudança segura. Family: config-drift pós-migração. [investigação 2026-07-02] |
| **F69** | HIGH | investigação 2026-07-02 | 2026-07-02 (gcloud + `ab14268`) | **O Cloud Scheduler do resync diário não existia no projeto novo — o resync rodava pelo projeto ANTIGO.** `gcloud scheduler jobs list` no projeto `v4-ads-mcp` = 0 items; o job `v4-ads-mcp-resync` nunca executara. Mas o `audit_log` (DB compartilhada) tinha rows diárias de `meta_resync`/`account_resync` — era o scheduler do `v4-ads-mcp-prod` mantendo o cache vivo. Decomissionar o projeto antigo mataria o resync silenciosamente (cache Meta congelaria). **Fix:** recriado `v4-ads-mcp-resync-daily` (cron `0 6 * * *` BRT) no projeto novo com SA dedicada least-privilege (`v4-ads-mcp-scheduler` + `roles/run.invoker` no job); validado via `scheduler jobs run` → HTTP 200 → execução Completed. Depende do F66 (jobs precisavam funcionar primeiro). Family: infra-órfã pós-migração. [investigação 2026-07-02] |
| **F70** | MED | investigação 2026-07-02 (cutover Pedro) | 2026-07-02 (`8520aea`) | **Falha de decrypt do token virava "Erro interno" genérico no cutover.** No cutover, o refresh token do gestor foi cifrado com a `aes-master-key` ANTIGA; o serviço novo tem a chave regenerada → `decrypt_refresh_token` levanta `InvalidCiphertextError`. Mas `build_client_for_manager` é chamado FORA do wrap de `to_friendly` de cada executor, então o erro cru chegava no `_error_envelope` e virava "Erro interno ao executar a ferramenta" — zero acionável. Pedro ficou ~9min preso (6 erros no `audit_log` 07-02 13:33-13:35) até reconectar. **Fix:** `build_client_for_manager` converte `InvalidCiphertextError` na ORIGEM via `to_friendly` (mapeamento novo → mensagem PT-BR "reconecte sua conta Google no painel" + URL); cobre TODOS os executores. `to_friendly` idempotente (não re-embrulha `GoogleAdsFriendlyError`). Family: error-UX-não-acionável (irmã de F62), agravada pela migração de chave. [investigação 2026-07-02] |
| **F71** | HIGH | investigação 2026-07-02 (auditoria de segurança) | 2026-07-02 (`25fd1cc`) | **Customer Match (mutate de PII) não gravava audit_log nem contava rate-limit.** `run_offline_user_data_job` (`src/google_ads/customer_match.py`) fazia 3 chamadas de API (create/add/run de membros de lista de remarketing) mas — diferente de `run_conversion_upload` e `run_mutation` — não tinha `before_call`/`record_actual`/`audit_log.record`. Um mutate LGPD-sensível (add/remove de até 1000 membros hash de e-mail/telefone) ficava invisível em `get_my_audit_log`/`detect_drift`; incident response cego, sem prova de quem/quando; e as 3 calls não contavam na quota. **Fix:** espelha o padrão de `run_conversion_upload` (audit sempre + rate-limit em sucesso E erro; `params_summary` só metadados, nunca os hashes). No erro grava audit e levanta o friendly. Family: governança-ausente (audit gap). [investigação 2026-07-02] |
| **F72** | HIGH | investigação 2026-07-02 (auditoria de segurança) | 2026-07-02 (`b1cb1e7`) | **Gate Meta era fail-open por convenção — `ad_account_id` opcional.** O hard-gate do Modelo B (token compartilhado; a matriz de acesso é o único freio) lia `ad_account_id = params.get("ad_account_id")` e só checava `if ad_account_id:`. Um tool futuro (M.5) que montasse o edge da Graph e esquecesse o param rodaria SEM gate, lendo qualquer das 19 contas do BM — a mesma classe F57 que já mordeu o `validate_gaql` no Google. **Fix:** `ad_account_id` vira kwarg OBRIGATÓRIO de `run_meta_graph_get` e o gate roda incondicional; impossível pular. Os 6 call-sites já tinham o valor no escopo. Guard estrutural F57-Meta (`build_meta_api` só em reports.py) acompanha. Family: hard-gate-bypass (F57 variante Meta). [investigação 2026-07-02] |
| **F73** | MED | investigação 2026-07-03 (gap de teste → bug latente) | 2026-07-04 (`510cd9d`) | **Quota leak: chamada bloqueada no teto DECREMENTAVA o contador → cap diário virava "soft cap".** Nos executores Google (`run_report`, `run_conversion_upload`, `run_offline_user_data_job`), `before_call` ficava DENTRO do `try` e levantava `QuotaExhausted` ANTES de persistir a reserva (o `conn.transaction()` interno de `rate_limit.py` aborta); mas o `finally`/caminho de erro chamava `record_actual(actual_ops=0, estimated_ops=N)` → delta `-N` incondicional (`GREATEST(0, used + delta)`) → cada chamada bloqueada liberava quota pra próxima. No teto de 15k ops o freio nunca segurava um loop de cliente LLM (exatamente quando importa). `run_mutation` era imune por acidente (reconcilia `actual=target_count` → delta 0). **Fix:** flag `reserved` — `before_call` movido pra transação EXTERNA (`async with pool.acquire() as conn, conn.transaction()`), `reserved=True` só após reservar; `record_actual` gated por `if reserved`; audit continua SEMPRE. Mesmo diff adicionou **cap diário por gestor** (2ª chave `mgr:<uuid>` em `rate_counters`, `daily_limit=settings.manager_daily_quota` default 5000) — antes o rate-limit era só global no dev-token, então um gestor em loop esgotava a quota de todos. 9 testes novos (QuotaExhausted por executor → `record_actual` não chamado + audit gravado). **`run_recommendation_action` (5º executor, apply/dismiss_recommendation) ficou de fora no 1º diff** (o brief dizia "4 executores") e o **whole-branch review pegou** (2026-07-04, `d6ac558`): o cap por gestor tinha um buraco por onde as 2 ações de recommendation passavam (o quota-leak em si não, pois `record_actual(actual=1,estimated=1)` dá delta 0 — imune como o run_mutation). Fechado com o mesmo padrão `reserved`. **Lição:** ao aplicar um padrão "a todos os executores", `grep` TODA função que chama `before_call`/`build_client_for_manager` (parente de F57). Nota operacional: `MANAGER_DAILY_QUOTA` não setado no Cloud Run (usa default 5000) — monitorar `rate_counters WHERE developer_token_id LIKE 'mgr:%'` na 1ª semana. Family: governança-ausente (reconciliação de quota; irmã de F71). [investigação 2026-07-03, completado no review 2026-07-04] |

---

## Bug class 2: Schema/serialization gaps (Anthropic API + MCP transport)

**Pattern:** JSON Schema constructs that Anthropic API or MCP client doesn't support.

**Mitigation convention:** ver [`convencoes/testes.md`](../convencoes/testes.md) (composition keywords) e [`convencoes/dados.md`](../convencoes/dados.md) (date range).

| # | Severity | Discovered | Fixed | Summary |
|---|---|---|---|---|
| **A2** | LOW | 3b.5 | 3b.5 | GAQL parens bug + REMOVED retrofit gap em 4 status ops. Status ops cap restritos a `["ENABLED", "PAUSED"]`. |
| **F1** | CRIT | dogfood 2026-05-15 | 3b.20 | `date_range` object `{from, to}` rejected — schema sem `type` field fez Claude serializar dict como JSON-stringified literal; `parse_date_range` chamou `.upper()` corrompendo keys. Fix: explicit `type: "string"` + new `start_date`/`end_date` params + defensive JSON parse. [phase-3b-20-bootstrap.md] |
| **F2** | MED | dogfood 2026-05-15 | 3b.20 | `get_search_terms_report.limit` default 500 stourava token cap. Fix: default 500 → 50. [phase-3b-20-bootstrap.md] |
| **F22** | MED | 3b.21 | 3b.23 | `get_negative_keywords_audit` em MO-JP (467 negativas) pós-enrichment retornou 81k chars, excedeu MCP cap. Fix: `limit` param default 100. [phase-3b-21-bootstrap.md, phase-3b-23-bootstrap.md] |
| **F26** | MED | 3b.19B | 3b.22 doc | Google limita 1 RuleSet CUSTOMER-level por conta (undocumented constraint). Doc fix em tool description, sem pre-flight (option (a) — let Google's error surface). |
| **F28** | LOW | 3b.23 | not-fixable | MCP client schema cache propagation lag pós-deploy: client cache não auto-refresh quando new tool/param shipped. Workaround: restart Claude Code session. Characteristic do MCP transport. |

---

## Bug class 3: Pre-flight + test convention (mock target mistakes)

**Pattern:** Adding a pre-flight call to an existing mutate tool — existing integration tests fail to mock the new helper because helper's `run_report` import lives in `_common.py` namespace (not tool's). Slips local fast pre-push gate but caught by CI DB integration step.

**Mitigation convention:** ver [`convencoes/testes.md`](../convencoes/testes.md) (pre-flight test convention).

| # | Severity | Discovered | Fixed | Summary |
|---|---|---|---|---|
| **F14** | LOW | 3b.14 | 3b.15 doc | `create_ad_group` description claimed "NÃO idempotente" but Google ENFORCES name uniqueness within campaign. Idempotency-by-error effective via Google server-side check. [phase-3b-14-bootstrap.md] |
| **F15** | CRIT | 3b.14 | 3b.14.1 | `import_all_tools()` em `_registry.py` era manual hardcoded list — Sprints 3b.12+13+14 shipparam 3 new tools mas esqueceram atualizar lista → tools DEAD em prod apesar de tests passing (pytest import side effects masked). Fix: `pkgutil.iter_modules` auto-discovery. |

---

## Bug class 4: UX / dogfood ergonomics

| # | Severity | Discovered | Fixed | Summary |
|---|---|---|---|---|
| **UX-1** | LOW | 3b.6/3b.7 | 3b.7 | `conversions_value == conversions` (1:1 ratio) sinal de placeholder tracking; ROAS misleading. Helper `value_proxy_warning` em `get_account_overview` + `get_funnel_metrics`. V4 accounts default a 1:1 tracking (out-of-MCP-scope finding). |
| **UX-2** | LOW | 3b.6/3b.7 | 3b.7 | proto-plus v20 repr regression — `str(enum).split(".")[-1]` retornava `"2"` em vez de `"ENABLED"`. Fix: `.name` access em 22 call sites across 10 read tools. |
| **UX-3** | LOW | 3b.6/3b.7 | 3b.7 | Same as UX-2 (same bug, different surface). Found via P1b dogfood. |
| **F7** | LOW | P3 dogfood | 3b.9 | `get_recommendations.type_pt` duplicava `type` quando PT-BR mapping ausente. Fix: null fallback signaling "use type field, no translation available." |
| **F13** | MED | 3b.14 | 3b.15 | `create_*` responses não retornavam new entity resource_names. Fix: extract via `WhichOneof("response")` + `getattr` em `run_mutation`. **Cross-cutting feature** — all future creates auto-inherit. Validated 5+ times in production smokes. |

---

## Bug class 5: Runbook typos (low severity, documentation fixes)

| # | Severity | Discovered | Fixed | Summary |
|---|---|---|---|---|
| **F24** | LOW | 3b.19B | 3b.19B doc | Smoke runbook usou `geoTargetConstants/20114` como "São Paulo" — actually British Columbia (Canada). V4 BR pre-flight rejeitou corretamente. Runbook fixed inline. |
| **F29** | LOW | 3b.24 | 3b.24 doc | Runbook usou `geoTargetConstants/20180` como "SP state" — actually Hunan (China). Correct SP state via GAQL lookup = `geoTargetConstants/20106`. V4 BR pre-flight rejeitou corretamente. |
| **F23** | LOW | 3b.21 | 3b.38 | `get_change_history LAST_30_DAYS` Google rejects "start date too old" — preset hits retention boundary (Google quer start_date > today-30, preset resolve pra yesterday-29 = today-30, borda exclusiva rejeitada). Reconfirmado em dogfood 2026-05-25 MO-JP+CAB B7 (medium severity, UX confusa pq preset oferecido pela tool é rejeitado pelo backend). **Fix Sprint 3b.38:** tool `get_change_history` auto-clamp `start_date` pra `max(start, today-28)` quando preset usado (margem 2-day safety contra UTC drift) + warning `date_range_warning` na response. Non-breaking — custom `start_date`/`end_date` (e legacy `date_range={"from","to"}` dict) honram intent do usuário sem clamp. 2 regression tests novos (clamp + no-warning negative). |

---

## Bug class 6: Google constraint (not a code bug, document as known limitation)

| # | Severity | Discovered | Fixed | Summary |
|---|---|---|---|---|
| **F36** | HIGH | 3b.24 | doc-only | `TARGET_CPA` + `TARGET_ROAS` rejeitam em accounts sem conversion data history. Nutry sandbox tem 14+ conversion actions de 3b.19A mas zero real data → reject. Real V4 production accounts (com tracking history) funcionam. Tool description documenta. |
| **F41** | LOW | 3b.26 | doc-only | Nutry sandbox sem traffic recente (zero clicks LAST_90_DAYS) — `click_view` retorna empty → real gclids não disponíveis pra T4-T6 happy paths em `import_offline_conversions`. Não é Sprint 3b.26 bug; é smoke-environment limitation. Workaround: T7 partial_failure path com fake gclids valida dispatcher + parsing end-to-end (UNPARSEABLE_GCLID error_code retornado bit-a-bit). Real production V4 accounts com gestor inputando gclids ativos vão funcionar. Smoke runbook updated com guidance. |
| **F45** | LOW | 3b.28 | doc-only | Nutry sandbox sem CRM_BASED_USER_LIST disponível pra smoke T7-T11 do `upload_customer_match_list`. Customer Match terms acceptance pré-requisito requer Google Ads UI manual + provavelmente não aceitável em sandbox (4 user_lists existentes são todas RULE_BASED/LOGICAL + read_only). Tool funcionalmente validada via Layer 1/2/3 reject paths (T1-T6 PASS) + 31 unit tests + 5 integration tests (incluindo LGPD raw-query verification de payload sem plaintext em pending_confirmations). Não é Sprint 3b.28 bug; é smoke-environment limitation similar a F41. Real V4 production accounts com Customer Match policy aceita vão funcionar. [phase-3b-28-bootstrap.md] |

---

## Bug class 7: Strategic decisions (ecosystem constraint, not-a-bug, decision documented)

**Pattern:** Provider (Meta/Google) impõe constraint não-código que requer decisão estratégica V4 — escolha entre re-tentar atender critério OU aceitar limitação como permanente. Registrar pra evitar re-investigação futura quando alguém perguntar "por que está em X mode?".

| # | Severity | Discovered | Decision | Summary |
|---|---|---|---|---|
| **D3** | INFO | Sprint 3b.39 Wellington config attempt 2026-05-25 | Server-side per-tool _meta via anthropic/alwaysLoad | **D2 estava parcialmente errado.** Pré-Wellington-config attempt, WebFetch direto a Claude Code docs oficiais (https://code.claude.com/docs/en/mcp#scale-with-mcp-tool-search) revelou: **(1) Claude Code já tem `ENABLE_TOOL_SEARCH=true` por DEFAULT v2.x — todas MCP tools são deferred automaticamente sem config Wellington needed**; **(2) `defer_loading: true` em settings.json `tools[]` array NÃO existe no schema Claude Code** — era best-guess errado D2; **(3) mecanismo correto pra promover always-loaded é per-tool `_meta.anthropic/alwaysLoad: true` (server-side, MCP standard field)** OR `.mcp.json` server-level `alwaysLoad: true` (toda tool do server). Pra V4 Ads MCP (21 always + 38 defer no MESMO server), granularidade per-tool requer `_meta` approach. **Fix Sprint 3b.39 D3 commit:** `src/mcp/server.py` adicionar `_build_tool_meta(bucket)` helper que retorna `{"com.v4company/bucket": bucket}` sempre + `"anthropic/alwaysLoad": True` quando bucket="always". Defer tools omit anthropic/alwaysLoad → Claude Code defaults to deferred. **Resultado:** Wellington NÃO precisa tocar `~/.claude/settings.json` — fix é 100% server-side, deploy ship → Wellington restart Claude Code → 21 tools always-loaded + 38 tools via Tool Search Tool default. **Lição reinforced (3× consecutiva):** sempre verificar docs oficial cliente ANTES de design refactor cross-layer. D1 (Meta App Review) → D2 (defer_loading client-side API) → D3 (real mechanism is per-tool _meta server-side). Cada research saved 2-3 dias wasted work. **Runbook update needed:** `phase-3b-39-bootstrap.md` T3 procedure (Wellington manual settings.json edit) é obsoleto — substituir por "deploy aplica + Wellington restart Claude Code". 3 unit tests novos cobrindo `_build_tool_meta` helper + end-to-end count check. [src/mcp/server.py + tests/unit/test_mcp_server_meta.py + docs Claude Code WebFetch 2026-05-25] |
| **D2** | INFO | Sprint 3b.39 OQ1 research 2026-05-25 | Caminho server-metadata-only + client-config | **MCP `defer_loading` é parâmetro CLIENT-SIDE da Anthropic Messages API, NÃO server metadata.** Research OQ1 do refactor arquitetural confirmou via [Anthropic advanced-tool-use docs](https://www.anthropic.com/engineering/advanced-tool-use): `defer_loading: true` é configurado em `client.beta.messages.create(tools=[...])` com beta header `advanced-tool-use-2025-11-20`. Tool Search Tool é Anthropic-provided special tool (`tool_search_tool_regex_20251119`), NÃO pattern MCP server. **Implicação V4 Ads MCP:** server-side mudou de "modificar list_tools()" pra "expor bucket metadata via description prefix `[CORE]`/`[DEFER]` + `_meta.com.v4company/bucket` structured field". Wellington manual configura `~/.claude/settings.json` com defer per-tool baseado em prefix. **Lição reinforced:** sempre research API features cross-layer (client vs server) ANTES de design — Fase 1 inicial spec assumiu server-side incorrectly, descoberto via writing-plans skill research pré-implementation (~2-3 dias wasted work prevented). **Implementação Sprint 3b.39:** (1) `@register_tool` decorator add `bucket: Literal["always", "defer"]` kwarg (commit 6e1ddc9); (2) MCP SDK `Tool._meta` field populated com `{"com.v4company/bucket": "always"|"defer"}` em `list_tools()` (commit 2ede685, MCP SDK 1.22.0 supports); (3) Mass-tag 59 tool files: `# bucket:` line 1 + `[CORE]`/`[DEFER]` prefix em description + `bucket="always"|"defer"` kwarg (commits 7e64834 + ac0941a + e376898); (4) Runbook `phase-3b-39-bootstrap.md` 6 tests + Wellington Claude Code config procedure step-by-step (commit ad2c12c). Final state: 21 always + 38 defer = 59 tools. [phase-3b-39-bootstrap.md + spec refactor §5 + commits 3b.39] |
| **D1** | INFO | M.2b App Review 2026-05-25 10:58 GMT-3 | Caminho B+ — Janela observação 30-45 dias | **Meta App Review respondeu: `public_profile` ✅ APROVADA, `Marketing API Access Tier` ❌ REJEITADA.** Motivo Meta literal: *"Our records do not show a sufficient number of Ads API calls in the last 15 days by this application. It is required that the application successfully integrate with the Ads API before it is approved for Marketing API standard access tier."* **Critérios exatos Meta (docs oficial revisão pós-rejeição):** (1) ≥500 chamadas Marketing API/15d — **atualizado, era 1.500 antes**, (2) <15% error rate nas últimas 500 calls. **Nomenclatura ATUALIZADA (atenção pra documentação não-stale):** "Standard Access" agora é **Limited Access** (default sem App Review), "Advanced Access" agora é **Full Access** (o que rejeitou aqui). 2 conceitos diferentes coexistem: **(a) Nível de acesso à API de Marketing** Limited/Full (volume + escala) — rejeitado aqui; **(b) Nível de acesso ao recurso** Standard/Advanced (cada permission individual) — Standard auto-aprovado pra business apps. **Red flag Limited Access (docs Meta literal):** *"Volumes extremamente limitados por conta de anúncios. Somente para desenvolvimento. NÃO para apps em produção visualizado para um cliente publicitário."* Tradução prática: throttle agressivo + risco em uso real Wellington nos 12 ad_accounts V4 LS&Co se ficar permanente. **Decisão Wellington Caminho B+ (não Caminho A permanente, não Caminho B forçado):** janela observação 30-45 dias. Strategy: **acelerar M.3+ pra ship mais tools Meta** (`meta_get_campaign_performance` etc) → Wellington usa naturalmente day-to-day → volume cresce → ~30-45 dias atinge 500 calls cumulativas → **re-submit Full Access** com fundamento. **Por que NÃO Caminho A permanente:** risk throttle production. **Por que NÃO Caminho B forçado** (3×/dia em 12 contas = 540 calls em 15d): waste Wellington time, melhor cadência natural. **Por que Caminho B+ ganha:** balance esforço/benefício — M.3+ teria sido shipped de qualquer jeito (roadmap original M.1-M.25), e volume gerado é byproduct. **Monitorar:** `meta_rate_counters` table X-Business-Use-Case-Usage — se Wellington bater throttle real antes da janela completa, priorize re-submit imediato. **Decision gate atualizado:** continuar roadmap M.3-M.25 = ≥3 calls/semana dogfood Wellington (não-mais "App Review APPROVED" como pré-req); senão pivot Google. **Action quando colab entrarem:** add como App Roles → Administrators no Meta Dev Console (Limited Access permite 25 admins/testers). **Re-submit Full Access ON roadmap** (originalmente OFF na análise inicial pré-leitura docs) — agendado pra ~30-45 dias após volume natural atingido. [screenshot resposta App Review 2026-05-25 + docs Meta `developers.facebook.com/documentation/ads-commerce/marketing-api/get-started/authorization` + CLAUDE.md §Pending] |

---

## Summary and open items

| Metric | Count |
|---|---|
| **Unique catalog IDs** | **99** = 89 findings `F` + 7 hypotheses/design gaps `A` + 3 strategic decisions `D` (contados por regex sobre o arquivo, não estimados) |
| **Open product/infra work** | **10** — A4 (mecanismo real de exclusão Customer Match), F67 (custom domain via Load Balancer), **F91/F94-F100** (investigação 2026-08-14/15; 7 abertos) e **F82 parcial** (vazamento fechado; restam 3 call-sites com segredo na query string, pendentes de probe empírica). Fechados: F83-F90, F92 e F93 (F82 parcial). |
| **Strategic decisions** | **3** — D1/D2/D3 |
| **Closed, mitigated or explicitly documented** | **73** — todos os demais IDs; inclui limitações conhecidas e hipóteses refutadas, não apenas mudanças de código |

> A contagem anterior (`57`) estava stale porque não incorporava de forma consistente F57-F76/A7. A contagem foi auditada por IDs únicos ao registrar F77 e novamente ao registrar F82-F99.
>
> **Atenção ao ler este catálogo hoje:** pela primeira vez o número de itens ABERTOS é significativo (20 de 96). Até 2026-08-11 o catálogo era essencialmente um registro de coisas já resolvidas; F82-F99 são backlog vivo. Antes de mexer em auth/OAuth, executores de mutate, jobs de resync, tools Meta ou no design system, cheque se já existe finding aberto na área.

---

## Cross-reference: Sprint → findings introduced

(Sprints e sessões recentes; para o histórico completo, veja `docs/operacao/sprint-history.md`.)

| Sprint | Findings introduced |
|---|---|
| 3b.28 | F45 (env limitation, doc-only) |
| 3b.33 | F46 (GAQL BETWEEN end_date midnight-exclusive → 3b.34 fix) |
| M.2a | A6 (Meta OAuth domain check design error, fixed `e93a05b`), F47 (PowerShell pipe CRLF, procedural fix runbook) |
| M.2b | F48 (FacebookAdsApi.__init__ signature, fixed `a281c00`), F49 (button() macro default type, fixed same-session) |
| Retrospective (audit_log 2026-05-18) | F50 (produção confirma TypeError F33 — audit_log id=140), F51 (produção confirma AttributeError F37 — audit_log id=149) |
| 3b.38 | F52 (audit_zombie_keywords não filtra ad_group.status — órfãs cosméticas em ad_group REMOVED), F23 promoted "known limitation" → "fixed" (get_change_history LAST_30_DAYS clamp + warning) |
| M.2b App Review response | D1 (Meta App Review Full Access rejected — decisão Caminho B+ janela observação 30-45 dias, acelerar M.3+ pra volume natural, re-submit Full Access após 500 calls/15d) |
| 3b.39 | D2 (hipótese client-side) + D3 (mecanismo final server-side via `_meta.anthropic/alwaysLoad`) |
| 3b.40 | F56 (keywords negativas misturadas no relatório de performance) |
| Sessão 2026-05-28/29 | F57-F60 (hard-gate, cursor/transação, JOIN ambíguo, gestor inativo) |
| Sessão 2026-06-19 | F61-F63 (paginação Meta, UX GAQL, clamp do change history) |
| Sessão 2026-06-30 | F64-F67 (token Meta, deletion detection, jobs CNB, domain mapping) |
| Sessão 2026-07-02 | F68-F72 (cutover, scheduler, governança Customer Match e gate Meta) |
| Sessão 2026-07-04 | F73-F75 (quota/cap por gestor + UI/UX HTMX) |
| Sessão 2026-07-22 | A7 + F76 (hipótese de acento refutada; reconnect do auth path) |
| Sessão 2026-07-23 | F77 (deep health resiliente a conexão DB stale); F76 validado em produção |
| Sessão 2026-08-11 | F78-F81 (hambúrguer fantasma deslogado; offsets sticky não-medidos; colisão de shorthand entre modificadores CSS; filtros de tabela mortos por id inexistente) |
| Sessão 2026-08-14/15 | F82-F100 (investigação ampla, 6 auditorias paralelas — **F83-F90, F92 e F93 fechados, F82 com o vazamento fechado e causa raiz parcial; 7 abertos**): F82-F84 segurança/integridade · F85-F90 correção dos dados entregues ao gestor · F91-F94 infra/jobs/resiliência · F95-F99 higiene, dívida e doc-drift |
| Sessão 2026-08-19 | F101-F117 (três investigações no mesmo dia: frontend F101-F108, backend F109-F112, infra/CI F113-F117 — todas fechadas) |
| Sessão 2026-08-20 | F118-F127 (revisão de responsividade: 9 telas com scroll horizontal em 375px, header estourando em 768px, scrollers sem teclado — todos fechados) · F128 (conta Meta que sai da parceria nunca saía do inventário; superado no mesmo dia pela reconciliação) · **F129** e **F130**, abertos (governança do system user; gate do Google sem `is_active`) |

---

## Lessons reinforced

1. **Per-value empirical probe** (Sprint 3b.19A.1 convention) is essential for ANY new mutate tool with enum whitelists. Without it, design gaps reach production. **Without exception, every "design-gap-via-SDK-ambiguity" finding was caught by per-value probe in smoke.**
2. **Mock fidelity matters** (F16 lesson) — ProtoFieldCapture mocks must mirror real proto-plus API. `.add()` vs `.append()` distinction caused F16.
3. **Smoke against real account, not pre-flight only.** Builder tests + dry_run validate code path; real API call validates Google's runtime acceptance. The 7 findings from Sprint 3b.24 (F30+F32+F33+F34+F35+F36+F37) were all surfaced ONLY in apply step — not dry_run, not unit tests.
4. **CI catches what fast gate misses** (Sprint 3b.5/3b.8 lesson). Pre-flight test convention requires mocking new helper at TOOL's namespace, not helper's. Local `check_pre_push.py` skips DB integration; full sweep (`check_pre_push_full.py`) catches but requires Docker.
5. **Schema explicit type** (F1 lesson) — every JSON schema property MUST have explicit `type` field; otherwise Claude/MCP client may serialize as string literal causing parsing bugs downstream.
6. **`CapturedOp._SubCapture.__setattr__` captura qualquer campo silenciosamente** (F51 lesson) — `_SubCapture` não valida se o campo setado existe no proto real. Builder que seta `campaign.start_date` passa em testes mas lança `AttributeError` em produção. Mitigation: quando um sprint muda nomes de campos proto (renames, deprecations, v24 API surface changes), o builder test DEVE asserir via `.has("path.to.new_field") is True` E `.has("path.to.old_field") is False` simultaneamente. Sprint 3b.24.5 `test_builder_schedule_dates_set_when_provided` assertou o campo correto (`start_date_time`) mas NÃO assertou ausência do campo errado (`start_date`) — ausência check teria pego o bug antes do deploy. Convention nova para campos que trocaram nome: adicionar `assert campaign_op.has("...old_field") is False` em todo test de rename. [F51/F37]
7. **Audit tools devem expor status do parent resource** (F52 lesson — Lição V4 48) — tools `audit_*` que retornam child resources (keywords em ad_groups, ad_groups em campaigns) podem incluir items órfãos cosméticos em parents REMOVED. Item está tecnicamente ENABLED mas não compete em leilão / não impacta Smart Bidding. Batch operation neles é no-op + infla narrativa pro cliente ("pausei 280" quando só 110 importavam = 2.5×). Mitigation: SEMPRE expor `<parent>_status` field na response da audit tool (Opção C minimal — zero breaking change, consumer filtra client-side). Tool description avisa "filtre pelo campo `<parent>_status='ENABLED'` pra cleanup de impacto técnico real, OU mantenha tudo pra inventário cosmético". Aplicação: `audit_zombie_keywords` (F52 fixed 3b.38), futuras `audit_zombie_ad_groups`, etc. Pattern generaliza pra qualquer audit V4 com hierarquia parent-child. [F52, dogfood 2026-05-25 MO-JP+CAB]

---

## Sessão 2026-05-28/29 — access matrix + segurança + auditorias (findings F57+)

> Trabalho de acesso/segurança/UX (sem novas MCP tools). Detalhe: `session-2026-05-29-handoff.md`.

- **F57 (CRÍTICO) — hard-gate incompleto:** ao adicionar `ensure_account_access` aos executores Google (Plano A), `run_recommendation_action` (mutations.py) foi **esquecido** — `apply_recommendation`/`dismiss_recommendation` alcançavam conta não-concedida. Pego na 2ª auditoria do gestor. Lição: ao adicionar um gate/pré-flight a "todos os executores", **enumere via grep TODA função que builda o client** (`build_client_for_manager`), não só as óbvias (run_report/run_mutation). Há 6 choke points, não 5. **Instância adicional (2026-06-20, Onda 0):** `validate_gaql` era o único dos ~8 call-sites de `build_client_for_manager` sem `ensure_account_access` — vazava existência/schema de qualquer conta da MCC + bypassa rate-limit. Pego proativamente em auditoria de melhoria (não em incidente de produção); gated em `6506cd7`.
- **F58 (HIGH, pré-existente) — `export_csv_rows` cursor sem transação:** asyncpg server-side cursor (`async for row in conn.cursor(...)`) exige `async with conn.transaction():`. O CSV export estava quebrado em produção **desde sempre** — nenhum teste jamais iterou o generator (só checavam status code). O 1º teste a iterar de fato (filtro status, esta sessão) expôs `NoActiveSQLTransactionError`. Lição: generators de streaming com cursor PRECISAM de teste que **consuma** o output, não só dispare a rota.
- **F59 (MED) — coluna ambígua em JOIN:** `export_csv_rows` faz JOIN `audit_log al` × `managers m`; ambos têm coluna `status`. Filtro `WHERE status = ...` sem alias → `AmbiguousColumnError`. Sempre qualifique colunas com alias (`al.status`) em queries com JOIN — as outras clauses só não quebravam por serem únicas a uma tabela.
- **F60 (MED) — sessão MCP de gestor desativado:** `resolve_session_to_context` validava revoked+expired mas não `managers.is_active`. Gestor desativado mantinha acesso MCP até o token expirar. Fix: checar is_active na resolução.

## Lessons reinforced (cont.)

8. **`gh run watch --exit-status` engana** (esta sessão, 3×): o exit code do watch retornou 0 num run que FALHOU. **Sempre confirme a conclusão via `gh run view <id> --json conclusion`**, nunca pelo exit code do watch.
9. **`check_pre_push.py` local NÃO roda integration tests (testcontainers, sem Docker no Windows).** Bugs de SQL/transação/JOIN só aparecem no CI (8min). Ao mexer em queries com JOIN/cursor/streaming, prefira rodar `check_pre_push_full.py` (Docker) OU aceite que o CI é o validador — e corrija forward confirmando via `gh run view`.
10. **Auditoria persona-específica acha o que a ampla não acha** (2 auditorias do gestor esta sessão): a 1ª (genérica) pegou XSS/CSRF; a 2ª (foco no gestor não-admin) pegou o gate incompleto F57 + isolamento entre gestores. Re-auditar com persona estreita > re-auditar amplo.
11. **Segredo em query string é segredo no log de outra pessoa** (F82). Não basta auditar o que NÓS logamos: bibliotecas de terceiro logam por conta própria, e o httpx registra a URL inteira em `INFO`. Regra dupla: segredo viaja em header ou corpo, **e** todo cliente HTTP de terceiro tem o nível de log fixado explicitamente no `configure_logging`. Corolário de revisão: ao procurar vazamento, procurar por `params=` com nome de segredo, não só por `log.*(...)`.
12. **`finally` que faz I/O tem poder de veto sobre o resultado do `try`** (F83). Exceção levantada no `finally` descarta o `return` pendente — então bookkeeping (audit, contador, métrica) posto ali pode transformar uma operação bem-sucedida e **já aplicada no provider** em erro pro chamador, e ainda apagar o próprio registro dela. Todo `finally` com I/O precisa do próprio `try/except` que loga e engole. Vale especialmente onde o efeito colateral é externo e não-idempotente.
13. **Fix por classe precisa descer até o design system e os parsers** (F89/F90/F97). Três instâncias nesta investigação em que a correção anterior parou nos call-sites óbvios: o retrofit do F52 não alcançou `audit_competitor_keywords`; o fix de offsets do F79 corrigiu as templates mas não a regra `.v4-table--sticky-head`; e o fix dos campos Meta (F53/F54) corrigiu a query mas deixou o parser pedindo os campos removidos. Ao fechar uma classe, enumere as camadas — schema/query, parser, CSS compartilhado, description — não só os arquivos que apareceram no bug original.

14. **Métrica que existe num recorte não mede aquele recorte — quando o recorte é uma projeção** (probe de precedência 02/09). `customer_asset` e `campaign_asset` aceitam `metrics.*`, e a leitura natural é que cada linha mede aquele vínculo. Não mede: a métrica é atribuída ao **asset**, e as linhas de vínculo repetem o mesmo total por outro corte. Medido em 3 assets CALLOUT, o `customer_asset` deu **exatamente a soma** dos `campaign_asset` (300 = 178+122, 693 = 392+301, 850 = 520+330; idem cliques). Consequência prática: zero num vínculo não prova que ele não serviu, e não-zero não prova que serviu. **A regra geral:** antes de derivar um veredito de uma métrica, pergunte a que ENTIDADE ela está atribuída — se o recurso é um vínculo, uma view ou qualquer join, a métrica provavelmente pertence à entidade ligada, não à linha. Corolário que salvou este caso: quando existe campo de status publicado (`primary_status`), deduzir por métrica é escolher não olhar. [probe 02/09, spec `2026-09-02-ad-schedule-e-assets-design.md` §5.1]

---

## Sessão 2026-07-04 (2ª) — painel web UI/UX (findings F74/F75)

> Pacote de UI/UX do painel (templates Jinja2 + design system + rotas + HTMX; sem novas MCP tools). Detalhe: [`session-2026-07-04-ui-ux-handoff.md`](session-2026-07-04-ui-ux-handoff.md). Padrões novos no CLAUDE.md `Conventions → Design system`.

- **F74 (MED) — fragmento HTMX de reposição perde `hx-on`/`aria-label` após o 1º swap:** `_toggle_checkbox_fragment` (`routes.py`) devolvia o checkbox de reposição SEM o `hx-on::after-request` (toast + revert-on-fail) e sem `aria-label` → após o 1º toggle o feedback sumia e o input ficava sem label acessível. O HTML de origem nos 4 templates de matriz TINHA o `hx-on`; o fragmento servido pela rota, não. Fix: o fragmento re-emite o mesmo `hx-on` (string estática — sem vetor XSS novo; `hx-vals` seguem com `html.escape(quote=True)`) + `aria-label`. **Lição:** todo HTML de reposição servido por rota (não só o template inicial) DEVE reproduzir os handlers/atributos do original — senão o comportamento degrada silenciosamente após o 1º swap. Um unit test de escaping pré-existente quebrou legitimamente (o fragmento agora contém `this.checked`) → asserts migrados de substring frouxo (`"checked" in`) pra posicional (`'"checkbox" checked'`).
- **F75 (MED) — `htmx.ajax(url, { target: "closest tr" })` cai no `body` e pode apagar a página:** em `openConfirm` do cancelar-convite, o `target` string do `htmx.ajax` (API JS) resolve via `document.querySelector` — a sintaxe estendida `"closest tr"` NÃO é válida aí (só em atributos `hx-target`) → `querySelector` retorna `null` → o HTMX cai no fallback `document.body`; com `swap:"outerHTML"` isso **substituiria o `<body>` inteiro** pela resposta. Fix: `htmx.ajax("POST", url, { swap: "none" })` + a rota `cancel` virou HX-aware (`204` + `HX-Refresh: true`, que recarrega e atualiza contador + badge de graça). **Lição:** `htmx.ajax` (JS) ≠ atributo `hx-target` (HTML) — o primeiro não entende `closest/find/next`; passe um seletor CSS absoluto ou `swap:"none"`. O revoke de sessões já usava `target:"#sessions-table"` (por isso funcionava).

## Sessão 2026-07-22 — resiliência do pool DB (finding F76)

> Investigação de um `/mcp` 500 intermitente em produção (Gemini Cloud Assist deu o stack; validado firsthand nos logs por timestamp + frequência). Fix via TDD: `src/db/connection.py` (`run_with_reconnect` + lifetime) + `src/mcp/session.py` (wiring). Testes Docker-free em `tests/unit/test_db_connection.py` + `tests/unit/test_mcp_session.py`.

- **F76 (MED) — `/mcp` 500 intermitente (`mcp_auth_error`) por conexão asyncpg stale no pool (Supabase fecha socket ocioso):** o Cloud Run mantém conexões do pool ociosas; o Supabase eventualmente fecha o socket; o próximo request pegava a conexão morta e a query de auth (`mcp_sessions.find_by_hash`) levantava `ConnectionResetError [Errno 104]` → `asyncpg.ConnectionDoesNotExistError` no _statement prep_ → 500. ~5 em 14 dias, TODOS no auth path, desde 2026-07-09 (antecede a revisão corrente — NÃO é regressão; código/deps inalterados). Fail em ~14ms (falha imediata, não timeout downstream). Fix: `run_with_reconnect(op, attempts=2)` readquire conexão NOVA e re-roda o op idempotente em erro de conexão dropada (`asyncpg.PostgresConnectionError` + builtin `ConnectionError`); `UnauthorizedError`/query-errors propagam sem retry. `resolve_session_to_context` envolve o lookup nele (read → seguro re-rodar). Complemento: `max_inactive_connection_lifetime` 300s (default asyncpg) → 120s pra reap idle antes do remoto matar. **Validação D+1 (2026-07-23 21:16:14 UTC):** `db_dropped_connection_retry` ocorreu na tentativa 1 e o mesmo request MCP terminou 200 em 174,9ms; não houve `mcp_auth_error` pós-fix. **Lição:** pool asyncpg NÃO faz pre-ping — conexão fechada pelo remoto só é detectada no próximo statement; com serverless + remoto que derruba idle, o par certo pra raw asyncpg é **retry-com-reacquire** (readquirir do pool, NÃO reusar a mesma `conn`) + `max_inactive_connection_lifetime` < idle-timeout do remoto. NÃO é SQLAlchemy `pool_pre_ping` (projeto é asyncpg cru, sem ORM) nem `tenacity`. Sub-nota observabilidade: `log.exception` sai com `jsonPayload.level=error` mas o *entry severity* do Cloud Run fica DEFAULT (structlog emite `level`, não `severity`) → alertas por severidade não pegam esses 500. **Corrigido em seguida:** processor `add_cloud_logging_severity` em `logging.py` espelha `level`→`severity` (só no pipeline JSON, antes do renderer) → o Cloud Logging passa a elevar a entry; verificado end-to-end.

## Sessão 2026-07-23 — deep health resiliente (finding F77)

> Alerta de produção investigado a partir do e-mail do Cloud Monitoring. Detalhe e queries de validação: [`session-2026-07-23-handoff.md`](session-2026-07-23-handoff.md).

- **F77 (MED) — `/health?deep=1` bypassava a resiliência F76 e gerava 503 transitório em conexão stale:** o handler fazia `pool.acquire()` + `SELECT 1` diretamente. Quando o Supabase já havia fechado o socket ocioso, o probe falhava em 4-5ms com `connection was closed in the middle of operation`, embora um request MCP entre os probes retornasse 200. O alerta log-based amplo (`severity>=ERROR`) disparou por dois request logs 503; a policy de uptime, que exige falha sustentada, não abriu incidente. `max_inactive_connection_lifetime=120` reduz a chance, mas **não faz pre-ping** e não eliminou o caso: três falhas do health ocorreram depois do F76. **Fix (`23fccfe`):** o deep health passou a executar o `SELECT 1` via `connection.run_with_reconnect(...)`, com deadline global de 5s — menor que o timeout externo de 10s — e mantém 503 quando as duas tentativas falham ou o prazo estoura. Três testes cobrem stale→healthy (200/2 acquires), stale→stale (503/2 acquires) e timeout (503). CI com integração DB e deploy verdes; revisão `v4-ads-mcp-00028-lvc`, 100% do tráfego, sem ERROR após o deploy. **Lição:** todo probe/read idempotente que toca o pool precisa usar o mesmo boundary de reconnect dos hot paths; lifetime do pool é mitigação, não substituto de retry. Não aplicar retry cego a mutações.

## Sessão 2026-08-11 — pacote de frontend + smoke autenticado (findings F78-F80)

> Investigação de frontend com hipóteses **medidas no DOM de produção** (não deduzidas de leitura de código), seguida de smoke autenticado das telas admin via Claude in Chrome. Detalhe: [`session-2026-08-11-frontend-handoff.md`](session-2026-08-11-frontend-handoff.md).

- **F78 (MED) — hambúrguer e drawer renderizados deslogado, abrindo gaveta vazia e travando o scroll:** o `<button class="v4-header__hamburger">` e o `<div id="mobile-drawer">` ficavam fora do `{% if current_user %}` (só o *conteúdo* do drawer era condicional). A 375px, no `/login`, o botão aparecia (`display:block` pela media query), abria um painel com **0 links** e ainda aplicava `document.body.style.overflow='hidden'` — scroll travado numa gaveta vazia, na primeira tela que todo gestor novo vê. No mesmo header, o `justify-content: space-between` com `nav`/`user` ocultos jogava a marca pro canto direito (medido: x=241–359 em vez de x=16). **Fix (`aebdb8f`):** botão, drawer e o `<script>` do `toggleDrawer` passaram a exigir `current_user`; guard `if (!drawer) return;`; `.v4-header__brand { margin-right: auto }` **só** dentro da media query mobile (desktop intacto). **Lição:** um elemento cuja *visibilidade* é controlada por media query ainda precisa da condição de *existência* no servidor — CSS esconde, não remove; e `space-between` num container cujo número de filhos visíveis muda por breakpoint precisa de âncora explícita.

- **F79 (MED) — offsets sticky eram números mágicos que nunca bateram com o DOM real:** `--v4-tab-bar-offset: 96px` / `--v4-subnav-offset: 53px` assumiam um header de 53px. Medido em produção: o header tem **65px** (o botão "Sair" do `.v4-header__user` tem 40px de altura, não os 28 que o comentário assumia) e a subnav **55px**, não 43. Consequência: toda barra sticky grudava **12px alto demais** e deslizava por baixo do header, e o cabeçalho de dia da `/audit` ficava 33px sob a barra de filtros. Pior caso: **`/admin/audit` usava `--v4-subnav-offset` (só header) numa página que TEM a subnav admin** — a barra de filtros grudava no mesmo topo da subnav e a cobria por inteiro (mesmo z-index e vindo depois no DOM); na captura, a subnav aparecia cortada no meio da palavra "Aud…". **Fix (`fc8c0a8`):** valores medidos (`65/55/88`, com override de 61px no mobile onde o "Sair" some) e `/admin/audit` migrada pro `--v4-tab-bar-offset`. Guard: nenhuma template em `admin/` pode usar `var(--v4-subnav-offset)`. **Lição:** offset sticky é altura medida, não estimada — e o mesmo token não serve pra contextos com profundidade de pilha diferente (`/audit` tem header; `/admin/audit` tem header+subnav). Derivar por `calc()` a partir de uma altura só melhora a manutenção, mas **não corrige a altura errada**: medir no DOM é o passo que faltava.
  **Desdobramento (`eab6099`) — o valor medido também apodrece:** a barra de filtros da `/audit` embrulha conforme a largura — 88px a partir de **831px**, 164px a partir de **618px**, 240px abaixo disso. Os pontos de quebra emergem da largura do conteúdo e não coincidem com breakpoint padrão algum (640/768/1024), então o offset já estava errado por 76px em qualquer janela entre 618 e 831px — **não era um problema só de mobile**, e nenhuma media query com literal acertaria em toda janela (nem sobreviveria a alguém adicionar um filtro). Fix: um `ResizeObserver` em `_base.html` publica a altura real em `--v4-filter-bar-h` (0 quando a barra não está sticky); o literal em `v4-tokens.css` vira fallback sem-JS. Marcação declarativa via `data-sticky-measure`, aplicada só na barra cuja altura alimenta um offset. **Lição final:** quando a altura de um elemento de layout é emergente (wrap, conteúdo variável), a medição precisa ser **contínua** — um snapshot, por mais correto que esteja no dia, apodrece na primeira mudança de largura ou de conteúdo.

- **F80 (LOW) — shorthand `padding` de um modificador anulando o `padding-left` de outro:** `.v4-input--small` (`padding: 4px 8px`) é declarado **depois** de `.v4-input--search` (`padding-left: 36px`) com a mesma especificidade (0,1,0). Nos campos de busca das matrizes de acesso, que usam as duas classes, o shorthand zerava o espaço reservado e o ícone de lupa (18px em `left:10px`) ficava **por cima do placeholder** — renderizava "🔍scar gestor…". **Fix (`fc8c0a8`):** regra combinada `.v4-input--search.v4-input--small { padding-left: 32px }` (0,2,0), preservando o padding vertical compacto. **Lição:** modificador que usa shorthand (`padding`, `margin`, `background`, `border`) apaga as longhand de qualquer modificador irmão declarado antes. Ao criar um modificador combinável, prefira longhand — ou adicione a regra de interseção.

**Nota de método (3 ocorrências nesta sessão):** guard grep-based deve casar a **forma de uso** (`var(--token)`, `aria-atomic=`, `'unsafe-eval'` no valor da policy), nunca o token nu — o comentário que *explica* a regra contém a string e dispara o próprio guard. Corolário no Tailwind: o scanner lê o arquivo inteiro, comentários incluídos — citar o nome de um utilitário num comentário **gera CSS** (aconteceu com `font-light`).

## Sessão 2026-08-11 (cont.) — CSP sem script inline (finding F81)

> Refatoração dos handlers inline pra permitir `script-src` sem `'unsafe-inline'`. Detalhe: [`session-2026-08-11-frontend-handoff.md`](session-2026-08-11-frontend-handoff.md).

- **F81 (MED) — os 4 filtros de tabela do painel estavam mortos em produção:** `filterManagers()`, `filterAccounts()`, `filterAccs()` e `filterMetaAccs()` começavam com `document.getElementById('<id>').value`, mas o input vinha da macro `search_input`, que emite **`name=`, não `id=`**. Resultado: `getElementById` retornava `null` e a função lançava `Cannot read properties of null (reading 'value')` a cada tecla. Como os selects de role/status/MCC chamavam a MESMA função, eles caíam junto — a tela de Gestores tinha três controles de filtro e nenhum funcionava. Passou despercebido porque falha em silêncio (exceção em handler inline não quebra a página) e nenhum teste exercita JS. **Fix (`bfd438d`):** o mecanismo declarativo novo mira o controle pelo atributo `data-v4-filter`, não por id — o acoplamento que quebrava deixou de existir. Verificado em produção: buscar "wellington" filtra 4→1 linhas, o select de role idem, e limpar restaura. **Lição:** handler inline que chama função global falha mudo; e macro que gera markup precisa emitir o que o consumidor assume (aqui, `id`). Um guard grep-based não pegaria — o que pegaria é um teste que exercita o JS, que o projeto não tem.

**Nota de método — a CSP como detector:** apertar `script-src` transformou "handler esquecido" de bug silencioso em erro observável. Um `onclick` sobreviveu à varredura estática porque estava dentro de uma string Jinja com aspas **escapadas** (`\"`) passada pra macro `modal()` em `admin/index.html`; o regex do guard só casava aspa normal. Foi pego varrendo as 14 telas renderizadas em produção, e o guard passou a casar `\?["']`. Quando o alvo é remover uma permissão, a varredura precisa ser no HTML **servido**, não só no source.

---

## Sessão 2026-08-14 — investigação ampla de bugs e gaps (findings F82-F99)

> Investigação sem escopo prévio ("investigue bugs e gaps"), executada como 6 auditorias paralelas read-only sobre áreas independentes: tools MCP, painel web, auth/acesso, DB/jobs/governança, núcleo Google/Meta e CI/tooling/doc-drift. **Todo finding abaixo foi reaberto e confirmado no código pelo controller antes de ser catalogado** — nada entrou por relato de subagente. **Nenhum está corrigido**; esta seção é backlog, não changelog.
>
> Três dos itens (F82, F87, F93) são follow-ups deferidos em 2026-07-04 que seguiam no ar — e dois deles se revelaram **maiores do que o registro original dizia**.

### Segurança e integridade

- **F82 (HIGH) — segredos do Meta vazam em texto puro pro Cloud Logging, pela URL do request:** o httpx 0.28.1 loga `request.url` **completa, com query string**, em `logger.info` ([`_client.py:1740`](https://github.com/encode/httpx)); `configure_logging` chama `basicConfig(level=info)` ([`logging.py:55`](../../src/logging.py)) e **nada em `src/` silencia o logger `httpx`** (grep por `getLogger`: zero ocorrências) → o registro cai no stdout, que no Cloud Run é o Cloud Logging. O código Meta põe segredo em `params=`, ou seja, na query: `client_secret` na troca short→long-lived ([`meta_oauth.py:271`](../../src/auth/meta_oauth.py)), app access token no formato `app_id|app_secret` no `debug_token` ([`:316`](../../src/auth/meta_oauth.py)), e o **token system-user all-targets** em `/me/adaccounts` ([`:140`](../../src/auth/meta_oauth.py)) — que ainda reaparece a cada iteração, porque a URL de `paging.next` do Graph já traz o `access_token` embutido. **Por que é grave NESTE projeto:** o token system-user **não expira** e é o que dá acesso às ~19 contas do BM; no Modelo B a matriz de acesso é o único freio e ela vive na camada MCP, então quem tiver leitura no Cloud Logging contorna a matriz inteira sem passar por gate nenhum. **O lado Google faz certo e serve de referência:** `data=` no corpo do POST na troca de token e header `Authorization: Bearer` no userinfo ([`oauth.py:219,247`](../../src/auth/oauth.py)) — nada na URL. **Este é o item "OAuth logs sem body" deferido em 07-04 — e o registro subestimava:** dizia "não logar `resp.text`", quando o vazamento real está na URL, num caminho de sucesso, e inclui o secret do app. **Lição:** biblioteca de terceiro loga por conta própria — colocar segredo em query string é colocá-lo no log de alguém. Segredo vai em header ou corpo, e todo cliente HTTP de terceiro deve ter o nível de log fixado explicitamente. Family: secret-leak-via-transitive-logging (nova).
  **✅ VAZAMENTO FECHADO (2026-08-14); causa raiz parcialmente remanescente — ver abaixo.** (1) `configure_logging` ([`src/logging.py`](../../src/logging.py)) agora faz `setLevel(logging.WARNING)` nos loggers `httpx` **e** `httpcore`. O nível é absoluto (não herda do root), então vale inclusive com `LOG_LEVEL=debug`, que é opção real em `config.py`; WARNING/ERROR do httpx seguem passando. Isso encerra o vazamento observado **em todos os call-sites de uma vez**, inclusive nos que ainda carregam segredo na URL. (2) A troca short→long-lived virou `_exchange_for_long_lived_token`, um **POST com `data=`** — o `client_secret` e o token do gestor saíram da query string. O método não é aposta: a troca code→short chama o **mesmo endpoint** por POST e roda em produção. **Testes:** `tests/unit/test_meta_secret_leak.py`, incluindo um teste que **prova a premissa** (força INFO no logger `httpx` e verifica que o segredo aparece mesmo no log record) — sem ele o teste do `setLevel` seria ritual. O primeiro teste do `setLevel` passou vacuamente na 1ª tentativa porque `getEffectiveLevel()` herda do root e o `basicConfig` é no-op sob pytest; corrigido pra assertar o nível **próprio** do logger. Os mocks de `tests/integration/test_meta_oauth_flow.py` migraram de `respx.get`+`respx.post` pra uma rota POST única com `side_effect` ordenado (a semântica de ordenação foi verificada localmente, já que integração exige Docker e só roda no CI).
  **⚠️ Aberto — 3 call-sites ainda com segredo na query string:** `_fetch_all_adaccounts` (token system-user), `/me` (token pessoal) e `/debug_token` (app access token `app_id|app_secret` + `input_token`). Tirar esses exige trocar o **mecanismo de auth** pro header, e isso **não foi shipado de propósito**: (a) o formato é quirk do Meta — a doc oficial recuperada via context7 mostra `Authorization: OAuth <token>`, não `Bearer`, e o snippet era de outra família de endpoint; (b) `_fetch_all_adaccounts` roda no **job diário de resync em produção**; (c) com o F93 ainda aberto na ocasião, uma falha desse job era auditada como `success` — a quebra seria *mascarada*. É exatamente o modo de falha F53/F54/F55 ("não shippar mudança de superfície da API Meta sem validação empírica"), então o passo correto é uma **probe empírica** contra o Graph antes da migração. Enquanto isso, a camada (1) impede o vazamento.
  **Destravado em 2026-08-14:** o **F93 foi fechado** na mesma sessão, então a condição (c) caiu — uma quebra do resync agora grava `status="error"` no audit em vez de passar por sucesso. Restam (a) e (b): a migração segue precisando da probe empírica do formato do header contra o Graph, mas agora falha de forma visível se der errado.
  **A condição (a) CAIU em 2026-08-15 — probe feita, e sem gastar segredo nenhum.** Bastou mandar um token *falso* pro Graph e comparar os erros: `Authorization: Bearer <lixo>` → code **190** *"Cannot parse access token"*; `Authorization: OAuth <lixo>` → **190** idêntico; **sem header** → code **2500** *"An active access token must be used"*. O erro **diferente** sem header prova que nos dois formatos o token foi lido do header e entregue ao parser — ou seja, `Bearer` é aceito, e a dúvida do doc (`OAuth` vs `Bearer`) morreu. **Não foi feita** a confirmação de que um token *válido* autentica igual: exige o token real, e o `gcloud` está com credencial expirada (`gcloud auth login` é interativo). O probe que fecha isso está escrito e imprime **só** status/contagem, nunca o segredo: `scratchpad/probe_meta_header.py`.
  **✅ CAUSA RAIZ FECHADA (2026-08-15), depois da probe com token válido.** O gestor rodou `gcloud auth login` e o probe ([`scripts/probe_meta_auth_header.py`](../../scripts/probe_meta_auth_header.py)) decidiu tudo:

| Item | Resultado | Consequência |
|---|---|---|
| **(B)** `Bearer` vs `?access_token=` | dados **idênticos** | migração liberada |
| **(D)** `next` traz `access_token`? | **não**, quando se autentica por header | ver abaixo — inverteu o desenho |
| **(E)** `next` sem token + header | HTTP 200 | paginação funciona por header |
| **(F)** app token no header | HTTP 200 | `app_id\|app_secret` sai da URL |
| **(G)** `/debug_token` via POST | **HTTP 400**, code 100 sub 33 | `input_token` **fica** na query |

  **O item (D) inverteu o desenho e é a razão de a probe ter valido a pena.** Eu ia *reescrever* a URL do `paging.next` pra arrancar o `access_token` — mas autenticando por header o Graph simplesmente **não embute mais o token no `next`**. O que era "remover o token da URL de paginação" virou o requisito oposto: **reenviar o header em cada página**, senão a 2ª volta 401. Um teste cobre exatamente isso.
  **O `input_token` do `/debug_token` fica na query, e é o resíduo conhecido** — não é credencial do chamador (é o objeto inspecionado, não cabe em `Authorization`) e o endpoint rejeita POST. O que saiu do mesmo request foi o `app_id|app_secret`, o segredo **permanente**; o `input_token` é token de gestor, que expira. Sobra risco, de outra ordem de grandeza.
  **Guard:** `tests/unit/test_no_secrets_in_query_params.py` (AST) impede segredo novo em `params=`. A allowlist é por **(função, chave)**, não por função — reintroduzir `access_token` numa função já listada passaria batido —, e um 2º teste falha se ela ficar obsoleta. **Quase nasceu furado:** a 1ª versão só via dict literal inline e dava verde justamente em `_fetch_all_adaccounts`, que monta o dict numa **variável** por causa da paginação; passou a rastrear a atribuição. Sabotado com um call-site novo, aponta arquivo, linha, função e chave.

- **F83 (HIGH) — mutação aplicada com sucesso pode ser reportada como erro e sumir do audit:** em [`mutations.py:270-306`](../../src/google_ads/mutations.py) o `finally` faz `pool.acquire()` **cru** duas vezes (reconciliação de quota + `audit_log.record`), e roda **depois** de `ga_service.mutate()` já ter aplicado a mudança no Google, com um `return` pendente. Se a conexão estiver stale — o modo de falha do **F76**, com 6 ocorrências reais em produção — a exceção nasce no `finally` e, por semântica do Python, **descarta o `return` pendente** e se propaga. Três consequências simultâneas: (1) o gestor vê erro numa mutação que **foi aplicada**; (2) o cliente LLM tende a re-tentar, e `add_keywords`/`create_campaign`/`update_campaign_budget` **não são idempotentes** → risco de aplicação dupla; (3) a linha de audit **nunca é gravada**, quebrando o invariante "audit SEMPRE em mutates" exatamente no caso em que ele mais importa (mudança aplicada sem rastro). Se a falha for no `record_actual`, a reserva de quota ainda fica órfã. Mesmo shape em [`conversions.py:142`](../../src/google_ads/conversions.py), [`customer_match.py:220`](../../src/google_ads/customer_match.py), [`mutations.py:392`](../../src/google_ads/mutations.py) (`run_recommendation_action`), [`reports.py:113`](../../src/google_ads/reports.py) e [`validate_gaql.py:169`](../../src/mcp/tools/validate_gaql.py) — **6 sites**. **Lição:** bookkeeping em `finally` tem poder de veto sobre o resultado do `try` — todo `finally` que faz I/O precisa do próprio `except`, senão a observabilidade derruba a operação que deveria apenas observar. Family: F76 aplicada ao lado write + governança-ausente (irmã de F71/F73).
  **✅ CORRIGIDO (2026-08-14, mesma sessão).** Helper `best_effort` em [`src/governance/bookkeeping.py`](../../src/governance/bookkeeping.py) — async context manager que engole a exceção do bookkeeping e a converte em `log.exception` (alertável, porque `add_cloud_logging_severity` mapeia `level`→`severity`). Aplicado nos 6 sites, com os blocos de quota e audit tornados **independentes**: antes eram sequenciais no mesmo `finally`, então a falha da reconciliação de quota pulava o audit inteiro. Em `reports.py` o `if audit_this_call` subiu pra ANTES do `pool.acquire()` — sem opt-in de audit não havia por que pegar conexão, e era um ponto de falha gratuito dentro do `finally`. **Deliberadamente SEM retry:** re-executar um INSERT que pode ter commitado duplicaria a linha de audit (CLAUDE.md, "mutação NÃO leva retry cego") — o ganho é trocar "erro opaco + audit perdido em silêncio" por "resultado correto + falha registrada", não garantir a escrita. **Guard:** `test_finally_bookkeeping_is_best_effort` em `tests/unit/test_structural_guards.py` é **AST-based e por BLOCO** (não grep por arquivo, como os guards F57/F58): cada statement de um `finally` que chama `.acquire()` tem que chamar `best_effort` no mesmo statement. Isso importa porque `mutations.py` tem dois executores — quando só `run_mutation` estava corrigido, o guard continuou acusando `mutations.py:413` (`run_recommendation_action`), o que um guard file-level não pegaria. **Testes:** 4 comportamentais em `tests/unit/test_executor_bookkeeping_never_masks.py`, todos verificados falhando contra o código pré-fix (via `git stash` do executor) — incluindo o caso em que a conexão morre **no próprio `acquire()`**, e não no corpo, que é o modo de falha real do F76 e o que exercita a forma `async with best_effort(...), pool.acquire()` que o ruff colapsou.

- **F84 (MED) — `managers.status` e `managers.is_active` divergem, e os gates de sessão só leem `is_active`:** os dois campos podem divergir e nada os sincroniza — o toggle do painel faz `UPDATE managers SET is_active = NOT is_active` ([`routes.py:861`](../../src/web/routes.py)) e **nunca toca em `status`**; nenhum código escreve `status='inactive'`. O gate de **login** nega nas duas condições (`status == "active" and is_active`, com fallthrough explícito pra `status == "inactive" OR is_active=False` → `/access-denied`, [`oauth.py:76-83`](../../src/auth/oauth.py)), mas os gates de **sessão viva** olham só `is_active`: [`session.py:54`](../../src/mcp/session.py) (MCP) e [`deps.py:59,74`](../../src/web/deps.py) (painel). **Cenário concreto:** offboarding feito via SQL direto marcando `status='inactive'` — o único caminho existente, já que a UI não escreve essa coluna — bloqueia o login mas deixa **todo Bearer MCP do gestor funcionando até expirar** (TTL padrão 90 dias). A coluna que a UI de admin exibe não é a que o gate do MCP lê. Family: hard-gate-bypass (irmã de F60, que fechou o `is_active` e não viu o `status`).
  **✅ CORRIGIDO (2026-08-15).** Predicado único `Manager.is_deactivated` (`not is_active or status == "inactive"`) no dataclass, usado pelos 3 gates — `session.py` (MCP) e `deps.py` (painel, 2 sites). O bug foi **três sites decidindo isso por conta própria**, então a correção é ter um lugar só onde a regra mora. `invited` NÃO conta como desativado: é estado de onboarding e o login promove invited→active; bloqueá-lo quebraria o fluxo.
  **Um 4º site apareceu durante o fix, no gate de LOGIN:** o branch `status == "invited"` vinha ANTES da checagem de desativação e lia só `status`. Como `create_invited` grava `is_active=true` mas o toggle do painel funciona em qualquer gestor — inclusive num convite pendente —, um convite desativado era **promovido a 'active' no login** e só então batia em porta fechada no primeiro page-load. Reordenado: desativação primeiro, e status desconhecido passou a negar por padrão (fail-closed).
  **Decisão deliberada — NÃO sincronizar as colunas no toggle:** parecia a correção óbvia ("escreve as duas"), mas re-ativar um gestor gravaria `status='active'` e **destruiria o estado `invited`** de quem nunca logou, atropelando o `mark_active`. Tornar os gates autoritativos fecha o buraco sem tocar no modelo de dados.
  **Fidelidade de mock (3ª ocorrência da família nesta sessão):** dois testes usavam um `_FakeManager` com um campo só (`is_active`) — um fake que **não conseguia sequer expressar a divergência** que causou o bug. Substituídos pelo dataclass `Manager` real via helper `make_manager()`. É a mesma lição de F16/F48/F89: mock que simplifica demais apaga a categoria de bug que ele deveria pegar.

### Correção de dados entregues ao gestor

- **F85 (MED) — resposta vazia da API do Google desativa TODAS as 25 contas do MCC:** `fetch_account_details` pode retornar `[]` **sem levantar exceção** (search com 0 linhas, mudança de semântica do `customer_client`, hiccup de permissão); `keep_ids` sai vazio ([`account_resync.py:107`](../../src/jobs/account_resync.py)) e `mark_inactive_except` cai num branch deliberado que marca o inventário inteiro como inativo ([`google_ads_accounts.py:82-87`](../../src/db/repositories/google_ads_accounts.py)). As contas somem do painel, de `list_my_accounts` e de `grant_all_active` até o resync seguinte — 24h depois. **O lado Meta escolheu o oposto e documentou (F65):** payload vazio não desativa nada. A assimetria fail-deactivate vs fail-safe não parece intencional. Family: deletion-detection sem guarda de sanidade (espelho invertido de F65).
  **✅ CORRIGIDO (2026-08-15).** Duas camadas, porque o perigo existia nos dois níveis. **(1) Repositório:** `mark_inactive_except` virou **no-op com keep-list vazia** — lista vazia quase sempre significa falha de leitura, não "o MCC ficou vazio". A desativação em massa continua possível, mas só por opt-in explícito (`allow_full_deactivation=True`), que obriga o caller a assumir a intenção. **(2) Job:** `account_resync` detecta o inventário vazio, loga ERROR, **pula a detecção de churn** e grava `status="error"` no audit — espelhando o que a F93 acabara de fazer no lado Meta. O `params_summary` ganhou `inventory_ok`, que distingue "0 desativadas porque nada sumiu" de "0 desativadas porque o inventário veio vazio e pulamos a detecção". **Testes:** 4 unit (no-op por default, opt-in preservado, caminho feliz intacto, job auditando erro) + 1 de integração contra banco real — o unit prova que o UPDATE não é emitido, o de integração prova o efeito (as contas seguem ativas), que é o que de fato importava. **Assimetria resolvida:** Google e Meta agora falham do mesmo jeito diante de inventário suspeito. **Follow-up possível, não feito:** guarda por queda percentual (25→1 também é suspeito) — é decisão de produto sobre o limiar, não correção de bug.

- **F86 (MED) — SDK do Google é síncrono e roda direto no event loop, inclusive travando o `/health`:** `ga_service.search_stream()` ([`reports.py:101`](../../src/google_ads/reports.py)), `.mutate()` ([`mutations.py:223`](../../src/google_ads/mutations.py)), `.search()` ([`accounts.py:51`](../../src/google_ads/accounts.py)) e `.upload_click_conversions()` ([`conversions.py:125`](../../src/google_ads/conversions.py)) são chamadas gRPC **bloqueantes** dentro de `async def`. Grep confirma **zero** `to_thread`/`run_in_executor` no projeto (`anyio` só aparece em `server.py` pra task groups). Com `--concurrency=80`, uma chamada Google lenta congela o event loop da instância inteira — e o `asyncio.timeout(5)` do deep health (F77) **nem começa a contar**, porque o loop não cede. É um caminho pra 503 no uptime check **sem nenhum problema de DB**, que a investigação do F77 não teria como distinguir. **Lição:** um probe de disponibilidade só mede o que o event loop consegue atender; deadline interno não protege contra bloqueio do próprio loop. Family: async-hygiene (nova).
  **✅ CORRIGIDO (2026-08-15).** Helper `run_blocking` em `_blocking.py` (`anyio.to_thread.run_sync`) aplicado aos 4 executores que atendem request: `reports.py`, `mutations.py`, `conversions.py` e `customer_match.py` (3 chamadas sequenciais num salto só — são dependentes entre si). **`accounts.py` ficou síncrono de propósito:** é consumido apenas pelo Cloud Run Job de resync, que não serve tráfego, então bloquear ali não tira nada de ninguém.
  **⚠️ ESTE FIX ESTAVA INCOMPLETO — ver [F109](#investigação-de-backend-2026-08-19-f109-f112).** "Os 4 executores que atendem request" era a lista errada: são **6** os caminhos que atendem request (os 5 executores mais `validate_gaql`, que constrói o client direto), e o lado Meta bloqueia por conta própria. Três ficaram para trás por cinco dias, e não havia guard pra notar. O helper mudou de casa nesse fix: hoje é [`src/blocking.py`](../../src/blocking.py).
  **Streaming exigia mais que offloadar a chamada:** `search_stream` devolve um iterador cuja I/O acontece no `for`. Tirar só a chamada do loop mudaria o bloqueio de lugar — o `for batch in stream` inteiro precisa rodar dentro da função offloaded.
  **⚠️ Armadilha que a própria correção criava — `provider_request_id` sumindo do audit:** o interceptor grava o request-id num **ContextVar** durante a chamada gRPC, e `anyio.to_thread` **copia** o contexto pra worker thread sem propagar mutações de volta. Um `get_request_id()` do lado do loop passaria a ler `None` e o campo sumiria de todo audit — em silêncio, porque é opcional. Por isso o id é lido DENTRO da função offloaded e devolvido junto com a resposta (nos 3 executores que o usam; `run_report` não expõe request-id). Coberto por teste que exercita o ContextVar de verdade, e não o mock de `get_request_id` que os outros testes usam — sem isso, nada pegaria.
  **Método do teste:** a forma óbvia (medir tempo, assertar que nenhuma pausa passou de X ms) é instável em CI ruidoso. A prova aqui é **determinística**: o SDK falso bloqueia num `threading.Event` que só o lado async consegue liberar. Se a chamada rodar no event loop, a corrotina que libera nunca executa e o `wait` estoura; se rodar numa thread, o loop segue girando e libera. O booleano que o SDK falso registra é a resposta. No RED, `loop_seguiu_girando = False` nos dois caminhos (read e mutate).

- **F87 (MED) — escape GAQL usa doubling de SQL (`''`) onde a linguagem quer backslash, e não escapa `\`:** [`_common.py:555`](../../src/google_ads/queries/_common.py) faz `n.replace("'", "''")` com um comentário que explicita o modelo mental errado — *"doubled-quote pattern, same as SQL"* — e o gêmeo `_quote_literal` em [`change_history.py:47-49`](../../src/google_ads/queries/change_history.py) repete. **Dois efeitos:** (1) nome legítimo como `Lead - D'Or` vira `IN ('Lead - D''Or')`, que o parser lê como duas strings adjacentes → **erro de sintaxe**, e o pré-flight de nome duplicado do `create_conversion_action` falha com erro opaco do Google pra um nome perfeitamente válido — este é o dano real e frequente; (2) `\` não é escapado, então nome terminado em barra invertida produz `'Promo \'`, o `\'` escapa a aspa de fechamento e a string engole o resto da query, permitindo balancear aspas e injetar cláusula no WHERE. **Impacto de injeção é baixo e deve ser descrito honestamente:** a query é read-only, o `customer_id` é campo separado da request (hard-gate intacto) e as colunas expostas já são visíveis por outras tools — o ganho máximo é furar/travar o próprio pré-flight. **Superfície mapeada:** dos 35 pontos de interpolação GAQL do código, só este e o `user_emails` do `get_change_history` (F88-adjacente: `format: "email"` **não é enforced** porque `jsonschema.validate` roda sem `format_checker` em [`server.py:121`](../../src/mcp/server.py)) recebem texto livre; todo o resto é protegido por `pattern`/`enum` de schema ou `int()`. Notavelmente, keyword text e `competitor_brands` **nunca chegam a GAQL** (vão pra proto de mutate e matching client-side). Item deferido em 07-04 ("GAQL escaping `''`→`\'`"), agora com causa e superfície precisas.
  **✅ CORRIGIDO (2026-08-15), com prova empírica contra a API real.** Antes de escrever código, as hipóteses foram testadas via `validate_gaql` na conta sandbox — a probe que as lições F53/F54/F55 e A7 exigem:

  | GAQL | valid |
  |---|---|
  | `... IN ('O\'Brien')` — barra invertida | **true** |
  | `... IN ('O''Brien')` — doubling de SQL (o código antigo) | **false**: `invalid value 'Brien'` |
  | `... IN ('Promo \')` — barra crua no fim | **false**: o erro mostra o parser consumindo `'Promo \')`, isto é, a string engoliu a aspa de fechamento e o `)` |
  | `... IN ('Promo \\')` — barra escapada | **true** |

  Módulo novo [`_gaql.py`](../../src/google_ads/queries/_gaql.py), sem dependências (pra ser importável de qualquer builder sem arrastar o executor via `_common`): `gaql_escape`, `gaql_string_literal`, `gaql_in_list`. **A ordem é load-bearing:** a barra invertida é escapada ANTES da aspa, senão as barras recém-inseridas pelo escape da aspa seriam re-escapadas. Aplicado nos 3 sites. **Validação final:** a query montada pelo helper com os três casos juntos (`Lead - D'Or`, `Promo \`, `a\' OR 1=1 OR '`) retorna `valid: true` na API real, com o payload de injeção neutralizado em literal comum.
  **Descoberta incômoda — o bug tinha cobertura de teste que o FIXAVA.** `test_user_emails_filter_escapes_single_quote` e `test_validate_geo_targets_single_quote_escape` asseriam o doubling como correto, com comentários afirmando *"must be doubled per GAQL string literal rules"* e *"Doubled-quote escape pattern"*. Não era ausência de teste: era teste errado, dando confiança invertida — e é por isso que o bug sobreviveu a várias sprints. Ambos tiveram o contrato revertido, com nota explicando a inversão. **Lição:** teste que codifica a convenção errada é pior que teste ausente, porque desliga a suspeita. Quando a asserção é sobre a superfície de uma API externa, ela precisa nascer de probe empírica e não de analogia — aqui, "GAQL parece SQL".
  **Guard:** `test_gaql_nao_usa_doubling_de_aspas`, **AST e não grep**. A 1ª versão era grep de linha, e o único infrator que encontrou foi a **própria docstring do `_gaql.py`**, que cita o padrão antigo pra explicar por que é errado — 4ª ocorrência da armadilha registrada na nota de método de 2026-08-11 (a prosa que descreve a regra dispara o guard que a aplica). Casando a *chamada* no AST, comentário e docstring ficam invisíveis por construção. Verificado que dispara no código pré-fix.

- **F88 (MED) — tools Meta truncam na primeira página e ordenam DEPOIS de truncar, com `total_rows` se apresentando como total:** `run_meta_graph_get` devolve só o `body` da 1ª página e ignora `paging.next` ([`reports.py:112`](../../src/meta_ads/reports.py)); em [`_meta_performance.py:118-128`](../../src/mcp/tools/_meta_performance.py) o `sort` por `spend_brl` roda sobre esse subconjunto arbitrário e `total_rows: len(rows)` reporta o parcial. A description promete *"Ordenado por spend desc"* — numa conta com mais entidades que o `limit` (default 100; `meta_get_ad_performance` estoura fácil), **o "top gastadores" não é o top**. Nenhuma das 6 tools Meta emite `truncated`, enquanto as 4 de audit Google e o `run_gaql` emitem. **Contraste:** o lado Google ordena e corta **server-side** (`ORDER BY metrics.cost_micros DESC LIMIT n`), que é o comportamento correto. Family: silent-truncation (irmã de F61, agora no lado de leitura) + ordenação sobre amostra enviesada.
  **✅ CORRIGIDO (2026-08-15).** Fiz as duas coisas que o registro oferecia como alternativas, porque cada uma sozinha deixa metade do problema: **(1) paginação** — `run_meta_graph_get` ganhou `max_pages` (default 1, preservando os callers que leem um objeto só) e segue `paging.next` concatenando `data`; o `paging` da ÚLTIMA página sobrevive no retorno, então um `next` remanescente é o sinal de truncamento. As 4 tools de performance passam `_MAX_PAGES=5`. **(2) honestidade** — o sort roda sobre tudo que foi lido, o corte pro `limit` acontece DEPOIS, e o envelope ganhou `truncated` + `truncated_hint`. Nenhuma tool Meta sinalizava truncamento; as 4 de audit Google e o `run_gaql` já sinalizavam.
  **BUC:** o contador passou a registrar as chamadas REALMENTE feitas (`max(estimated_calls, páginas_lidas)`), não a estimativa fixa de 1 — senão a paginação consumiria quota invisível, que é o mesmo tipo de cegueira do F93.
  **Descriptions:** as 4 prometiam "Ordenado por spend desc" sem ressalva. Passaram a dizer que a ordenação é entre o que foi lido e a apontar o `truncated`. Detalhe de processo: a substituição foi mecânica e gerou erro de concordância ("entre as anúncios lidas") — corrigido, porque description é texto que o LLM consumidor lê e do qual tira conclusão.
  **Teste de parity ajustado:** `test_run_meta_level_performance_success_shape_parity` fixa o shape do envelope desde a dedup M.3. `truncated` é adição deliberada e aditiva (nenhum campo saiu); o teste foi atualizado com a justificativa em vez de afrouxado.
  **✅ FECHADO POR COMPLETO (2026-08-15, 2ª parte).** O "limite conhecido" acima **deixou de existir**: `build_insights_call` passa `sort=spend_descending`, o servidor ordena ANTES de cortar e a 1ª página JÁ é o topo — mesma forma do lado Google (`ORDER BY metrics.cost_micros DESC LIMIT n`). A probe ([`scripts/probe_meta_sort.py`](../../scripts/probe_meta_sort.py)) decidiu, e **o teste que sustenta os outros foi o do valor INVÁLIDO**: `banana_ascending` devolve **HTTP 400** `The parameter value of "sort" is invalid`, provando que a API LÊ o param — sem isso um 200 não significaria nada, que é exatamente como F53/F54/F55 nasceram. O controle fechou o argumento: `limit=3` **sem** sort devolve 3 campanhas sem relação com o topo.
  **O `truncated_hint` virou MENTIRA com o fix, e corrigi-lo era parte do trabalho.** Ele dizia "o ranking pode não incluir o maior gastador" — verdade com sort no cliente, falso quando o maior gastador vem garantido. Manter aquele texto seria **pior que não avisar**: mandaria o gestor desconfiar de um dado correto. Agora `truncated` significa "ficou a cauda de MENOR gasto de fora", que é completude, não risco de correção. As 4 descriptions mudaram pelo mesmo motivo — são o contrato que o cliente LLM lê antes de interpretar o resultado.
  **`build_insights_call` é compartilhado com `meta_get_performance_breakdown`**, então a combinação `sort` + `breakdowns` foi sondada à parte antes de aplicar lá (`publisher_platform`, `impression_device`, `country` e `hourly` com 48 linhas — todos aceitam e voltam ordenados). Aplicar por analogia com a query sem breakdown seria a própria classe F53/F54/F55.
  O sort no cliente **ficou** como rede idempotente sobre dado já ordenado: o corte `[:limit]` depende da ordem, e o custo é nulo.

- **F89 (MED) — `parse_insights_row` ainda lê 4 campos removidos nos F53/F54, e `effective_status` sai constante em 5 tools:** as listas `INSIGHTS_FIELDS_*` foram corrigidas (só metrics + ids/names + `objective` + `optimization_goal`), mas o parser continua pedindo `effective_status`, `billing_event`, `daily_budget` (adset) e `creative_id` (ad) ([`insights.py:159-164,186-196`](../../src/meta_ads/insights.py)) — campos que a query **nunca solicita** (confirmado por grep nas listas) → `"UNKNOWN"`/`"DESCONHECIDO"`/`null` em **100% das linhas**. **Agravante:** a description de `meta_get_campaign_performance` diz ao gestor que ele "pode filtrar client-side via prompt natural" por status — impossível, o campo é literal fixo. Pra um consumidor LLM isso é **pior que a ausência do campo**: ele reporta "status desconhecido" com confiança, ou preenche a lacuna. **Lição:** campo que o parser lê mas a query não pede não é "defensivo" — é um valor inventado com cara de dado. Family: F53/F54 residual (o fix parou na query e não desceu ao parser/description).
  **✅ CORRIGIDO (2026-08-15).** Os 4 campos saíram do parser e do envelope; as 3 descriptions foram reescritas. **Correção de contagem:** são **4 tools** afetadas, não 5 como este registro dizia — `meta_get_campaign_performance`, `meta_get_ad_set_performance` e `meta_get_ad_performance` (as três via `_meta_performance.py`) mais `meta_get_performance_breakdown`. **As descriptions eram pior que imprecisas: prometiam os campos.** A de ad_set anunciava "billing_event + daily_budget_brl (CBO=None)" e a de ad, "creative_id" — campos que a tool nunca entregou, sempre `None`. A de campaign instruía a "filtrar client-side via prompt natural" por um status constante. As três passaram a dizer o que de fato acontece: metadata de entidade não vem, o status não é conhecido aqui, e a consulta é no Gerenciador. **Órfãos removidos:** o import de `META_EFFECTIVE_STATUS_LABELS` em `insights.py` (ruff pegou) e o re-export morto em `_meta_common.py`, cujo único consumidor era esse parser; o mapa segue em `labels.py` pro enriquecimento futuro.
  **Guard:** `test_parser_nao_le_campo_que_a_query_nao_pede` — lê o AST de `parse_insights_row` e cruza cada `row.get("<literal>")` com a união das `INSIGHTS_FIELDS_*`. É o guard que faltava pra fechar F53/F54: aqueles fixes corrigiram a QUERY e ninguém verificou o parser. Chaves de breakdown são dinâmicas (`row.get(key)`), então caem fora naturalmente. No RED ele apontou sozinho os 4 fantasmas.
  **Descoberta (2ª ocorrência do padrão do F87 nesta sessão): 5 testes fixavam o comportamento fantasma** — 3 unit (`..._unknown_effective_status`, `..._adset_no_daily_budget`, `..._ad_missing_optional`) e 2 de integração (`test_ad_missing_creative_id_returns_none`, `test_cbo_adset_no_daily_budget_returns_none`). Vários testavam cenários **impossíveis**: `..._unknown_effective_status` verificava o label de um status que nunca chega, e o par `with_daily_budget`/`no_daily_budget` fingia cobrir a distinção CBO quando ambos os casos davam `None`. **E os mocks eram infiéis:** os bodies de resposta nos testes de integração incluíam `effective_status`/`creative_id`/`daily_budget`, descrevendo uma resposta que a Meta nunca devolve — provavelmente a razão de o campo morto sobreviver a tantas sprints. Mocks limpos e testes reescritos pra assertar ausência. **Lição (irmã da do F16/F48):** mock que inclui campo que a API real não devolve é pior que mock incompleto — ele valida um contrato imaginário e some com a evidência do bug.

- **F90 (MED) — `audit_competitor_keywords` não expõe o status do ad_group pai:** a query nunca seleciona `ad_group.status` ([`audit_competitor_keywords.py:9-26`](../../src/google_ads/queries/audit_competitor_keywords.py) filtra só `ad_group_criterion.status='ENABLED'`), e o `status` devolvido ao gestor é a **constante hardcoded** `"ENABLED"` ([`competitor_analysis.py:48,134`](../../src/google_ads/competitor_analysis.py)). É a classe **F52**: keyword ENABLED dentro de ad_group REMOVED não compete em leilão, então o "gasto em concorrência" e os `suggested_negatives` incluem itens inertes — a mesma inflação de narrativa que o F52 mediu em 60,7% num caso real. Os dois irmãos de família (`audit_zombie_keywords`, `audit_quality_score`) já citam a lição explicitamente; **este ficou de fora do retrofit**. Family: F52 (site não retrofitado).
  **✅ CORRIGIDO (2026-08-15).** `ad_group.status` entrou no SELECT e atravessa o caminho inteiro — parser (via `.name` do enum, não `str(enum)`: lição UX-2 do proto-plus), `KeywordRow`, `MatchedKeyword` e o output do tool, como `ad_group_status`. O campo `status` (da keyword) continua: é tautologicamente correto, já que a query filtra por `ENABLED` — diferente dos fantasmas do F89, que eram lidos e nunca vinham. A description foi extraída do decorator pra constante `_DESCRIPTION` (padrão dos irmãos) e ganhou o mesmo aviso que `audit_zombie_keywords` e `audit_quality_score` têm desde a 3b.38: filtre `ad_group_status='ENABLED'` antes de agir ou de reportar gasto pro cliente.
  **Por que importa mais aqui que nos irmãos:** esta tool alimenta `suggested_negatives` e um total de "gasto em concorrência" que vira número em relatório. Item inerte não só infla a narrativa (60,7% no caso real que a F52 mediu) como sugere negativar keyword que não gasta.

### Infra, jobs e resiliência

- **F91 (MED) — reincidência da classe F76: `pool.acquire()` cru em reads quentes e idempotentes:** fora dos dois sites já corrigidos, sobraram (a) [`deps.py:56,71,84`](../../src/web/deps.py) — `current_manager`/`optional_current_manager`/`pending_invites_count` rodam a **cada page-load** do painel, que é de baixo tráfego, ou seja, o cenário exato do F76 (conexão ociosa) → o primeiro acesso da manhã vira 500; (b) o acquire do `ensure_account_access` a **cada request MCP** ([`reports.py:61`](../../src/google_ads/reports.py), [`mutations.py:169`](../../src/google_ads/mutations.py), [`conversions.py:59`](../../src/google_ads/conversions.py), [`customer_match.py:118`](../../src/google_ads/customer_match.py), [`validate_gaql.py:94`](../../src/mcp/tools/validate_gaql.py), [`meta_ads/reports.py:69`](../../src/meta_ads/reports.py)) e o read de OAuth em [`client.py:59`](../../src/google_ads/client.py). Todos são reads pré-operação, seguros de re-executar — exatamente o contrato de `run_with_reconnect`, e o "Don't" já declarado no CLAUDE.md. Fix: envolver esses reads (mantendo mutação sem retry).
  **✅ CORRIGIDO (2026-08-15).** Os 9 call-sites envolvidos: 3 em `deps.py`, os 5 gates Google (`reports`, `mutations` ×2, `conversions`, `customer_match`, `validate_gaql`), o read de OAuth em `client.py` e o gate Meta. Os `acquire()` que **sobraram** nesses arquivos são reserva de quota e audit — escritas, que continuam sem retry de propósito.
  **⚠️ O fix introduzia um bug próprio, e foi isso que deu mais trabalho.** O gate não é read puro: no caminho de negação ele **escreve** um audit. Envolver a função inteira em retry significava que uma falha de conexão no INSERT faria o retry gravar a negação **duas vezes** — "mutação NÃO leva retry cego". Resolvido de forma diferente nos dois lados, pelo custo: no **Meta** o read e a escrita já eram instruções separadas, então foram **separados de fato** (só o `can_manager_access` é retentado); no **Google** eles vivem dentro de `ensure_account_access(conn, …)`, e mudar a assinatura custaria ~40 arquivos de teste, então a escrita foi envolvida em **`best_effort`** (F83) — a exceção de conexão não escapa, logo o retry não a alcança. Perder o registro é pior que tê-lo, mas hoje a mesma falha virava 500 **sem audit e sem negação clara**; agora o gestor recebe a negação correta e a falha fica logada como ERROR alertável.
  **Verificação:** os 8 testes ficaram RED pelo motivo certo (`ConnectionDoesNotExistError` escapando). Os 2 que cobrem o não-retry da escrita foram provados por **sabotagem** — removido o `best_effort` dos dois gates, o erro de conexão volta a escapar. Técnica: 1ª chamada levanta o erro de produção, 2ª devolve o resultado; no gate, a 2ª levanta `AccountAccessDeniedError`, o que prova o retry sem precisar mockar o executor inteiro.
  **Efeito colateral em teste:** 3 testes de `run_recommendation_action` trocam o **módulo** `connection` inteiro por MagicMock, e `run_with_reconnect` passou a voltar um MagicMock não-awaitable. Anular a chamada esconderia o gate (eles assertam `ensure_access_mock`), então ganharam um stub que **executa** a operação, como o real faz no caminho feliz.

- **F92 (MED) — dimensionamento do pool e `acquire` aninhado sem timeout:** `max_size=10` é default hardcoded de `init_pool` ([`connection.py:26`](../../src/db/connection.py), sem knob em Settings) contra `--max-instances=10` + `--concurrency=80` ([`deploy.yml:133`](../../.github/workflows/deploy.yml)) → até **100 conexões**, mais o overlap de revisões durante o deploy e os pools próprios dos Cloud Run Jobs; tiers pequenos do Supabase têm `max_connections=60`. Nenhum `pool.acquire()` do projeto usa `timeout=`, e **4 rotas admin chamam `pending_invites_count()` DENTRO de um `acquire` já aberto** ([`routes.py:1154,1191,1277,1314`](../../src/web/routes.py)) enquanto as outras 7 chamam fora — a inconsistência mostra que não é intencional. Com o pool esgotado, quem segura a 1ª conexão e espera a 2ª espera **para sempre** (asyncpg não tem timeout default). Improvável com 1 admin; é hazard estrutural gratuito. Family: deadlock latente + orçamento de conexões não coordenado.
  **✅ CORRIGIDO (2026-08-15).** **(1) Aninhamento:** as 4 chamadas saíram do `async with` — nenhuma usava `conn`, eram a última instrução do bloco. **(2) Dimensionamento:** default caiu de 10 pra **5** (constantes `DEFAULT_POOL_*` em `connection.py`) — 10 instâncias × 5 = 50, com ~10 de folga pros Cloud Run Jobs dentro das 60 do tier pequeno. `db_pool_min_size`/`db_pool_max_size` em Settings alimentam o caminho que **serve tráfego** (`app.py` passa explícito), que é onde a conta de instâncias importa; job e script ficam no default conservador.
  **⚠️ A 1ª tentativa derrubou a suíte INTEIRA de integração no CI.** Eu tinha posto `get_settings()` dentro de `init_pool` pra ler o default — e pior, carregava o Settings ANTES de checar se os tamanhos vieram por argumento, então quebrava até pra conftest que passava os dois. No ambiente de integração o Settings não tem as 13 variáveis obrigatórias: `ValidationError: 11 validation errors`. **Lição:** primitivo de infraestrutura (pool, cliente HTTP, logger) não pode depender da config completa da app — quem serve tráfego injeta o valor, o primitivo carrega um default sensato. Um teste agora falha se `get_settings` voltar a ser chamado ali, e outro garante que a constante e o default de Settings não divergem.
  **Guard:** `test_nao_chama_helper_que_pega_conexao_dentro_de_acquire` é AST e **descobre sozinho** quais funções abrem conexão própria (as que casam `get_pool` **e** `acquire` no corpo) antes de procurar chamadas a elas dentro de um `async with ...acquire()`. Não é allowlist de nomes: helper auto-adquirente novo entra no radar automaticamente. Na 1ª versão eu exigia que o `.acquire` pendesse de `get_pool()` no AST e o guard passou vazio — o idioma do codebase é `pool = get_pool()` e depois `pool.acquire()`, com os dois nós separados. Corrigido, o RED apontou os 4 sites com linha e nome do helper.
  **Teste-conta:** `test_default_cabe_no_orcamento_de_conexoes_do_supabase` escreve a aritmética (instâncias × pool + folga ≤ teto) como asserção. Se alguém subir o pool sem subir o tier, quebra no CI e não em produção.
  **NÃO fiz o timeout global de `acquire`, de propósito:** o cenário de trava exigia o aninhamento — sem ele, pool cheio vira backpressure normal (requisições enfileiram e drenam), não deadlock. Um `timeout=` por chamada exigiria tocar ~50 call-sites pra proteger um caminho que deixou de existir; se for feito algum dia, o lugar certo é um wrapper único de acquire. **Também não mexi em `--concurrency=80`** (o follow-up de 07-04 sugeria 40): é decisão de capacidade, não correção de bug.

- **F93 (MED) — jobs auditam fetch parcial ou falho como `success`, e não auditam crash:** `record_job_run` tem `status: str = "success"` como default ([`_audit.py:21`](../../src/jobs/_audit.py)) e `resync_meta` o chama **sem passar status** ([`meta_resync.py:90`](../../src/jobs/meta_resync.py)). Como `_fetch_all_adaccounts` faz `break` em resposta não-200 e **devolve lista parcial** ([`meta_oauth.py:145-150`](../../src/auth/meta_oauth.py) — comportamento correto pro uso OAuth original, mas o resync o reusa pra deletion detection), uma falha na 1ª página grava `success` com `target_count=0`, e uma falha na página N entrega inventário truncado que `_deactivate_churned` interpreta como churn — **reintroduzindo o sintoma do F65 por outra porta** (latente hoje: ~19-50 contas cabem em 1 página de 200). Além disso, crash inesperado no corpo dos jobs (`build_client`, `fetch_account_details`, `upsert_many`, `_list_tables`) não grava linha nenhuma — o rastro fica só no Cloud Run, então um resync quebrado por dias fica **invisível na trilha de auditoria**. Relacionado ao follow-up de 07-04 "sync Meta pro domínio + token no header", que também moveria esse helper pra `src/meta_ads/sync.py`.
  **✅ CORRIGIDO (2026-08-14).** Três mudanças: (1) `_fetch_all_adaccounts` passou a devolver `AdAccountsFetch(accounts, complete)` em vez de lista nua — o chamador não tinha como distinguir "o BM tem 12 contas" de "a página 2 deu 500" olhando só o tamanho da lista. `complete=True` só na saída limpa (paginação acabou sozinha); erro de página **e** estouro do cap de 50 páginas marcam `False`. (2) `resync_meta` segue fazendo o upsert (aditivo, seguro sobre inventário parcial) mas **pula o `_deactivate_churned`** quando `complete=False`, e grava `status="error"` com mensagem explicando — antes gravava `success` com `target_count=0` quando a 1ª página falhava. (3) `record_job_crash` em [`_audit.py`](../../src/jobs/_audit.py) grava `status="error"` no crash inesperado dos três jobs (`meta_resync`, `account_resync`, `db_backup`) antes do re-raise; usa o **`best_effort` do F83**, pela mesma razão — o audit do crash não pode virar um segundo crash que substitui o original. **Mudança de contrato deliberada:** `record_job_run.status` deixou de ter default `"success"` e virou **obrigatório**, porque era exatamente o default que permitia reportar sucesso por omissão; agora cada call-site é forçado a decidir. **Armadilha no teste:** `record_job_crash` resolve `record_job_run` no namespace de `_audit`, não no do job — patchar em `meta_resync` não interceptaria nada, a mesma armadilha de mock-target que o CLAUDE.md documenta pra pré-flight. **Desdobramento:** fechar este finding **destrava a parte remanescente do F82** — a migração dos 3 call-sites pro header `Authorization` era arriscada justamente porque uma quebra do resync seria auditada como sucesso; agora ela aparece.

- **F94 (MED) — backup bufferiza cada tabela 3× em memória e tira snapshot não-atômico:** [`backup.py:40-59`](../../src/jobs/backup.py) acumula o COPY inteiro num `io.BytesIO`, faz `gzip.compress(buf.getvalue())` (2ª cópia) e `upload_from_string(gz_bytes)` (3ª) com `--memory=512Mi` — enquanto `audit_log` tem retenção infinita por decisão de produto e cresce sem teto, então o job que protege o artefato de compliance é o que tende a morrer por OOM. E cada tabela é dumpada em momento distinto **sem transação englobante**: um manager criado no meio do run produz dump com FK órfã (`mcp_sessions.manager_id` sem linha em `managers.csv`, já que `managers` vem antes na ordem alfabética) → **restore quebra**. Fix: uma conexão + `REPEATABLE READ` pra todos os COPYs e stream incremental pro GCS (`blob.open("wb")`).
  **✅ CORRIGIDO (2026-08-15).** Uma conexão numa transação `REPEATABLE READ` cobre a **descoberta e todos os COPYs** (a descoberta entrou no snapshot de propósito), e o dump vai `COPY → GzipFile → blob.open("wb")` sem materializar a tabela. O `total_bytes` do `params_summary` manteve o significado (bytes **comprimidos**) via um contador que embrulha o writer — sem isso a métrica mudaria de sentido em silêncio. `storage.Client()` é montado **antes** da transação: o snapshot segura o vacuum enquanto aberto.
  **Duas consequências que o fix criou e precisaram de decisão própria.** (1) **Transação única propaga falha:** um `PostgresError` numa tabela aborta a transação e as seguintes não teriam snapshot algum. Em vez de gerar N erros de "current transaction is aborted", o loop marca o restante como falho de uma vez e loga `backup_snapshot_lost`. Erro **não**-Postgres (ex.: falha de rede no GCS) segue sem interromper as demais, como antes. (2) **`blob.open` abre o upload ANTES do COPY**, então uma falha no meio poderia deixar um `.gz` **truncado** no bucket — pior que arquivo ausente, porque pareceria bom até o dia do restore. **Verificado na fonte instalada** (google-cloud-storage 3.12.0) em vez de suposto: `BlobWriter.__exit__` chama `terminate()` na exceção, que faz `transport.delete(upload.upload_url)` e cancela o upload resumable. Os fakes dos testes passaram a espelhar essa semântica — antes eles não conseguiriam expressar a diferença.
  **Ordem dos `with` é carga:** o `GzipFile` fecha ANTES do writer do blob, senão o trailer não é escrito e o arquivo sobe truncado. O teste de round-trip (`gzip.decompress` + contagem de linhas) existe pra pegar exatamente isso. O runbook de restore ganhou a garantia de integridade referencial e o aviso de **não completar uma pasta com outra data**.

### Higiene, dívida e doc-drift

- **F95 (LOW) — 3 secrets Supabase são obrigatórios e não têm nenhum consumidor:** `supabase_url`, `supabase_anon_key` e `supabase_service_key` são campos **required** em Settings ([`config.py:47-49`](../../src/config.py)) e 3 dos 13 secrets montados no `--set-secrets` do deploy, mas grep confirma **zero leituras** em `src/` — as demais ocorrências são comentário. O DB é acessado só via `DATABASE_URL` (asyncpg cru, sem lib supabase no `pyproject.toml`). Todo ambiente (CI, testes, `.env`, Cloud Run) carrega 3 valores que nada lê, e testes mantêm fixtures só pra satisfazer o `required`. Fix: remover de Settings + deploy + atualizar a contagem "13 secrets" do CLAUDE.md em mudança coordenada.
  **✅ CORRIGIDO (2026-08-15).** Removidos de `Settings`, do `--set-secrets` do deploy, do `.env.example`, do `conftest` e dos 3 blocos de `test_config`. **A "mudança coordenada" não era necessária:** `Settings` usa `extra="ignore"`, então env var montado sem campo é inerte — os dois lados podiam mudar em qualquer ordem. Isso importa porque **os Cloud Run Jobs foram criados à mão** e seguem montando os 3; ficam inofensivos até alguém recriá-los. Os secrets continuam existindo no Secret Manager (apagar é decisão à parte, não código). **O guard vale mais que a remoção:** `test_deploy_env_matches_settings.py` cruza `deploy.yml` com `Settings.model_fields` nas **duas direções** — env montado que nenhum campo lê (este finding) **e campo obrigatório que o deploy não fornece**, que é o footgun já documentado no CLAUDE.md ("adicione o secret também ao `--set-secrets`, senão o próximo deploy o apaga") e cuja falha só apareceria no boot da revisão nova, depois do build. **Verificação:** o guard de campo-sem-montagem foi provado por sabotagem (removi `DATABASE_URL` do deploy → RED); o de env-órfão ficou RED naturalmente na janela entre remover de `Settings` e remover do deploy, nomeando os 3.

- **F96 (LOW) — `/accounts/{id}/revoke` devolve `303` cru pra chamada HTMX:** é o **único** dos 7 endpoints acionados por HTMX que não é HX-aware ([`routes.py:582`](../../src/web/routes.py)); os outros respondem `204`+`HX-Redirect`/`HX-Refresh` ou fragmento. O XHR segue o redirect e o htmx injeta o **documento inteiro** dentro do `body.innerHTML`, e só então o `data-v4-reload` da template dispara `location.reload()` — funciona porque o reload mascara, ao custo de 2 round-trips, um flash de página aninhada, e a compensação morando na template em vez do handler. Fix: espelhar `sessions_revoke` e remover `data-v4-target`/`swap`/`reload` da template. Family: classe do 2º pacote de 07-04 (303 cru em `hx-post`), instância remanescente.
  **✅ CORRIGIDO (2026-08-15).** Handler devolve `204` + `HX-Refresh: true` quando `HX-Request` está presente, e segue com `303` no POST sem JS — espelhando `admin_invite_cancel` (mesmo arquivo), que já usava esse par. Sem toast de propósito: o refresh do browser destruiria o `HX-Trigger` antes de ele renderizar, e a mudança de badge para "Revogada" já é o feedback. A template perdeu as 3 compensações e ficou idêntica ao botão de `/sessions`. **O guard é genérico, não pontual:** em vez de proibir este botão específico, ele varre TODA template atrás de swap no `<body>` (`data-v4-target="body"` ou `hx-target="body"`) — a assinatura do problema, que nunca é legítima: se o htmx precisa trocar o documento inteiro, quem deveria ter mandado navegar é o handler. Instância futura da classe cai no guard sozinha.

- **F97 (LOW) — `v4-table--sticky-head` gruda em `top: 0` sob ~208px de chrome sticky opaco:** a regra ([`v4-components.css:693`](../../src/web/static/v4-components.css)) usa `top: 0; z-index: 1`, e seu **único consumidor** é [`admin/audit.html:68`](../../src/web/templates/admin/audit.html) — justamente a página com a pilha mais profunda (header 65 + subnav 55 + barra de filtros 88), toda em `z-index: 10` e fundo opaco. Ao rolar, o cabeçalho de colunas encosta em 0 e **desaparece atrás do chrome**. É a classe **F79** sobrevivendo na regra CSS: o fix de 08-11 mediu e corrigiu os offsets nas templates, mas não alcançou este, que estava no design system. Complicador pro fix: a barra de filtros de `/admin/audit` **não** tem `data-sticky-measure` (só a de `/audit` tem), então o offset correto exige estender a medição ou expor um token dedicado. **Lição:** ao corrigir uma classe de bug por varredura, varra também as regras do design system — não só os call-sites.
  **✅ CORRIGIDO (2026-08-15).** O `top` virou `var(--v4-sticky-head-offset, 0px)` — variável porque a mesma regra serve páginas com pilhas de chrome diferentes; o default `0` continua correto pra tabela sem nada sticky acima. Quem tem chrome declara a própria pilha: o modificador `.v4-table--sticky-head-under-filters` resolve `calc(--v4-tab-bar-offset + --v4-filter-bar-h)` = **208px** no desktop. **O complicador foi resolvido, não contornado:** a barra de `/admin/audit` ganhou `data-sticky-measure`, então a altura é medida em runtime em vez de herdar o literal `88px` — que foi aferido na barra de `/audit` (flex-wrap), não neste grid de 5 colunas. Sem isso o offset erraria em toda janela fora do literal, que é **exatamente o modo de falha do F79**. No celular a barra vira estática, o script publica `0` e o cabeçalho gruda sob header+subnav (116px) — o comportamento certo. Confirmado que a tabela **não** está em `.v4-table-wrap` (o overflow mataria o sticky e tornaria o fix inócuo).

- **F98 (LOW) — `get_recommendations` não tem `limit` algum:** o schema não expõe o param e `recommendations_query()` não tem `LIMIT` no builder — não é "default alto" (classe F2/F22), é **ausência total de teto**. As recomendações do Google escalam com nº de ad_groups/keywords (`RESPONSIVE_SEARCH_AD_ASSET` e `KEYWORD` são por ad_group), então uma conta grande pode estourar o cap de token do MCP. `get_conversion_actions` e `get_budget_pacing` têm a mesma ausência, com risco menor por serem limitados pela estrutura da conta. Fix: `limit` com default ≤100 nos 3 schemas.
  **✅ CORRIGIDO (2026-08-15).** `limit` (default **100**, max 1000) nos 3 schemas, e o builder pede **`limit + 1`** — a linha sentinela é o que permite responder `truncated` honestamente, mesmo truque do `LIMIT 101` de `bulk_pause.py`. A sentinela é cortada antes de chegar ao gestor. **O `budget_pacing` exigiu mais que os outros dois:** ele ordena por gasto DESC **depois** de receber as linhas, então um `LIMIT` sem `ORDER BY` entregaria N campanhas arbitrárias reordenadas entre si — parecendo o topo de gasto da conta sem ser, que é exatamente a classe **F88**. A query ganhou `ORDER BY metrics.cost_micros DESC` e um teste asserta que o `ORDER BY` vem **antes** do `LIMIT`. Os outros dois são inventário (não há ranking implícito), então ficaram na ordem natural + flag. **As 3 queries com `LIMIT 101` foram validadas via `validate_gaql` contra a API real ANTES do teste existir** (lição F87) — incluindo o `ORDER BY` em `metrics.cost_micros`, que não era óbvio que o recurso `campaign` aceitasse.

- **F99 (LOW) — doc-drift no CLAUDE.md contra o próprio código:** (a) a seção *Segurança web* declara "Allowlist atual: `cdn.tailwindcss.com`, `unpkg.com`, `fonts.bunny.net`" (linha 98), mas `_CSP_POLICY` ([`middleware.py:47-54`](../../src/web/middleware.py)) tem só `unpkg.com` e `fonts.bunny.net` — **`cdn.tailwindcss.com` foi removido em 08-11 e há guard assertando a ausência dele**, então seguir o doc induz a re-adicionar um host que o CI rejeita; (b) a seção *Design system* ainda abre com "Tailwind CDN (no build)" (linha 210), contradizendo a seção Stack do mesmo arquivo e o pacote de 08-11; (c) "~22 macros em `_components.html`" — são **16**. Verificados e **corretos**: contagem de tools (64 = 58 Google + 6 Meta; 23 always + 41 defer) e a lista de 13 secrets (que bate 1:1 com o deploy, ressalvado o F95). **Lição:** doc que contradiz um guard é pior que doc desatualizado — ele instrui a quebrar o CI.
  **✅ CORRIGIDO (2026-08-15, commit `c3bc1cd`).** Os 3 pontos corrigidos no CLAUDE.md: a allowlist da CSP agora lista só `unpkg.com` + `fonts.bunny.net` **e diz que há guard assertando a ausência** de `cdn.tailwindcss.com`; a seção *Design system* abre com "Tailwind gerado offline e commitado (não CDN)"; e "16 macros". A contagem de secrets também mudou depois (F95: 13 → 10).

- **F100 (LOW, test-infra) — data fixa em teste validado contra janela móvel é bomba-relógio; esta detonou por SETE MINUTOS:** `test_import_offline_conversions.py` mandava `conversion_date_time: "2026-05-17 14:30:00"` fixo, e a tool rejeita conversão com mais de 90 dias (janela click-to-conversion do Google, `_validate_payload_shape` check 3). Em **2026-08-15 às 14:37 BRT** o valor completou **90 dias e 7 minutos** → os 2 testes passaram a receber `status="error"` em vez de `dry_run` e derrubaram o CI. O run do dia anterior, com o MESMO código de teste, passou — a diferença era o relógio. **Diagnóstico:** o vermelho apareceu logo após o merge do F87 e a suspeita natural era regressão do escape GAQL; o pré-flight, porém, estava mockado no teste, o que descartava esse caminho. A aritmética fechou a causa real. **Lição:** teste cujo input é validado contra janela relativa a `now` NÃO pode ter data literal — ou ancora em `now` (`datetime.now() - timedelta(days=7)`), ou congela o relógio (`freeze_time`, como `test_overview_tools.py` já faz). Literal só é seguro em campo de resposta MOCKADA (o que o provider ecoa) ou em builder de query puro, que não valida nada. **Fix:** helper `_conversion_date_time(days_ago=7)` ancorado em `now`. Varredura confirmou que era a única do tipo: as demais datas literais em `tests/` alimentam builders puros ou mocks. Family: test-infra time-bomb (nova; prima do "mock infiel" do F89/F16 — as duas fazem o teste descrever um mundo que não é o de produção). **Nota de processo:** o gate `needs: test` funcionou como desenhado — o deploy foi **pulado** e produção seguiu na revisão anterior. Vermelho no CI, zero impacto no ar.

**Nota de método — o que a paralelização acha e o que ela não acha:** as 6 auditorias rodaram sobre áreas propositalmente disjuntas, e **duas convergiram sozinhas no mesmo achado** (o audit Meta lendo `customer_id` do `params_summary`), o que é sinal de cobertura real e não de sorte. Em contrapartida, uma hipótese forte levantada a priori — `meta_list_my_ad_accounts` vazando o inventário do BM entre gestores — **foi refutada na verificação**: o tool chama `list_accounts_for_manager`, que faz INNER JOIN com `manager_meta_account_access` filtrando por `manager_id`, espelhando o lado Google (existe um `list_all` sem filtro no repositório, mas só o painel admin e o job de sync o consomem). Vale registrar o negativo: é a segunda vez (com A7) que uma suspeita plausível cai ao ser confrontada com o código, e o custo de verificar é uma fração do custo de "consertar" um não-bug.

---

## Investigação de frontend 2026-08-19 (F101-F108)

> Varredura do painel sem escopo prévio, uma semana depois do pacote de 08-11. Método: três varreduras mecânicas (variáveis exigidas por template × contexto passado pelas rotas; classes `v4-*` usadas × definidas; URLs das templates × rotas declaradas) mais leitura dirigida. **Os 8 estão fechados.** Detalhe: [`session-2026-08-19-frontend-handoff.md`](session-2026-08-19-frontend-handoff.md).
>
> **O padrão que une os mais graves: cada um caía num ponto cego de um guard que existia e estava VERDE.** O guard do fragmento de toggle checava só a ausência de `hx-on`; o de caching assertava o header da resposta e nunca a cobertura do `?v=`; o de offset sticky citava uma página pelo nome. Guard que passa não é guard que cobre — a pergunta certa é "o que este guard NÃO olha".

- **F101 (HIGH, a11y) — o nome acessível da matriz de acessos degrada no primeiro swap HTMX:** `_toggle_checkbox_fragment` ([`routes.py`](../../src/web/routes.py)) servia `aria-label="Alternar acesso"` e atendia **quatro** templates com duas estratégias de rótulo diferentes: nas matrizes (`access.html`, `access_meta.html`) o HTML inicial dizia "Acesso de {gestor} à conta {conta}"; nas views por gestor (`access_manager_detail*.html`) o nome vinha de um `<label>` que embrulha o input. Depois do primeiro toggle todos viravam "Alternar acesso" — e no detail o `aria-label` **vence** o `<label>` na computação do nome acessível, então o texto visível e o anunciado passavam a discordar (território do WCAG 2.5.3 *Label in Name*). Numa grade N×M de checkboxes idênticos o rótulo é a única coisa que os distingue, e a view por gestor é justamente a que a matriz recomenda no celular. Family: **F74** (fragmento que não sobrevive ao swap), agora na acessibilidade em vez do handler.
  **✅ CORRIGIDO (2026-08-19).** O fragmento **deixou de carregar texto**: emite `aria-labelledby="v4-mgr-<manager_id> v4-acc-<account_id>"`, apontando pro cabeçalho do gestor e pro da conta, que ficam **fora do nó trocado**. O valor é **função pura dos dois ids que já chegam no form**, então template e fragmento não têm como divergir — sem leitura extra de banco e sem texto duplicado. É a mesma estratégia do F74 (tornar a perda impossível por construção) aplicada ao rótulo, em vez de exigir paridade e confiar num teste pra lembrar. A assinatura mudou de `vals: dict` pra `manager_id`/`account_id`/`account_field`, eliminando a redundância entre o dict e os ids. **Armadilha:** havia um `tests/unit/test_toggle_fragment_escape.py` usando a assinatura antiga — o CLAUDE.md já avisa ("grep TODOS os patch-sites em `tests/`") e mesmo assim escapou na primeira passada; pego pelo `check_pre_push`. O teste ficou **mais forte** depois: o id injetado agora alimenta dois atributos, então o escape é assertado nos dois.

- **F102 (MED) — logo servido `immutable` por 1 ano sem cache-buster:** `CachedStaticFiles` ([`static_files.py`](../../src/web/static_files.py)) marca **todo** `/static` com `public, max-age=31536000, immutable`, e o docstring do próprio módulo condiciona a segurança disso a versionar as URLs. Duas escapavam: o logo do header ([`_base.html`](../../src/web/templates/_base.html), toda página autenticada) e o do hero de login. Efeito duplo — trocar o arquivo nunca chegaria em quem já visitou (`immutable` suprime até a revalidação no refresh, por spec), e como o favicon aponta pra **mesma URL com `?v=`**, o mesmo SVG era baixado **duas vezes**, sob duas chaves de cache.
  **✅ CORRIGIDO (2026-08-19).** As duas URLs ganharam `?v={{ asset_version }}`. **O guard é que importa:** `test_toda_referencia_a_static_carrega_cache_buster` varre as templates atrás de `href`/`src` sob `/static` sem `?v=`. Os testes de caching que já existiam assertavam o **header da resposta** e nunca a cobertura do lado do consumidor — a invariante tinha metade guardada.

- **F103 (MED, a11y) — 8 controles de formulário sem nome acessível:** em [`admin/audit.html`](../../src/web/templates/admin/audit.html) os cinco `<label class="v4-form__label">` não tinham `for=`, os `<select>` não tinham `id` e o label não embrulhava — o rótulo **visual** estava do lado e não estava ligado a nada, enquanto a página irmã `/audit` faz certo com exatamente os mesmos filtros. Em `admin/accounts.html` (filtro de MCC) e `admin/managers.html` (role, status) os selects não tinham rótulo nenhum nem `aria-label`, ao lado de um `search_input` que recebe `aria_label` pela macro. Leitor de tela anuncia "caixa de combinação" sem nome.
  **✅ CORRIGIDO (2026-08-19).** Os cinco de `/admin/audit` ganharam o mesmo par `for=`/`id=` que `/audit` já usava; os três de filtro ganharam `aria-label` (não há rótulo visível a criar sem mexer no layout da barra). Guard `test_todo_controle_de_formulario_tem_nome_acessivel` aceita as **três** formas de vínculo — `label for`, `aria-label` e `<label>` que embrulha — em vez de exigir uma.

- **F104 (LOW, a11y) — 15 `<th>` sem `scope`** em `accounts.html`, `dashboard.html`, `admin/index.html` e `admin/invites.html`, enquanto todas as outras tabelas do painel já declaravam `scope="col"`.
  **✅ CORRIGIDO (2026-08-19).** Guard `test_todo_th_declara_scope`. **Armadilha do regex:** `<th([^>]*)>` casa `<thead>` também (`th` + `ead`), e o guard nasceu apontando 29 falsos positivos. Exigir que o caractere após `th` não seja letra (`<th([^a-z>][^>]*)?>`) resolve. Vale como lembrete de que guard grep-based precisa ser lido contra o próprio ruído antes de virar verdade.

- **F105 (LOW, a11y) — `role="button"` no `<tr>` expansível achata a linha:** [`audit.html`](../../src/web/templates/audit.html) resolvia o acesso por teclado da linha expansível com `tabindex="0" role="button"`. Só que pela ARIA os filhos de um `button` são **presentacionais**: a linha inteira vira um nome único e as células perdem o vínculo com os `<th scope="col">` — justamente na tabela que **é** o log de auditoria.
  **✅ CORRIGIDO (2026-08-19).** `role="button"` saiu; ficam `tabindex="0"` e `aria-expanded`, que **é suportado em `role=row`** (uso de treegrid), com o handler de Enter/Espaço que `v4-panel.js` já tinha. Teclado preservado, semântica de tabela restaurada. Guard `test_linha_expansivel_nao_vira_button`.

- **F106 (MED, segurança) — a isenção de CSRF cobria duas mutações do painel:** `_CSRF_EXEMPT_PREFIXES` ([`middleware.py`](../../src/web/middleware.py)) isentava o prefixo `/oauth/` inteiro, justificado no comentário por "callbacks (GET) ou o data-deletion POST que valida o próprio HMAC". Mas `POST /oauth/meta/revoke` e `POST /oauth/meta/refresh-accounts` são ações do **painel** autenticadas por cookie (`Depends(current_manager)`), disparadas por `<form method="post">` em `admin/index.html` — vivem sob `/oauth` por acidente de roteamento (o `APIRouter` tem `prefix="/oauth/meta"`) e ficavam fora da única checagem de origem que existe. **Não era explorável:** SameSite=Lax não manda o cookie num POST cross-site, e essa é a defesa primária declarada no docstring da própria classe. Mas a camada de defense-in-depth existe justamente pra não depender de uma só.
  **✅ CORRIGIDO (2026-08-19).** Isenção por **rota**, não por prefixo: `("/oauth/meta/data-deletion-callback", "/mcp")`. Os demais endpoints OAuth são GET — método seguro, nunca checado —, então a isenção larga não protegia nada que precisasse dela. **Lição:** isenção por prefixo herda tudo que um roteador com `prefix=` vier a pendurar ali depois; a rota nova entra na isenção sem passar por revisão nenhuma.

- **F107 (LOW) — `sessions_revoke` sem HTMX devolve 200 num POST:** o ramo final renderizava `sessions/list.html` com 200, então recarregar re-executava a revogação — quebra de POST-redirect-GET, contra a convenção que o CLAUDE.md fixa e que o **próprio ramo HTMX da rota** já seguia. Os dois testes de integração existentes mandam `HX-Request: true`, então cobriam só os caminhos HTMX; foi por ali que o 200 passou. Family: **F96** (303 cru em `hx-post`), o espelho — aqui o defeito é o oposto, 200 onde devia haver 303.
  **✅ CORRIGIDO (2026-08-19).** `303` pra `/sessions` no ramo sem HTMX. De quebra saiu uma pré-busca morta de `sessions` no primeiro bloco: só o ramo HTMX-da-lista usa a lista, e ele refaz a query com o `include_revoked` que vem do `HX-Current-URL` — eram duas idas ao banco pra uma resposta. Dois guards: um AST (roda sem Docker) e um de integração que exercita o ramo de verdade (o `client` de teste não segue redirect, então o 303 é observável).

- **F108 (LOW, higiene) — 9 regras CSS e 2 ramos de JS sem nenhum consumidor:** `.v4-dialog`/`.v4-dialog__panel` (substituídos por `.v4-modal`), `.v4-skeleton`, `.v4-stat-grid`, `.v4-card--compact` (3 regras), `.v4-alert--copyable` e as classes `.v4-fade-in`/`.v4-slide-up`/`.v4-pulse` viajavam em toda visita sem que nenhuma template as aplicasse; `v4-panel.js` lia `data-v4-reload` e `data-v4-confirm-kind`, que nenhuma template emite.
  **✅ CORRIGIDO (2026-08-19).** Removidos. **O `@keyframes v4-fade-in` FICA** — `.v4-dropdown.is-open` e o alert o consomem direto; só a classe homônima saiu, e confundir os dois quebraria o dropdown. O comentário do bloco `prefers-reduced-motion` listava as animações infinitas nominalmente e passaria a mentir: como o seletor é universal, a lista era manutenção à toa e virou uma frase que não precisa dela. **Armadilha:** regex de remoção do tipo `seletor{...}` não serve pra `@keyframes` (chaves aninhadas) — `v4-motion.css` foi reescrito à mão, e a sanidade conferida por balanço de chaves em todos os CSS.

**Hipótese forte que caiu na verificação** (vale o registro, como o A7 e o `meta_list_my_ad_accounts`): a barra de filtros de `/admin/audit` parecia não ter `data-sticky-measure`, o que deixaria `--v4-filter-bar-h` no fallback de 88px — aferido na barra flex do `/audit`, não naquele grid de 5 colunas — e faria o `<thead>` sticky sumir sob a barra entre 640px e 767px. **Falso:** o atributo está lá desde o F97, na **linha 16**, na abertura do `<form>`; a leitura do arquivo começou na linha 20, e o comentário do F97, que explica *por que a medição é necessária ali*, foi lido como se admitisse a ausência dela. O guard novo (`test_toda_barra_que_alimenta_offset_sticky_e_medida`) ficou mesmo assim, porque **o antigo citava `audit.html` pelo nome**: tirar `data-sticky-measure` de `/admin/audit` não falhava teste nenhum. Agora a lista de páginas sai do próprio consumo do token no template. **Lição dupla:** ler trecho de arquivo em vez do bloco inteiro produz achado fantasma — e guard que passa de primeira merece o mesmo ceticismo do guard que falha (aqui ele passou por estar certo, mas isso só apareceu ao investigar *por que* passou, em vez de assumir o erro do outro lado).

**O que foi verificado e estava limpo:** zero JS/CSS inline nas templates e CSP sem nenhum `unsafe-*` (intactos desde 08-11); nenhuma classe `v4-*` órfã; nenhuma das 48 URLs distintas das templates sem rota correspondente (47 rotas, contando os prefixos `/oauth/*`); nenhuma variável faltando no contexto das 26 chamadas de `TemplateResponse`; nenhum XSS — todo `|safe` recebe literal ou o mapa fixo do flash, `request.query_params` nunca chega na macro `alert`, e o `{{ reason }}` dentro de comentário HTML em `access_denied.html` está num branch de enum fechado; nenhum `id` duplicado, `<img>` sem `alt` ou `<button>` sem nome acessível; token de sessão em cookie httponly, `SameSite=strict`, path-scoped e 60s — nunca em query param.

---

## Investigação de backend 2026-08-19 (F109-F112)

> Varredura do núcleo (tools MCP, executores Google/Meta, DB, auth, jobs, governança) no mesmo dia da investigação de frontend, e cinco dias depois da varredura ampla de 08-14/15. Método: varreduras AST **transitivas** sobre `src/`, mais leitura dirigida e verificação empírica na fonte instalada das libs. **Os 4 estão fechados.** Detalhe: [`session-2026-08-19-backend-handoff.md`](session-2026-08-19-backend-handoff.md).
>
> **O achado que organiza a sessão: o F86 foi fechado sem guard nenhum.** `run_blocking` não aparecia em lugar algum de `tests/` — nem guard estrutural, nem teste — e três caminhos que atendem request ficaram bloqueando o event loop por cinco dias. É a contraparte exata da lição da investigação de frontend do mesmo dia ("guard verde não é cobertura"): aqui não havia nem guard verde.

- **F109 (HIGH) — três caminhos que atendem request seguiam bloqueando o event loop (F86 incompleto):** o fix do F86 cobriu 4 executores e parou ali, sem deixar guard. Ficaram: (a) [`validate_gaql`](../../src/mcp/tools/validate_gaql.py) chamando `ga_service.search()` direto no `async def` — é o tool que **não passa pelos executores** (constrói o client sozinho), o mesmo motivo que o deixou sem o gate do F57; (b) [`run_recommendation_action`](../../src/google_ads/mutations.py) chamando `execute_apply/dismiss_recommendation` direto, com o irmão `run_mutation` fazendo certo **180 linhas acima no mesmo arquivo**; (c) [`run_meta_graph_get`](../../src/meta_ads/reports.py) — o pior dos três — com `api.call()` dentro de um `while` de até **5 páginas**, ou seja round-trips **sequenciais** ao `graph.facebook.com` com o loop parado. Cada um congela a instância inteira: com `--concurrency=80` os requests serializam e o `asyncio.timeout(5)` do `/health?deep=1` nem começa a contar, porque o timer só dispara quando o loop volta a girar — 503 no uptime check indistinguível de problema de banco. **A lista dos 6 sites já existia**: é a que o CLAUDE.md enumera pro gate do F57. O F86 usou outra.
  **✅ CORRIGIDO (2026-08-19).** Os três passaram por closure + `run_blocking`. No de recommendations o `get_request_id()` foi pra **dentro** do offload — o interceptor grava num ContextVar durante a chamada e `to_thread` COPIA o contexto, então ler do lado do loop devolveria `None` e o `provider_request_id` sumiria do audit em silêncio (armadilha que o `run_mutation` já documentava). No Meta a **paginação inteira** entrou num closure só: offloadar apenas a 1ª chamada mudaria o bloqueio de lugar, como no stream do lado Google. `_blocking.py` saiu de `google_ads/` pra [`src/blocking.py`](../../src/blocking.py): serve os dois SDKs, e `meta_ads` importar de `google_ads` seria dependência invertida.
  **Verificação empírica antes de afirmar:** `FacebookAdsApi.call` foi inspecionado na fonte instalada — não é coroutine e usa `self._session.requests.request(...)`. Não foi deduzido de doc.
  **Guard `test_chamada_bloqueante_sai_do_event_loop`, e ele exigiu duas correções antes de valer:** (1) o fecho precisa ser **transitivo** — `run_recommendation_action` não chamava o SDK, chamava um helper sync que chama, então um guard que só olhasse nomes de método daria verde nele; (2) precisa distinguir chamada de **atributo** de **nome nu**, senão acusa `apply_change`, porque `run_offline_user_data_job` é ao mesmo tempo método do SDK e nome do nosso executor async (que já offloada). Provado contra o código pré-fix: RED nos 5 sites, zero falso positivo.

- **F110 (MED) — `get_my_rate_limit_status` reportava a quota que NÃO bloqueia o chamador:** desde o F73 todo executor reserva contra duas chaves — o developer token global (15.000) e `mgr:<uuid>` com `manager_daily_quota` (default **5.000**). O tool ([`get_my_rate_limit_status.py`](../../src/mcp/tools/get_my_rate_limit_status.py)) lia só a primeira. Como 5.000 < 15.000, o cap por gestor é o que barra na prática: o gestor tomava `quota diaria esgotada` de uma tool, chamava este pra diagnosticar, e ouvia *"5200/15000, 34.7%, restam 9800"*. Enganava exatamente no momento em que era consultado. O tool é anterior ao F73 e não foi atualizado quando o cap nasceu.
  **✅ CORRIGIDO (2026-08-19).** A linha `mgr:` está na mesma tabela com a mesma forma — ler foi uma linha. A resposta traz `manager` e `account` separados mais `blocking_scope`, decidido por chamadas **absolutas** restantes e não por percentual (90% de 15.000 sobra mais que 50% de 5.000). **As chaves planas antigas saíram de propósito:** eram elas que sugeriam "sua quota" pra um número que era da conta inteira; mantê-las preservaria a ambiguidade que É o bug. Os 3 testes antigos passaram a ler de `account`, com nota dizendo que o mock deles devolve o mesmo `Usage` pras duas chaves e portanto **não consegue expressar** a diferença — quem expressa é o teste novo, com `side_effect` por chave (evita a classe "mock que não consegue expressar o bug", F84/F89).

- **F111 (LOW, latente) — audit Meta derivava a conta de um dict opcional:** [`run_meta_graph_get`](../../src/meta_ads/reports.py) gravava `customer_id=(params_summary or {}).get("ad_account_id")` nos caminhos de sucesso e de erro, tendo `ad_account_id` como kwarg **obrigatório** desde o F72. Os 3 callers de hoje passam a chave (verificado um a um), então estava correto — o risco é o próximo, e **M.5 é o próximo sprint**: um tool Meta novo que esqueça a chave grava linha de auditoria **sem conta**, na plataforma onde o token é compartilhado e a matriz de acesso é o único freio. É a mesma forma que o F72 corrigiu no gate e o F88-era corrigiu no contador BUC, deixada no audit. O caminho de negação já usava o kwarg — a inconsistência estava dentro do mesmo arquivo.
  **✅ CORRIGIDO (2026-08-19).** Os 2 sites passaram a usar `ad_account_id`. Guard AST assertando que as 3 chamadas de `audit_log.record` do executor derivam `customer_id` do kwarg.

- **F112 (LOW, latente) — a política de blast radius é consultiva em 17 das 26 tools de mutação:** [`blast_radius.classify`](../../src/governance/blast_radius.py) se descreve como quem "decide auto-apply vs require-confirmation", mas só **9** tools leem `.level`. As outras 17 computam o veredito e usam apenas `.reason` como texto, com o caminho (auto-aplicar ou emitir token) fixo no código. **Verifiquei os dois lados: não há divergência hoje** — as always-CONFIRM chamam `create_pending` incondicionalmente e as 5 auto-apply caem em ramos que retornam AUTO constante. O risco é apertar a política no módulo — por exemplo passar `remove_negative_keywords` a CONFIRM, defensável já que remover negativa **alarga** o targeting — e as 17 seguirem o caminho antigo em silêncio.
  **✅ CORRIGIDO (2026-08-19) — e a decisão de desenho importa mais que o fix.** Reescrever as 17 pra consultarem `.level` era a outra saída; não vale o tamanho. **O risco não é a tool errar, é a política e a tool DIVERGIREM**, e isso um teste pega por uma fração do custo. O guard **deriva** a lista do source (quem lê `.level` é pulado; quem só emite token tem que ser CONFIRM; quem só chama executor tem que ser AUTO) e falha alto se uma tool não couber em nenhum caso — então tool nova entra sozinha, sem lista à mão pra envelhecer. **Provado por sabotagem**, porque passou de primeira: apertar a política deixa o guard RED exatamente na tool divergente; revertido, verde.

**O que foi verificado e estava limpo** — a maior parte da varredura: nenhum `datetime.now()`/`utcnow()` sem timezone em `src/`; nenhuma SQL montada com dado de usuário (todas parametrizadas por `$N`, com o `WHERE` montado de literais); os 7 call-sites de `ensure_account_access` usam o nível certo (`write` nas mutações, `read` nas leituras) e `can_manager_access` é simétrico entre Google e Meta; `dry_run.consume` é race-safe (`SELECT ... FOR UPDATE` + `consumed_at`), amarrado à sessão e com TTL checado; a aritmética do rate limit está correta sob o `FOR UPDATE`, e o `pct` como fração (0–1) é deliberado — o consumidor renderiza `pct * 100`; os 28 `except` que "engolem" são todos envelope de erro ou observabilidade defensiva documentada; OAuth e resync usam `httpx` async; `accounts.py` ser síncrono é exceção documentada e confirmei que **só** o job de resync o importa.

**Hipótese que caiu na verificação:** `apply_change` checa `status == "error"` num ramo e não nos outros dois — parecia inconsistência defensiva. **Falso:** só `run_conversion_upload` devolve dict de erro; `run_mutation` e `run_offline_user_data_job` levantam. A checagem está exatamente onde pode haver erro pra checar. Terceira vez seguida (com o `meta_list_my_ad_accounts` e a barra sticky do `/admin/audit`) que uma suspeita plausível cai ao ser confrontada com o código — e o custo de verificar segue sendo uma fração do custo de "consertar" um não-bug.

---

## Investigação de infra e CI 2026-08-19 (F113-F117)

> Terceira varredura do dia (depois de frontend e backend), agora nos workflows, no deploy, nos Cloud Run Jobs, nos scripts de gate e nas migrations. **Os 5 estão fechados.** Detalhe: [`session-2026-08-19-infra-ci-handoff.md`](session-2026-08-19-infra-ci-handoff.md).
>
> **Limite declarado da investigação:** o `gcloud` estava sem credencial válida (`Reauthentication failed. cannot prompt during non-interactive execution`), então a auditoria foi da **configuração declarativa do repo**. Estado vivo — env real dos jobs, crons do Scheduler, alert policies, IAM — **não foi verificado**. Os fixes foram desenhados para serem seguros sem esse conhecimento (ver F114).

- **F113 (MED) — o `ci.yml` ensinava a regenerar o lockfile com um comando que quebra o build Linux:** [`ci.yml`](../../.github/workflows/ci.yml) dizia *"Regerar o lock: `uv pip compile pyproject.toml -o requirements.txt`"*, **sem `--universal`** — a flag que o CLAUDE.md marca como obrigatória. Rodei os dois pra confirmar em vez de deduzir: sem ela sai `pywin32==312`; com ela, `pywin32==312 ; sys_platform == 'win32'`. A máquina do dev é Windows (`uv … x86_64-pc-windows-msvc`), então seguir a instrução do próprio CI produz um lockfile em que o buildpack CNB tenta instalar `pywin32` no Linux. Classe **F99**, agravada: não é doc velha, é doc que instrui a quebrar produção — e estava no arquivo que se lê ao mexer no step de instalação.
  **✅ CORRIGIDO (2026-08-19).** Comando corrigido, com o motivo escrito ao lado. Dois guards: toda instrução de regerar o lock precisa do `--universal` (o casamento exige `pyproject.toml` na linha, pra pegar **comando copiável** e não menção em prosa — "o lockfile sai de um uv pip compile do pyproject" é legítimo), e o `requirements.txt` commitado precisa carregar o marker de plataforma no `pywin32`, que é a prova de que saiu de um compile universal.

- **F114 (MED) — os 3 Cloud Run Jobs precisavam de 8 campos obrigatórios que nada no repo declarava:** `migrate`, `resync` e `backup` rodam o mesmo codebase e chamam `get_settings()`, que valida o `Settings` **inteiro** na subida — então cada um precisa dos 8 campos sem default, inclusive `migrate` e `backup`, que funcionalmente só usam o banco. O [`deploy.yml`](../../.github/workflows/deploy.yml) já re-apontava imagem e `--command` dos 3 a cada push (self-healing contra drift manual), mas o env ficava só na criação à mão: sem fonte de verdade no repo e **sem guard** — `test_deploy_env_matches_settings` lê `--set-env-vars`/`--set-secrets`, que só existem no step do **serviço**. Que a config manual deriva já estava registrado: o **F95** anotou que os jobs seguem montando os 3 secrets Supabase removidos. E os dois arquivos discordavam entre si — `deploy.yml` dizia *"DATABASE_URL foi setado na criação do job"* enquanto o `infra-setup.md` corrigia (*"precisa do MESMO secret set do resync"*); o que subestimava era o arquivo que se edita ao mexer no deploy. Modo de falha: campo obrigatório novo em `Settings` é pego pelo guard no serviço e quebra os 3 jobs em silêncio — `migrate` roda em todo deploy (falha alto), mas `resync` (diário) e `backup` (semanal, o artefato de compliance) falhariam quietos, a cegueira que o **F93** atacou.
  **✅ CORRIGIDO (2026-08-19).** Os 3 job-updates passaram a declarar `--update-env-vars` + `--update-secrets`. **`--update-*` é MERGE, não replace** — a escolha é deliberada: sem gcloud eu não conseguia enumerar o estado real dos jobs, e `--set-secrets` apagaria o que eu não visse. A lista vive num `env:` do job pra não ser triplicada (triplicar criaria exatamente a divergência que o guard existe pra impedir); o guard expande a variável antes de parsear. Guard: `test_todo_job_recebe_os_campos_obrigatorios`, que ficou RED listando os 8 campos ausentes em cada um dos 3.

- **F115 (LOW) — o guard do Tailwind só existia no CI:** mexer numa classe utilitária de template e dar push virava CI vermelho **depois** da espera do runner, e a única proteção era a regra do CLAUDE.md ("rode o build e commite no mesmo commit"). Comparando mecanicamente, era a **única** diferença entre os 9 steps do CI e os 5 do gate local.
  **✅ CORRIGIDO (2026-08-19).** [`scripts/check_tailwind_sync.py`](../../scripts/check_tailwind_sync.py) entrou no gate local, **por último** (é o único que depende de ferramenta externa e o mais lento — os checks baratos falham antes). Sem `npx` ele **pula com dica** em vez de bloquear, mesmo padrão do `check_docker()` do full sweep: quem não tem Node também não mexe no CSS gerado, e o CI segue sendo a rede. Guard de paridade derivado dos steps do CI, com **fecho de um nível** — o step chama `check_tailwind_sync.py`, que chama `build_tailwind.py`, e um scanner raso acusaria uma lacuna inexistente (mesma armadilha do F109, no mesmo dia). Verificado por sabotagem: classe utilitária nova sem regenerar → exit 1; em sync → exit 0.

- **F116 (LOW) — o rollback deduzia a revisão anterior por ordem de criação:** [`deploy.yml`](../../.github/workflows/deploy.yml) usava `revisions list --limit=2 | tail -1`, o que só coincide com "a que estava servindo" quando o deploy **chegou a criar** uma revisão. O guard `steps.deploy.outcome != 'skipped'` já cobria falha *antes* do deploy (migration quebrada → step pulado → nada mudou). O que sobrava era um `gcloud run deploy` que falhasse **sem criar revisão** (imagem inexistente, flag inválida, quota): a dedução ficava deslocada em um e o rollback tirava o tráfego da revisão saudável que estava no ar pra pousar numa mais velha — regressão provocada pelo próprio mecanismo de segurança.
  **✅ CORRIGIDO (2026-08-19).** Um step antes do deploy captura `status.traffic[0].revisionName` no `GITHUB_ENV`, e o rollback usa esse valor; serviço inexistente (1º deploy) → vazio → pula com mensagem. **O guard ignora linha de comentário**, porque o bloco que explica o fix cita `revisions list` ao descrever o que saiu — grep casando a própria prosa é a armadilha do **F87**, e esta foi a **4ª vez** neste repo. Provado por sabotagem depois de corrigido.

- **F117 (LOW, doc-drift) — o checkbox de branch protection estava desmarcado com a proteção ativa:** [`infra-setup.md`](infra-setup.md) trazia `- [ ] Branch protection on main`, mas o push de 2026-08-19 recebeu `remote: - Required status check "test" is expected.`, que o GitHub só emite quando a branch está protegida. O fluxo é solo-dev com admin bypass, então o push passa mesmo com o check pendente.
  **✅ CORRIGIDO (2026-08-19).** Checkbox marcado, com a evidência e a ressalva do bypass.

**O que foi verificado e estava limpo:** lista de migrations do `test_migrations.py` em sync com o disco (4/4); os 3 processos referenciados por `--command=/cnb/process/<type>` existem no Procfile; o lockfile consistente por nome (as 14 deps de prod presentes, zero dep de dev vazada); ordem do deploy correta (migrations antes do serviço); `--update-secrets` (merge) e `--set-secrets` (replace) usados cada um no lugar certo; concurrency bem separada (job-level no CI pra não matar o deploy, workflow-level `deploy-prod` serializando); o smoke tolera propagação e distingue "bearer vencido" de "stack quebrado".

**Hipótese que caiu na verificação:** o `infra-setup.md` parecia declarar dois crons diferentes pro mesmo Cloud Scheduler (`0 6 * * *` BRT e `0 7 * * *` UTC). O segundo está na seção marcada como **HISTÓRICO** (projeto antigo `v4-ads-mcp-prod`, a decomissionar). Ler o bloco inteiro em vez do trecho derrubou o achado — **segunda vez no mesmo dia**, depois da barra sticky do `/admin/audit` na investigação de frontend.

---

## Revisão de responsividade 2026-08-20 (F118-F127)

> **Método:** as 24 telas do painel renderizadas fora do app (mesmo `FileSystemLoader`, mesmos filtros, dados realistas — nomes de cliente V4, e-mails `@v4company.com`, token MCP em tamanho real), servidas com o CSS/JS de produção e medidas em **320/360/375/414/768/800/1024/1280px** por `scrollWidth × clientWidth`. Cada correção candidata foi aplicada no DOM e re-medida ANTES de virar código. Todos fechados no commit `79e67d9`; guard em [`test_frontend_responsive_guards.py`](../../tests/unit/test_frontend_responsive_guards.py).

- **F118 (MED) — `/admin/audit` rolava a página inteira na horizontal, e não só no celular:** a tabela de 8 colunas mede ~1080px e estava fora do `.v4-table-wrap` **de propósito** (o overflow mata o `thead` sticky do F97). Medido: **+751px em 375**, +358 em 768, +226 em 900 e **+102px em 1024** — ou seja, o trade-off documentado cobrava scroll horizontal até em notebook. Com a página rolando na horizontal, o header sticky sai de baixo do conteúdo e o layout inteiro desalinha; perder o cabeçalho fixo custa menos.
  **✅ CORRIGIDO (2026-08-20).** Modificador `.v4-table-wrap--wide`: o scroller vale abaixo de 1200px e some acima, onde a tabela cabe e o mecanismo do F97 (offset medido em runtime) segue intacto. **Testado e recusado:** scroller de dois eixos com `thead` sticky por dentro — ele *funciona* (a derrapada de 16px que parecia inviabilizá-lo era o `margin-top` da `.v4-table`, não o sticky), mas trocaria o mecanismo do F97 por uma região de scroll interna, invalidaria o token `--v4-sticky-head-offset` e derrubaria o guard `test_toda_barra_que_alimenta_offset_sticky_e_medida`. Churn demais para um fix de responsividade. O literal de 1200px é um **limiar**, não um offset: errar por alguns px só liga o scroller antes ou depois — verificado sem descontinuidade em 1180/1200/1220/1260/1300.

- **F119 (MED) — `/admin/managers` fora do padrão de tabela porque o dropdown de ações seria clipado:** 7 colunas, 850px, **+545px em 375** e +600 em 320. A exclusão era real: `overflow-x: auto` obriga `overflow-y` a virar `auto` também, então o menu `position: absolute` é clipado. Medido com o wrapper posto à força: o menu caía em `left=711` dentro de um scroller que termina em 320 — invisível, e o admin perdia promover/desativar gestor no celular.
  **✅ CORRIGIDO (2026-08-20).** `v4DesancorarMenu` em [`v4-panel.js`](../../src/web/static/v4-panel.js): quando o gatilho está dentro de um contentor de scroll, o menu vai para `position: fixed` com coordenadas grampeadas na tela, escritas por **CSSOM** (a CSP bloqueia `style=` em atributo, não escrita via CSSOM — mesma brecha que já sustenta os filtros e o drawer). Fecha no scroll com listener em **capture**, porque `scroll` de elemento não borbulha. Verificado com o JS real: abre → destaca (187..367 numa tela de 375) → `elementFromPoint` no centro acerta o `.v4-dropdown__item` → clique fora fecha, reancora e limpa as coordenadas inline. Isso destrava envolver **qualquer** tabela com dropdown daqui pra frente.

- **F120 (LOW) — sparkline de 600px estourando o `/admin`:** o Preflight do Tailwind dá `max-width:100%` a `img` e `video` e **não a `svg`**, e [`admin/index.html`](../../src/web/templates/admin/index.html) chama `sparkline(width=600)`. Medido: 669px de `scrollWidth` num viewport de 375.
  **✅ CORRIGIDO (2026-08-20).** `max-width: 100%` + `height: auto` na `.v4-sparkline`; com o `viewBox` já no lugar, o gráfico reescala para 222px sem perder proporção.

- **F121 (MED) — a regra de layout de página vazava para o `<main>` aninhado do `/help`:** `main { max-width: 1200px; margin: 0 auto; ... }` estava no **seletor de elemento**, e o `/help` abre um segundo `<main>` como coluna de conteúdo. Margem `auto` no eixo cruzado **cancela o `align stretch`** do flex, então a coluna virava `fit-content` do bloco de código — 618px dentro de um container de 286px, **+295px** de scroll horizontal em 375. Dois bugs no mesmo ponto: o documento também emitia **dois landmarks `main`**.
  **✅ CORRIGIDO (2026-08-20).** Regra escopada a `body > main` e o aninhado virou `<div>` — as duas camadas, porque só a template não impediria a reincidência e só o CSS deixaria o landmark duplicado. Medido: 655 → 360 de `scrollWidth`, 2 → 1 landmark. **Pista falsa registrada:** `min-width: 0` no item flex não mudou nada — foi justamente isso que apontou para a margem, e não para o `min-content`.

- **F122 (LOW) — tabela "Conexões Google" do `/accounts` sem contentor:** +275px em 375, +330 em 320. Omissão simples, e reveladora: das três tabelas da mesma página, duas já estavam envolvidas.
  **✅ CORRIGIDO (2026-08-20).** As três agora usam `.v4-table-wrap` (a terceira usava `overflow-x-auto` solto, que não traz o `nowrap` de `th`/`.col-mono`).

- **F123 (MED) — e-mail de gestor e nome de operação estouram em contexto flex/grid, e `break-words` sozinho não resolve:** um e-mail V4 (~33 chars) ou `add_negatives_from_search_terms` são **uma palavra só**, sem ponto de quebra. Medido: `/audit/<id>` +164px, `/admin/access/<id>` e a variante Meta +96px, `by-manager` +66px. A sutileza que custou uma rodada: `overflow-wrap: break-word` **não reduz o min-content**, e item flex não encolhe abaixo dele — com `break-words` aplicado, o `h1` do `/audit/<id>` ainda deixava **123px** de estouro porque é item flex.
  **✅ CORRIGIDO (2026-08-20).** `break-words` **+ `min-w-0`** onde o ancestral é flex; `grid-cols-[140px_minmax(0,1fr)]` no lugar de `1fr` na `dl`; `min-w-0` + `shrink-0` nos cartões de `by-manager`. Em bloco normal (o `h1` de `access_manager_detail`) `break-words` basta — o bloco não faz shrink-to-fit.

- **F124 (MED) — o header estoura de 768 a 799px: o modo mobile desliga antes de o desktop caber:** a media query mobile termina em 767px e o header desktop precisa de ~800px, então **toda** página ganhava scroll horizontal na faixa — 768px é o iPad em retrato. Caracterizado para não inflar a narrativa: reproduz com **admin (6 itens de nav) e e-mail de 33 chars**; gestor comum (5 itens) ou e-mail curto **não** reproduzem.
  **✅ CORRIGIDO (2026-08-20).** `min-width: 0` no `.v4-header__user` + ellipsis no e-mail, e `flex-shrink: 0` na marca, na nav e no botão Sair, para que o aperto caia sempre no e-mail. Os três fixes candidatos (embrulhar o header, subir o breakpoint, truncar) zeram o estouro; truncar é o único que **não muda a ALTURA** do header — e os offsets sticky do F79 estão calibrados em 65/61px. Medido em 768: estouro 0, e-mail em 120px visíveis de 235px de texto, nav com 6 links e Sair dentro da tela.

- **F125 (LOW) — 13 contentores de scroll horizontal fora do alcance do teclado:** nenhum `.v4-table-wrap` tinha `tabindex`. Chrome 127+ tornou scroller focável por default; Firefox e Safari não — nesses, as colunas cortadas ficam inalcançáveis por teclado (WCAG 2.1.1). É o custo escondido do próprio padrão adotado em 2026-08-11.
  **✅ CORRIGIDO (2026-08-20).** `tabindex="0" role="region" aria-label` nos 13, com rótulo específico (o do `/audit` sai do dia do grupo: `Eventos de {{ day }}`). O guard **deriva** a lista do source: qualquer `<div>` nova que abra scroll de tabela cai no teste sem ninguém lembrar de atualizá-lo.

- **F126 (LOW) — token longo em `<code>` inline e no breadcrumb, visível só em 320px e só DEPOIS da primeira rodada:** `%APPDATA%\Claude\claude_desktop_config.json` (43 chars) estourava o `/help` em 40px, e o e-mail no `.v4-breadcrumb__current` estourava `/admin/access/<id>` em 38px. Ficaram escondidos atrás dos estouros maiores e só apareceram quando eles saíram.
  **✅ CORRIGIDO (2026-08-20).** Nos dois casos no **design system**, não na página: `code { overflow-wrap: anywhere }` (com `pre code` de volta a `normal` — ali a quebra destruiria a indentação do snippet, que já rola sozinho) e `flex-wrap` + `overflow-wrap: anywhere` no breadcrumb, que também serve `/sessions/<id>` e `/audit/<id>`. **Como foram achados:** bissecção escondendo subárvore e re-medindo, depois de uma lista truncada em 6 linhas ter deixado o culpado de fora — mesma armadilha de "ler o recorte em vez do bloco" que produziu o achado fantasma de 2026-08-19.

- **F127 (LOW) — card de header do `/admin/accounts/meta` em `flex` sem `flex-wrap`:** o botão "Sincronizar contas" saía 41px para fora em 375px (96px em 320), com o texto do secret não configurado na linha.
  **✅ CORRIGIDO (2026-08-20).** `flex-wrap`.

**Resultado medido depois dos fixes:** **192/192** medições sem estouro (24 telas × 8 larguras), cada uma com checagem de que a página realmente carregou. Regressões conferidas uma a uma: dropdown abre/posiciona/fecha/reancora; `thead` sticky gruda em 1280 e degrada em 1024; coluna fixa da matriz sobrevive a 500px de scroll horizontal; cabeçalho de dia do `/audit` segue grudando em 61px.

**O que foi verificado e estava limpo:** `/audit`, `/dashboard`, `/sessions`, `/sessions/<id>`, `/admin/invites`, `/admin/accounts`, login, `access_denied`, `error` e as três páginas legais — zero estouro em **toda** largura testada. O `max-sm:static` das barras de filtro e a medição contínua por `ResizeObserver` (F79) continuam corretos.

**Hipótese que caiu na verificação:** a matriz de acessos (`/admin/access`, gestores × contas) parecia o pior caso possível — é a tela mais larga do painel. Mediu **zero** estouro em todas as larguras: já estava em `overflow-x-auto`, com coluna fixa que sobrevive ao scroll e um link para a visão por gestor no celular. Era o **modelo** a seguir, não o problema.

**Lição de método (nova):** um harness de medição precisa provar que a página carregou. Uma rodada intermediária devolveu "12/12 verde" porque o iframe rodou num tab de origem `file://`, onde `src="/pagina.html"` não resolve — página vazia tem `scrollWidth == clientWidth`, que é indistinguível de página perfeita. Toda medição posterior passou a carregar junto o `title` e a contagem de nós. Irmã da lição do F84/F89 (teste que não consegue expressar o bug), agora do lado da ferramenta de medição.

---

## Churn de conta Meta 2026-08-20 (F128)

> **Gatilho:** o gestor notou que `Mestre da Obra Petrolina` deixou de ser parceira da V4 Lima Soares no Meta e **continuava listada no MCP**, e perguntou por que não tinha saído sozinha. Não tinha — e a investigação mostrou que "por desenho" não é o mesmo que "aceitável".

- **F128 (MED) — conta que sai do alcance do system user fica ativa e concedida para sempre:** a detecção de churn do Meta é escopada por `business_id` ([`meta_resync.py:59`](../../src/jobs/meta_resync.py)): `_deactivate_churned` agrupa o payload de `/me/adaccounts` e, **para cada BM visto**, desativa o que faltou. Isso cobre "conta removida de um BM ainda visível" e não cobre o caso que mais acontece na operação — parceria encerrada, o system user perde o acesso e **o BM inteiro some do payload**. Sem BM não há keep-list, `mark_inactive_except` nunca é chamado para ele, e a conta fica `is_active=true` indefinidamente.
  **Confirmado ao vivo, não por leitura de código:** probe em `act_468463369497370` (BM `1012131859922651`) devolveu `(#200) Ad account owner has NOT grant ads_management or ads_read permission` enquanto `meta_list_my_ad_accounts` ainda a devolvia — e essa query já filtra `is_active = true` **e** exige grant, então a presença dela provou as duas coisas de uma vez.
  **Segunda camada, que é a que morde:** [`can_manager_access`](../../src/db/repositories/manager_meta_account_access.py) lê **só** a tabela de grants — sem join com `meta_ad_accounts`, sem `is_active`. Então mesmo o churn detectado **não revoga**: desativar esconde da listagem e nada mais. Consequência de segurança que vale registrar: se a parceria voltar, o acesso se restabelece sozinho, sem ninguém re-autorizar.
  **Nada disso era novidade escondida** — a limitação está escrita na docstring desde o fix do F65 (07-02) e virou lição em 15/08 ("o resync não limpa isso sozinho, por desenho; offboarding exige limpeza manual"). O que faltou foi transformar limitação conhecida em finding: por dois meses ela ficou só como comentário, até um gestor tropeçar nela.

  **✅ CORRIGIDO (2026-08-20).** Contador de ausências escopado por **tempo** em vez de por BM, o que o torna imune a BM invisível:
  - migration `005_meta_missed_syncs.sql` adiciona `missed_syncs`; `upsert_many` **zera** ao reaparecer (cliente que volta não chega ao limiar carregando ausência antiga);
  - `bump_missing` incrementa quem não veio e desativa ao cruzar `MISSED_SYNCS_THRESHOLD = 3` — três execuções completas seguidas, não uma, porque uma leitura esquisita não pode derrubar conta viva (é a família F65/F85);
  - só roda com `fetched.complete` (F93: sobre lista truncada "ausente" significa "página que não veio") e **lista de vistas vazia é no-op** — o mesmo fail-safe que o F85 instalou do lado Google, onde a ausência dele desativou as 25 contas do MCC de uma vez;
  - o caminho escopado por BM **continua**: ele age em 1 execução quando o BM está visível; o contador é a rede para o resto. Rápido + lento, não substituição;
  - `missing` e `aged_out` entram no `params_summary` do audit — churn lento sem trilha vira conta sumindo do painel sem explicação;
  - **(d)** `/admin/accounts/meta` ganhou a seção *Fora do alcance do system user*, que lista tanto a desativada quanto a que ainda está a caminho (`missed_syncs > 0`) com o alerta de que **desativar não revoga** e link para a matriz. Sem isso a correção seria invisível: `list_all` só mostra ativas, então a conta desativada sumia do admin e os grants ficavam vivos sem ninguém ver.

  **Deliberadamente fora:** (1) fazer o hard-gate consultar `is_active` — transformaria desativação em revogação, mas dá ao inventário poder de cortar acesso, e um sync com problema passaria a revogar gestor; a decisão de acoplar as duas coisas é de produto, não de correção de bug. (2) A revogação dos grants **desta** conta segue sendo ação humana — o código não revoga acesso de gestor sozinho.

  **Verificação:** 5 unit (no-op com lista vazia, duas escritas com o SQL certo, `upsert` zerando o contador, job não contando ausência em inventário truncado, job contando e auditando quando completo) + 4 de integração contra banco real (ciclo completo até o limiar, reativação zerando a série, inventário vazio não derrubando nada, e a listagem do painel cobrindo as duas rotas de churn). **Docker indisponível na máquina** — os 4 de integração e a migration foram validados pelo CI, não localmente; é o fallback documentado no CLAUDE.md.

  **Lição:** limitação conhecida e documentada continua sendo dívida com prazo. A docstring descrevia o buraco com precisão e mesmo assim ninguém o media — o que fechou o caso foi um probe ao vivo de 1 chamada, que separou "cache velho" de "acesso perdido" em segundos. Quando o custo de verificar é esse, verifique antes de aceitar o "é assim mesmo".

---

## Reconciliação da parceria Meta 2026-08-20 (F129, F130 + adendo ao F128)

> **Gatilho:** o mesmo do F128 — a Petrolina fora da parceria e viva no MCP. O F128 fechou o **sintoma** com um contador de ausências. Perguntado *"e para que ela saia sozinha quando a parceria acabar?"*, o desenho mudou de **inferir** para **consultar**: reconciliar contra `client_ad_accounts ∪ owned_ad_accounts` do BM da V4. PR [#21](https://github.com/BadWolf1509/v4-ads-mcp/pull/21), 21 commits, revisão `00071-q4v`, migration `006`.

### Adendo ao F128 — o fix foi superado no mesmo dia, de propósito

O contador de ausências continua existindo, mas **mudou de fonte**: deixou de contar ausência em `/me/adaccounts` e passou a contar ausência **na parceria**. `bump_missing` e `MISSED_SYNCS_THRESHOLD` foram removidos; a decisão migrou para `build_plan()`, que é puro, e a persistência virou `apply_absences`/`deactivate`. A seção *Fora do alcance do system user* do painel foi substituída por **três filas**, porque uma seção só não distinguia três ações diferentes. Manter as duas semânticas seria estado duplicado com sentidos divergentes — que é o teste nº 2 do `Padrão de solução` do CLAUDE.md.

**A lição do F128 que sobrevive intacta, e agora com fix:** *desativar não revoga*. Era verdade porque `can_manager_access` lia só a tabela de grants. Passou a exigir conta ativa **e** grant não revogado.

- **F129 (MED, ABERTO — ação humana) — o system user tem permissão três níveis acima do uso, e o token não expira.** Medido em 2026-08-20 via `assigned_users`: o SU `v4-ads-mcp-integracao` carrega `["DRAFT","ANALYZE","ADVERTISE","MANAGE"]` — *Ad Account Admin*, que pela doc da Meta "can manage all aspects of campaigns, reporting, billing and account permissions". As **6 tools Meta são todas de leitura**. O papel que corresponde ao uso real é `['ANALYZE']` (*"can see ad performance"*). Hoje, a única coisa que impede o MCP de alterar campanha de cliente é **não termos escrito a tool** — o que é uma coincidência, não um controle. Somam-se dois agravantes de mesma família: o token é **permanente** (a doc mostra que expiração em 60 dias é opção, com refresh suportado por `oauth/access_token`), logo um vazamento vale para sempre; e `business_users` do BM devolve **uma** pessoa, então há um único caminho de administração do SU.
  **Por que não foi corrigido aqui:** não é código — é configuração no Business Manager e geração de token, ação do gestor. Reduzir para `ANALYZE` deve ser testado em **uma** conta antes das 25.
  **Controle compensatório que existe:** na Meta toda ação aparece como `v4-ads-mcp-integracao`; a autoria real só existe no `audit_log` do MCP, que grava `manager_id` por chamada. No dia em que entrar a primeira tool de **escrita** Meta, esse log deixa de ser conveniência e vira requisito de governança.

- **F130 (MED) — o gate do Google não consulta `is_active`, o mesmo buraco que o do Meta acabou de perder.** [`manager_account_access.can_manager_access`](../../src/db/repositories/manager_account_access.py) lê só a tabela de grants: sem join com `google_ads_accounts`, sem checagem de estado. Conta desativada no inventário segue acessível a quem tiver grant. **Deliberadamente fora do escopo de 20/08:** no Google não existe "parceria de BM" — a fonte autoritativa é o `customer_client` do MCC —, então o desenho da reconciliação Meta não se transplanta, e misturar as duas frentes aumentaria o raio sem melhorar nenhuma. Family: mesma do F128/F57 (gate que não alcança todos os estados).

  **✅ CORRIGIDO (2026-09-05, branch `feat/gate-google`, commits `d4275ea`/`9eda30d`/`840676c` + a revisão final `00875ee`/`4c1f412`/`f88bfe3`/`8e26c85`).** `can_manager_access` ganhou `JOIN google_ads_accounts` + `is_active = true`, mesmo par de condições que o Meta já tinha. Junto (mesma branch, migration `008`): revogação virou soft (`revoked_at`/`revoked_reason`, em vez de `DELETE`), com restauração restrita ao que saiu por churn (`left_mcc`) — revogação de admin (`admin_revoked`) não volta sozinha. A revisão final fechou quatro reincidências da MESMA classe que o merge teria deixado passar: numerador de `/admin/access/by-manager` contando grant vivo em conta inativa (universo diferente do denominador), mensagem de negação recomendando o painel quando a causa era a conta ter saído do MCC (conselho que não funciona), `copy_access` sem guard `origem == destino` (aniquilava o gestor), e um guard AST que ficava verde em 3 das 13 variantes de sabotagem geradas na revisão (inverter o valor, trocar `AND` por `OR`, neutralizar com `OR TRUE` — as três só morriam nos testes de integração, nunca no gate local sem Docker).
  **Deliberadamente fora, sprint seguinte:** não há reconciliação automática (nenhum job compara o inventário contra o `customer_client` do MCC), não há fila equivalente às três do painel Meta, não há alerta, e `revoke_for_inactive_accounts` — a função que revogaria em massa o grant vivo em conta que já saiu do MCC — **não tem chamador em produção**; hoje só roda se alguém a invocar manualmente ou via teste. `count_grants_on_inactive_accounts` (leitura, pensada pro dry-run desse job futuro) está viva e também sem consumidor.

### Dívida deliberada que sobrou (verificada no código em 20/08, não copiada de lista)

Nada disto bloqueou o merge; está aqui porque foi **decidido**, não esquecido — e porque o ledger da execução, onde vivia, é scratch e foi descartado.

- **`mark_inactive_except` do Meta virou código morto.** A reconciliação usa `deactivate` (que trata lista vazia como no-op, ao contrário dela). O **homônimo do Google segue vivo e em uso** (`account_resync.py:118`) — não confundir os dois ao limpar.
- **O guard do gate ainda passa com comentário de bloco `/* */` e com `CROSS JOIN` sem `ON`.** Ele tira só comentário de linha (`--`). Residual conhecido: fechar exige `re.sub(r"/\*.*?\*/")` e rejeitar `CROSS`/`NATURAL` no conjunto de palavras precedentes.
- **A fila "Saíram da parceria" não tem afordância de dispensa:** conta re-delegada pela matriz continua listada. Cosmético e visível — o admin vê a conta, não perde ação.
- **As filas 2 e 3 podem se sobrepor** (conta que voltou e ainda está sem o SU). Aqui a sobreposição é **correta**, ao contrário do caso 1-vs-2 que foi eliminado: as duas ações são reais e independentes — atribuir o SU e restaurar acessos.
- **A rota de restore devolve `conta_inativa` também para id inexistente**, e tem TOCTOU sem transação. Rota de admin autenticado, sem enumeração útil; o TOCTOU exigiria dois admins no mesmo segundo na mesma conta.
- **`build_plan(threshold=3)` e o limiar exato do guard percentual** seguem sem calibração com dado real — o soak é quem responde.

### O que a execução ensinou (método, não bug)

Oito tarefas com implementador e revisor independentes, mais revisão da branch inteira. **Os achados mais graves foram defeitos do PLANO, não da implementação** — vale registrar porque contraria a intuição de que o risco mora no código:

1. **Renomeei `resync_meta` → `reconcile_meta` sem varrer os callers.** `src/jobs/account_resync.py` a importava direto no caminho de **piggyback de produção**: o próximo Cloud Run Job teria quebrado com `ImportError`. É o **F57 pela terceira vez na mesma sessão** — e desta vez o autor da lista incompleta fui eu.
2. **Código de teste que não compila.** `with (*ps, X as n):` é `SyntaxError` em Python; misturar desempacotamento com `as` num `with` parentizado não existe.
3. **`upsert_many` antes de `list_inventory_rows`.** Como o upsert marca tudo ativo e zera o contador, `to_add` saía **vazio por construção** e o audit gravaria `added: 0` para sempre — justamente um dos números que o soak existe para observar. **Nenhum teste pegava, porque `upsert_many` está mockado em todos.** Só uma asserção de **ordem de chamada** fixa isso.
4. **Duas falhas de costura que só a revisão da branch inteira viu:** o botão *Restaurar* ficava inalcançável exatamente quando a parceria voltava (a fila keyava em `is_active=false`, e o retorno reativa a conta), e `su_reachable` nunca era escrito durante o soak (estava atrás da trava destrutiva), deixando a fila "sem SU" vazia para sempre. Desta saiu o princípio: **a trava governa destruição, não observação.**
5. **A varredura de leitores de grant foi errada três vezes, em ordem crescente de acerto:** eu enumerei 4 "completos", o implementador varreu e achou 7, o reviewer varreu com `grep` e achou **10** — e o erro estrutural foi meu: eu procurei *leitores*, e a revogação soft mudou também os *escritores* (`copy_access` ressuscitava grant revogado como vivo, alcançável em um clique).
6. **Guard que passa não é guard que cobre, 5ª e 6ª ocorrências.** O guard do gate passava verde com `LEFT OUTER JOIN` (a blocklist casava só o bigrama exato) e com um comentário SQL `--` dentro do literal (ele tirava comentário do *Python*, não do *SQL*). O re-reviewer não leu o guard: **executou a lógica dele** contra 7 variantes. Lição operacional: para guard baseado em texto, afirme a **forma** (`\bJOIN\s+tabela` sem `LEFT/RIGHT/FULL/OUTER` antes), nunca uma lista de grafias proibidas.
## Gaps de campo trazidos pela gestão de tráfego MO-JP 2026-09-02 (F131-F135)

> **Gatilho:** a sessão de gestão de tráfego da MO João Pessoa (`jo-o-pessoa-db`) executou um passe grande na conta `786-223-0676` — 20 RSAs, 4 keywords, 6 vínculos de callout — e bateu em cinco limitações do MCP. Esta seção registra os **cinco defeitos** que a verificação confirmou. Os três **gaps de feature** do mesmo pacote estão no fim, fora da numeração: ausência de tool não é bug, e inflar o catálogo com roadmap estraga a busca dirigida que ele existe para servir.
>
> **Método:** leitura do código, enum autoritativo lido do SDK instalado, e probe empírica por `validate_gaql`/`run_gaql`/`get_change_history` contra a própria conta. Inclui **probe de controle** — `'BANANA_ASSET'` volta com `Invalid enum value cannot be included in WHERE clause`, e é isso que dá valor aos `valid: true`. Sem a recusa do controle, nenhum deles provaria nada.
>
> **Cinco afirmações caíram na verificação e estão corrigidas abaixo** — três minhas, duas do campo, incluindo a **premissa que motivou o pedido original**. Registradas em vez de apagadas, porque o valor está no modo de errar, e cada modo se repete: **medição pontual generalizada como regime** (F131), **defeito inferido da leitura de uma função sem checar quem a consome** (F134), **cegueira inferida de acoplamento não verificado** (F135, espelho exato do anterior — um leu a função e supôs o consumo, o outro leu a dependência e supôs o consumidor), **contagem tratada como prova de estado** (smoke do unlink) e **custo lido como veredito sem a conversão ao lado** (`ad_schedule`, que é o F133 recorrendo dentro de um desenho nosso). As cinco davam entrada de catálogo plausível e errada. O que as separou não foi releitura: foi rodar a coisa contra a fonte autoritativa, com controle.
>
> **Os cinco fechados no commit `38d890c`** (F131-F135), com guards verificados por sabotagem. O bloco de fechamento vem depois do F135, junto do **F136**, que nasceu da varredura dos consumidores e segue **aberto** por ser decisão de produto.

- **F131 (HIGH, ABERTO) — `get_change_history` e `detect_drift` não dizem até quando a fonte está indexada, então "zero drift" e "ainda não indexou" são respostas byte-a-byte idênticas.** O F46 tratou a *query* (`BETWEEN` com end_date midnight-exclusive, fechado em 3b.34 pelo `_format_change_date_between`). **Isto é upstream dela:** o lag de indexação do próprio `change_event` do Google.
  **⚠️ CORREÇÃO (mesma sessão, antes de qualquer fix) — a primeira versão desta entrada dizia "~2 dias de atraso, ao vivo". Era medição pontual dentro da janela, generalizada como regime.** O que os dois lados mediram na `786-223-0676` em 02/09: writes às **11:28–11:43**; consulta do campo ~**11:50** → **zero**; minha sonda logo depois → fronteira em **31/08 10:52**; re-medição no fim da tarde → **30 linhas, reconciliando item a item** (20 `AD` + 4 `AD_GROUP_CRITERION` via API, 4 `CAMPAIGN_ASSET` + 2 `CUSTOMER_ASSET` via web; `REMOVE 6`/`UPDATE 24`). A janela real de hoje foi de **~3-4 horas**. O `>4 dias` do registro de campo (dogfood 25/05) segue valendo como o **outro extremo**.
  **A correção fortalece o fix em vez de enfraquecê-lo, e troca a justificativa:** lag fixo se resolve com nota na description; o que está medido é **~3h a >4 dias na mesma conta, sem contrato**. É *por ser imprevisível* que a fronteira precisa ser **medida a cada chamada**, não documentada. **Por que é grave:** `detect_drift` é tool de segurança e roda inteiramente sobre essa fonte — pode responder "zero drift" numa conta que um terceiro acabou de mexer. 16ª variante da silent-acceptance, com o silêncio vindo de fora da nossa query.
  **Desenho acordado com o campo — duas fronteiras, não uma:** (1) **fronteira da conta**, sonda não-filtrada em `asyncio.gather` com a query principal (padrão que o `audit_competitor_keywords` já usa), `ORDER BY change_event.change_date_time DESC LIMIT 1` — o `LIMIT` é **obrigatório**, o Google recusa `change_event` sem ele. Vai **sem os filtros do usuário**: herdar `resource_types` reproduziria a cegueira que ela mede. (2) **fronteira do recorte**, `max(change_date_time)` **das linhas que a query principal já devolveu** — custo **zero** de quota, o dado já está na resposta. As duas juntas tornam distinguíveis os três estados: conta fresca + recorte com linhas = confiável; conta fresca + recorte vazio = **ambíguo, e declarado ambíguo**; conta atrasada = nada confiável. Isso resolve o trade-off que a fronteira única deixava aberto — o lado caro sai de graça.

- **F132 (LOW, ABERTO) — as duas descriptions prometem uma magnitude de lag que não existe, e se contradizem.** [`detect_drift.py:124`](../../src/mcp/tools/detect_drift.py) diz `"change_event tem lag até HORAS"`; [`get_change_history.py:269`](../../src/mcp/tools/get_change_history.py) — a tool que ele chama — diz `"latency de indexacao pode chegar a DIAS (>4 dias ja visto em producao)"`, e o módulo repete no docstring (linhas 16-19). Quem calibrar confiança pelo `detect_drift` calibra pelo número errado, e foi o que aconteceu no campo. **Mas o fix não é alinhar uma na outra:** à luz do F131, **as duas estão erradas do mesmo jeito** — afirmam número onde não há contrato. Nenhuma deve prometer magnitude; ambas devem dizer *lag variável e não contratual, e a resposta traz a fronteira medida*. Family: doc que descreve um sistema que não é o que roda.

- **F133 (HIGH, ABERTO) — `audit_competitor_keywords` chama gasto de `wasted` e sugere negativar sem nunca ler conversão.** [`queries/audit_competitor_keywords.py:42`](../../src/google_ads/queries/audit_competitor_keywords.py) seleciona `metrics.impressions, metrics.clicks, metrics.cost_micros` — e só. A palavra `conversions` não aparece em nenhum dos dois arquivos da tool. Mesmo assim o `summary` publica `total_cost_wasted_brl` e a tool emite `suggested_negatives` (EXACT + PHRASE por brand). **Evidência de campo:** na `786-223-0676` o termo de concorrente é o **melhor CPA da conta** — 90 dias, R$ 155,25, 9,00 conversões, **CPA R$ 17,25**. Aplicar a sugestão automática mataria o ativo mais eficiente. **Probe:** `metrics.conversions, metrics.conversions_value` em `search_term_view` → válido; mesma tabela que a query já visita, então o fix é uma linha de `SELECT`.
  **Decisão de desenho — sinalizar, não suprimir.** `suggested_negatives` é emitido **por brand agregada**, não por termo ([`competitor_analysis.py:181`](../../src/google_ads/competitor_analysis.py)), então "não sugerir o termo que converteu" não tem onde encaixar; e suprimir a brand que converteu faria a tool ficar muda **exatamente quando o termo é valioso** — 17ª variante da silent-acceptance, trocando um defeito por outro da mesma família. Razão do campo, mais forte que a minha: **a tool não tem ERP.** A regra de operação é que negativar exige cross-check de catálogo, e o ERP derruba a maioria das propostas (4 de 5, 5 de 7, 6 de 8 nas últimas rodadas). Tool sem ERP nunca deveria **decidir**, só instruir — e suprimir é decidir. O desenho é *recomendação com contra-evidência acoplada*.
  **Gatilho: `conversions > 0`, não CPA-relativo** — decidido pelo campo, contra a minha suposição de que o CPA seria melhor critério. Três razões: (a) a "média da conta" não existe como número honesto — os ~R$ 20 misturam brand e non-brand, GERAL e dedicado, JP e CAB, BROAD e EXACT; o `17,25 × 20` foi **argumento retórico**, não critério mecânico, e codificar retórica é erro; (b) CPA-relativo **mente com n pequeno** — termo com 1 conversão e CPA R$ 8 dispararia "ótimo", contra a regra de campo de que 2 conversões são sinal e não veredito; (c) **o flag é o freio, não o veredito** — a função é fazer o gestor abrir o ERP. Ruído é baixo nesta conta porque `search_term_view` subdeclara (cobertura ~47-51% do custo; em BROAD, **8%**). Se incomodar em conta de mais volume, ordenar por conversões desc — **não** subir o gatilho.
  **Campos:** `conversions` estruturado no `SuggestedNegative` (sem ele as skills `v4-trafego` parseariam prosa) + `conversions`/`conversions_value_brl` por search term. **`cost_brl` por termo já existe** no output de hoje — o campo pediu e já está lá; o que falta para fechar CPA sem segunda query é só a conversão ao lado. **Fora do escopo por decisão do Wellington:** `total_cost_wasted_brl` **mantém o nome** (renomear quebraria consumidor em produção, inclusive as skills `v4-trafego`); o desmentido vai na linha de baixo, com `total_conversions` no mesmo `summary`. **Generaliza para todo campo cujo nome embute julgamento** — `wasted`, `zombie`, `problemas`: mesmo movimento do F52/F90. **E recorreu nesta mesma sessao, no eixo do tempo, dentro de um desenho nosso:** o dry-run do `ad_schedule` ia mostrar `% de custo historico` das janelas cortadas, e foi esse numero que quase transformou o melhor CPA da conta em desperdicio. Ver o bullet do `ad_schedule` abaixo — a regra generaliza para qualquer superficie que apresente custo como candidato a corte.

- **F134 (LOW, ABERTO — reclassificado de MED) — `customerAssets` falta em `_RESOURCE_PLURAL_TO_TYPE`, mas é dívida latente, não defeito vivo.** [`queries/_common.py:152`](../../src/google_ads/queries/_common.py) tem `campaignAssets` e `adGroupAssets` e **não** tem `customerAssets`, apesar do docstring do módulo pedir que a lista acompanhe os tipos que o `change_event` emite.
  **⚠️ CORREÇÃO (mesma sessão) — a primeira versão desta entrada dizia que um change de `customer_asset` "sairia como `(None, id)`, tipo desconhecido e calado", implicando defeito vivo. Falso: o tipo devolvido é descartado nos três call sites** — [`get_change_history.py:160`](../../src/mcp/tools/get_change_history.py) faz `_rtype, rid = parse_resource_path(...)`, e as linhas 167-168 e [`get_negative_keywords_audit.py:65`](../../src/mcp/tools/get_negative_keywords_audit.py) usam `_`. O `resource_type` do output vem do **campo enum** `change_event.change_resource_type`, não do parser; e o `id` sai correto pelo fallback. Verificado no output real: as 2 linhas `CUSTOMER_ASSET` de 02/09 vieram com tipo e `resource_id` certos e `campaign_id`/`ad_group_id` nulos, que é o correto. **Eu inferi o defeito lendo a função e não o consumo dela.** O que sobra é real e menor: a lista está incompleta e nada obriga a completá-la, então o dia em que alguém consumir o tipo devolvido é o dia em que isso vira bug. **Cross-ref:** o buraco que o campo achou nos assets é o do **enum de entrada** — F135 —, não o do parser.

- **F135 (HIGH, ABERTO) — `_RESOURCE_TYPES` do `get_change_history` diverge do enum do Google nas DUAS direções: 10 valores que a API tem e nós não oferecemos, 3 que oferecemos e a API rejeita.** Descoberto pelo campo pelo caso mais caro: **`get_change_history(TODAY, resource_types=["AD_GROUP_AD"])` → `total_changes: 0`, com 20 linhas `AD` no mesmo dia**. Reproduzido pela tool, não por GAQL cru. Editar RSA emite `AD`; `AD_GROUP_AD` é o único enum de anúncio que a tool oferece — então a pergunta "mexeram nos meus anúncios?", feita pelo caminho que a tool oferece, devolve **zero com 20 edições no período**.
  **Enum autoritativo** (`ChangeEventResourceTypeEnum.ChangeEventResourceType`, SDK v24 instalado): **19** valores fora de `UNSPECIFIED`/`UNKNOWN`. Nossa lista tem 12. **Faltam 10** — `AD`, `CUSTOMER_ASSET`, `AD_GROUP_BID_MODIFIER`, `AD_GROUP_FEED`, `ASSET_SET`, `ASSET_SET_ASSET`, `CAMPAIGN_ASSET_SET`, `CAMPAIGN_FEED`, `FEED`, `FEED_ITEM`. **Sobram 3 fantasmas** — `BIDDING_STRATEGY`, `CONVERSION_ACTION`, `CUSTOMER_NEGATIVE_CRITERION`: não existem no enum, e os três foram probados devolvendo `Invalid enum value cannot be included in WHERE clause`. **As duas direções falham diferente:** o que falta some em **silêncio** (`total_changes: 0`), o que sobra falha **alto** (erro). O silêncio é o caro — e `AD` é a mudança mais comum numa conta de Search.
  **⚠️ Uma inferência do campo NÃO se confirmou, e é a que mais assustava:** *"se `detect_drift` compartilha essa lista, ele é cego para reescrita de anúncio por terceiro"*. **Não é.** [`detect_drift.py:149`](../../src/mcp/tools/detect_drift.py) chama `get_change_history` com `customer_id`, `start_date`, `end_date` e `limit` — **sem `resource_types`**. Sem filtro, a query não toca o enum e as 20 linhas `AD` entram normalmente; confirmado no output de 02/09. O `detect_drift` **enxerga** reescrita de anúncio. O F135 atinge quem **filtra** — e o `detect_drift` não filtra. Cegueira por acoplamento é hipótese barata de levantar e barata de testar; vale testar antes de escrever.
  **Fix (proposto pelo campo, adotado):** derivar `_RESOURCE_TYPES` do enum do SDK em vez de manter lista à mão, com **guard que falhe quando a API ganhar valor novo** — senão isto repete no próximo tipo. **É o guard que fecha o achado:** a lista à mão divergiu em 13 posições sem nada cruzando as duas fontes, que é a mesma forma do F86 → F109.

### ✅ Os cinco fechados no commit `38d890c` — e o que ficou de fora

**F131.** `freshness` na resposta das duas tools, com `account_frontier` (sonda propria em `asyncio.gather` com a query principal), `slice_frontier` (`max` das linhas ja devolvidas, custo zero) e `status` ∈ {`confiavel`, `ambiguo`, `atrasado`, `indeterminado`}. Logica pura em [`change_freshness.py`](../../src/google_ads/change_freshness.py); sonda em `change_event_frontier_query`. Sonda vazia devolve `indeterminado`, nunca frescor. **Custo aceito:** +1 chamada de quota por invocacao. **Fora de escopo deliberado:** cache da fronteira por `customer_id` — `detect_drift` roda ~1×/dia em D+1/D+2, nao em loop, e nao vale trocar correcao por economia antes de haver pressao real de quota.

**F132.** As duas descriptions pararam de prometer magnitude. **O fix nao foi alinhar uma na outra** — seria escolher qual numero errado manter. As duas apontam para o `freshness` medido, e o `detect_drift` diz explicitamente que *zero drift com `status != confiavel` NAO significa conta intacta*.

**F133.** `metrics.conversions` + `metrics.conversions_value` no `SELECT`; `conversions`/`conversions_value_brl` por search term; `conversions` **estruturado** no `SuggestedNegative`, agregado por brand; `total_conversions` no `summary`; `reason` mostra o CPA quando houve conversao; aviso na description no padrao F52/F90. **`conversions_value` e double no proto, NAO micros** — probado, e nao passa por `micros_to_currency` como o `cost_micros` da linha de cima. **Escolha que vale registrar:** os campos novos sao **obrigatorios** na dataclass, sem default `0.0`. Default silencioso ali seria o proprio modo de falha do F133 reintroduzido — parser que esquecesse o campo reportaria "nao converteu". O default vive no helper de teste, onde e inofensivo.

**F134.** `customerAssets` no mapa. Uma linha, sem efeito funcional hoje.

**F135.** `_RESOURCE_TYPES` com os 19 valores do enum. **Divergi do que esta escrito acima e do que o campo propos:** a producao **nao** deriva do SDK em runtime. O schema de uma tool MCP e contrato publico, e derivar faria um bump do lockfile mudar os valores aceitos pelo gestor sem diff, sem revisao e sem linha de catalogo — trocaria divergencia silenciosa por mudanca silenciosa de contrato. Alem disso cravaria versao de API num import do caminho que atende request (o `src/` inteiro fala com o SDK por `client.get_type()`; seguir a versao exigiria `client._DEFAULT_VERSION`, privado, e um upgrade derrubaria o servidor no import). **A fonte autoritativa continua sendo o SDK; o reconciliador e o guard no CI**, que le o enum ao vivo, falha nas duas direcoes e tem tripwire separado para upgrade de SDK.

**Guards verificados por sabotagem, nao por terem passado** (ver [`memoria de guards que nao cobrem`](../operacao/findings-catalog.md)): remover `AD` do enum derruba 2 testes; fazer a sonda herdar `resource_types` derruba o teste da invariante; suprimir a brand que converteu derruba o anti-teste da supressao. Os testes que **nao** falham contra o codigo pre-fix estao marcados como *guard de fiacao* nas proprias docstrings, em vez de contados como cobertura.

**Limite declarado:** o full sweep com Docker **nao rodou** (Docker indisponivel na maquina); os testes de integracao com DB validam no CI.

- **F136 (MED, ABERTO) — `detect_drift` promete vigiar remocao de conversion action, e nao consegue ver nenhuma.** Achado ao varrer os consumidores dos 3 valores fantasma do F135. [`drift_detection.py:18`](../../src/google_ads/drift_detection.py) tem `_STRUCTURAL_RESOURCE_TYPES = frozenset({"CAMPAIGN", "AD_GROUP", "CONVERSION_ACTION"})`, e a flag `structural_change` (severity **high**) so dispara com `operation == "REMOVE"` e `resource_type` nesse conjunto. Mas **`CONVERSION_ACTION` nao existe em `ChangeEventResourceType`** — ausente do enum do SDK e rejeitado pela API em `WHERE` (as duas confirmacoes sao independentes). Logo o terceiro membro e **codigo morto**: a flag so pode disparar em `CAMPAIGN` e `AD_GROUP`, enquanto o docstring do modulo e a `message_pt` entregue ao gestor dizem *"CAMPAIGN/AD_GROUP/CONVERSION_ACTION"*. Remover uma conversion action quebra Smart Bidding — e das mudancas mais caras que um terceiro pode fazer —, e o gestor acredita estar coberto. Familia: a mesma do F135 e do F128 — lista mantida a mao assumindo superficie de API que nao existe.
  **✅ CORRIGIDO (2026-09-02, commit a seguir).** O fix **nao** foi so apagar o membro: apagar sozinho deixaria o codigo honesto e a cobertura **pior, calada** — o gestor seguiria achando que esta coberto, agora sem nem o vestigio no codigo para alguem notar. **Antes de decidir foi verificado se havia caminho de cobertura, e nao ha:** `change_status`, o recurso irmao do `change_event`, tem **21 tipos e tambem nao inclui `CONVERSION_ACTION`** — nenhum dos dois recursos de rastreamento de mudanca da API enxerga conversion action. Cobertura real exigiria snapshot proprio + diff, que e feature separada e nao fix. Entao: membro morto removido, `message_pt` corrigida, e **o limite passou a ser declarado na description da tool**, dizendo que remocao de conversion action nao aparece ali e apontando `get_conversion_actions` para o estado. Mesma forma do F131 (fronteira medida em vez de silencio) e do F132 (nenhuma magnitude prometida): parar de fingir e dizer o que da para saber.
  **O guard cuida da CLASSE, nao do valor:** [`test_drift_structural_scope.py`](../../tests/unit/test_drift_structural_scope.py) cruza **todo** membro do conjunto com o enum autoritativo do SDK, entao qualquer tipo estrutural que a API nao emita derruba o teste — inclusive um que alguem adicione de boa-fe no futuro, que foi exatamente como o `CONVERSION_ACTION` entrou. Verificado por sabotagem com um fantasma **diferente** do original (`BIDDING_STRATEGY`), nao por ter passado.

### Gaps de feature do mesmo pacote (fora da numeração — ausência de tool não é bug)

Vão para spec própria, revisada antes de virar sprint. Registrados aqui só para não se perderem entre o relato de campo e o roadmap. As decisões abaixo são do campo, que opera a conta.

- **Sem tool de `ad_schedule` — decidido: leitura + escrita.** Zero ocorrências fora da `.venv`. Leitura probada: `campaign_criterion.ad_schedule.{day_of_week,start_hour,end_hour}` + `campaign_criterion.bid_modifier` → válido. **A escrita entra porque a UI já falhou em silêncio duas vezes nessa conta** — orçamento compartilhado em 17/08 (aceito 7×, exibido na tabela, nada persistiu) e os callouts de 02/09, que precisaram de duas tentativas e só apareceram porque o campo conferiu por GAQL. Um `ad_schedule` que não persiste em silêncio deixa a conta servindo com loja fechada sem ninguém saber, e ainda queima 14 dias de re-learning quando refeito.
  **⚠️ CORREÇÃO — o caso que motivou o pedido está invertido, e a inversão foi verificada de forma independente.** A versão anterior desta entrada dizia: as lojas fecham fim de semana, as campanhas gastam **16,6%** do orçamento nesses dias (R$ 795,72 de R$ 4.806,05 em 01–16/08), logo cortar economiza ~R$ 1.600/mês. **O campo remediu numa janela madura (19/08–01/09, pós-geo e pós-portfólio) e o fim de semana é o gasto MAIS EFICIENTE da conta.** Reproduzido aqui do zero, por `segments.day_of_week`, batendo em todas as casas:

  | | custo | conversões | **CPA** | CPC |
  |---|---|---|---|---|
  | **fim de semana** | R$ 645,86 | 34,75 | **R$ 18,59** | R$ 4,17 |
  | seg–sex | R$ 3.909,57 | 165,75 | **R$ 23,59** | R$ 7,01 |

  CPA do fim de semana é **78,8%** do de seg–sex; CPC, 60%. Por dia: **domingo R$ 14,14** é o melhor da conta e **terça R$ 25,05** o pior — ou seja, o dia que se ia cortar é melhor que todos os que ficariam. Share caiu de 16,6% para **14,2%** na janela nova. Replica nas duas campanhas (JPA 18,65 × 24,00 · CAB 17,92 × 20,78), então não é artefato de praça. **Ressalvas do próprio campo, que valem manter:** n = 34,75 conversões em 14 dias é sinal robusto e não veredito fino; `metrics.conversions` conta o que entra na métrica "Conversões" e ainda não foi cruzado com as primárias; e a janela está dentro do re-learning do portfólio. A premissa de **negócio** (loja fechada) continua verdadeira; o que caiu é a inferência de que gasto em loja fechada é desperdício — o lead entra no fim de semana e é atendido depois.
  🔴 **A inversão muda o desenho, não só o caso: `% de custo histórico` é o número ERRADO para o dry-run.** Foi exatamente ele que quase transformou o melhor CPA da conta em corte. **É o F133 outra vez — custo apresentado como candidato a corte sem a conversão ao lado — agora no eixo do tempo, e dentro de um desenho nosso.** Fica como regra da tool, não como observação: para as janelas que **deixam** de servir, o dry-run mostra **custo, conversões e CPA**; e mostra o **CPA das janelas que permanecem**, lado a lado. A pergunta que o preview tem que responder é *"o que estou desligando é melhor ou pior do que o que fica?"* — custo sozinho não responde.
  🔴 **Guarda obrigatória de desenho: `ad_schedule` é CONJUNTO, não incremento.** O criterion define as janelas em que a campanha serve, e **o que fica fora para de servir** — mesma semântica de "substitui a lista inteira" do `update_rsa`. Quem adicionar "seg–sex 07–17" achando que soma a uma grade existente **desliga a conta no resto**.
  🔴 **Com orçamento compartilhado, desligar janela não economiza — REALOCA.** A verba volta no mesmo dia pelas janelas que seguem servindo, então o efeito real do corte proposto seria mover gasto de CPA R$ 18,59 para CPA R$ 23,59: não é neutro, é negativo. **Não é hipótese nesta conta** — `campaign_budget.explicitly_shared` é `true` nos dois orçamentos ENABLED, e o ativo é o portfólio JPA+CAB a R$ 310/dia (verificado 02/09). O campo é válido em GAQL e barato de ler, então o dry-run deve **detectar e declarar** isso em vez de deixar o operador supor economia.
  **Conjunta dia × hora deliberadamente NÃO levantada:** a copy nova entrou em 02/09 e o portfólio acabou de sair do re-learning, então medir agora entregaria dado velho para a decisão. As marginais acima bastam para desenhar o formato; a conjunta se levanta na hora de codar, com a janela madura. **Consequência operacional que sai do escopo desta seção e é do campo:** o ajuste agendado para depois de 16/09 precisa ser reavaliado antes de executado — a tool que o faria continua justificada, o corte específico não.
- **Sem tool de leitura de assets — decidido: todos os `field_type`, precedência calculada.** `get_assets(customer_id, field_type?)` devolvendo `customer_asset` + `campaign_asset` + `ad_group_asset` juntos. **Todos os tipos**, com `field_type` opcional e sem filtro no default: limitar à família text-extension que o `create_and_link_assets` cobre repetiria o erro do checklist de 02/09, que previu uma camada quando existiam duas. ~~**Precedência como campo calculado** (`effective`, `shadowed_by`)~~ — **caiu na probe de 02/09.** O conceito não existe na API: `AssetLinkPrimaryStatusReason` tem seis valores e nenhum é de precedência, e dois vínculos coexistentes do mesmo asset voltam ambos `primary_status: ELIGIBLE`. O campo certo já existe e é melhor — `primary_status` + `primary_status_reasons`, veredito do próprio Google, que ainda cobre reprovação, revisão pendente e `LIMITED`. Detalhe na spec [`2026-09-02-ad-schedule-e-assets-design.md`](../superpowers/specs/2026-09-02-ad-schedule-e-assets-design.md) §5.1. **`status` por linha e sem filtrar status no default.** **Bônus pedido:** marcar assets **sem nenhum vínculo** (órfãos) — inventário sem gesto destrutivo.
- **Sem tool de remover/desvincular asset — decidido: só unlink.** `create_and_link_assets` existe, o inverso não; custou duas idas à UI. `remove_audience.py` é o formato precedente. **Não remover a entidade `Asset`:** o que serve na SERP é o vínculo, asset órfão é inerte, e remover é irreversível numa entidade que pode estar linkada onde a varredura não alcançou — o registro tem caso de "órfão" que era ativo vivo. Com órfãos visíveis no `get_assets`, o lixo fica auditável sem tool destrutiva.
  🔴 **Restrição obrigatória no smoke desta tool — só a asserção por id + status é incondicional.** Confirmar remoção **contando linhas não distingue os dois estados**, e a reprodução de campo mostra por quê: o vínculo removido **continua na tabela** com `status: REMOVED`, então a lista completa tem o mesmo tamanho antes e depois. Medido na `786-223-0676` em 02/09 (assets `144113768040` e `144113768046`, CALLOUT), comparando o momento em que a remoção **falhou** com o momento em que **funcionou**:

  | forma de checar | falha | sucesso | distingue? |
  |---|---|---|---|
  | `row_count` da query **não-filtrada** | 16 | **16** | ❌ nunca — o `REMOVED` continua contando |
  | `row_count` filtrado por `status = 'ENABLED'` | 16 | 12 | ⚠️ só com baseline conhecido |
  | `status` consultado **por `asset.id` alvo** | `ENABLED` | `REMOVED` | ✅ sempre |

  A linha do meio foi o que salvou a operação no dia (16 onde se esperavam 12), mas depende de saber o número esperado. A de cima é a armadilha. E nenhuma das duas cobre **remoção parcial**: tirar 2 de 4 devolve 14, que passa por "mudou, deve ter dado certo". Portanto: asserte **`status == REMOVED` no registro alvo**, nunca `id not in lista_enabled` e nunca `row_count`. Query de referência: `FROM campaign_asset WHERE campaign_asset.field_type = 'CALLOUT' AND asset.id IN (...)` — devolveu 4 linhas `ENABLED` no estado de falha (prova positiva sem baseline) e `REMOVED` no de sucesso. **Segundo caso, de graça, que cobre a hierarquia do `get_assets`:** no mesmo dia os `customer_asset` do par continuavam `ENABLED` depois de os `campaign_asset` já terem sido removidos — invisíveis a qualquer check que só olhasse campanha. **⚠️ A palavra "dormentes", que estava aqui, caiu na probe de 02/09:** nada do que a API expõe sustenta que vínculo de conta fique inerte por haver vínculo de campanha, e o `primary_status` dos dois coexistentes é `ELIGIBLE`. O que segue de pé é o essencial — eles existiam, eram invisíveis, e eram 6 remoções e não 4. Greppei `docs/`, `src/` e `tests/` por `asset.status = 'ENABLED'`: vazio, então **não há falso-positivo vivo hoje**.

### O que a sessão de campo propôs NÃO fazer, e por quê (registrado para não voltar à fila)

- **Tool de geo targeting write:** o gap que dói é da plataforma — o Google Ads não exclui por raio — e a frequência é ~1×/mês.
- **`remove_keyword` / `remove_ad_group` / `remove_campaign`:** as descriptions já dizem "se demanda real surgir", e não surgiu. `PAUSED` resolve, e a fricção da UI é saudável para operação irreversível.

## Pipeline: CVEs invisíveis e deploy por commit de docs 2026-09-02 (F137, F138)

> **Gatilho:** o push dos 4 commits de catálogo (`3e78e12..92bc5dd`) disparou o CI, que passou **e deployou produção**. A sessão de campo foi conferir se o run tinha passado mesmo e esbarrou numa annotation vermelha num run verde. Os dois achados saem daí.

- **F137 (HIGH) — o CI reportava 4 CVEs em produção e ninguém via, porque o passo era `continue-on-error`.** Confirmado no log do run `33649564502`, não no relato: `Found 4 known vulnerabilities in 2 packages` — `aiohttp 3.14.1` com **PYSEC-2026-3545/3546/3547** e `cryptography 49.0.0` com **PYSEC-2026-3552**, todas com correção publicada. O servidor guarda credenciais de Google Ads e Meta. **O mecanismo é o que importa:** `continue-on-error: true` deixava o passo sair 1, o GitHub pintava annotation vermelha num run verde, e annotation de run que passou não é lida. Pior que o CVE em si — treina a ignorar annotation, num repo cujo catálogo é quase todo sobre aceitação silenciosa. É a família silent-acceptance **no próprio pipeline que deveria detectá-la**.
  **✅ CORRIGIDO (2026-09-02, commit `84c8720`).** Pisos declarados no `pyproject.toml` e lockfile regenerado com `uv pip compile --universal`: `aiohttp` → 3.14.3, `cryptography` → 50.0.1. Blast radius do regen: 8/6 linhas, só os dois alvos, e o marker `sys_platform` do `pywin32` sobreviveu (F113). `pip-audit` rodado contra o lockfile novo: *No known vulnerabilities found*. O passo perdeu o `continue-on-error` e passou a **tratar os próprios erros** — nunca falha, escreve no `$GITHUB_STEP_SUMMARY`, e reporta também falha de **instalação**, em vez de virar auditoria que silenciosamente não rodou. **Segue non-blocking de propósito:** CVE novo em dep transitiva não deve travar deploy de hotfix.
  **Sobre `aiohttp` ser transitivo:** entra pelo `facebook-business`, que não põe teto nenhum. O piso foi declarado no `pyproject` mesmo sem importarmos `aiohttp`, porque é o único lugar onde o resolver o respeita — sem isso a correção dependeria de o `uv` sempre escolher a mais nova, que não é garantia.
  **Os três ramos do shell foram testados, não só validados como YAML:** com CVE (rc=1) sai 0 e imprime a tabela; com falha de instalação sai 0 e avisa; sem `GITHUB_STEP_SUMMARY` no ambiente não quebra. **O primeiro teste passou por engano** — o shim não estava no `PATH` e o `pip-audit` real rodou, devolvendo "nenhuma vulnerabilidade" e fazendo o teste do ramo errado parecer verde. Refeito com substituição por caminho absoluto. É a 7ª ocorrência da família *guard que passou sem cobrir*.

- **F138 (MED, ABERTO) — commit que toca só `docs/` publica revisão nova do servidor MCP em produção.** Os 4 commits de catálogo de 02/09 mexeram exclusivamente em `findings-catalog.md` e mesmo assim rodaram `Authenticate to GCP` → `Route 100% traffic to latest revision` → `Smoke test`. Deu certo e a produção ficou saudável, mas **este é o servidor por onde o gestor escreve nas contas dos clientes**: um deploy no meio de uma sequência de `update_rsa` + `apply_change` tiraria a ferramenta com writes parciais aplicados. Naquele dia o push veio depois do passe por sorte, não por desenho.
  🔴 **`paths-ignore` no `on:` seria PIOR que o problema — verificado, não suposto.** A proteção de `main` tem `required_status_checks.contexts = ['test']` e `pr_required: true` (conferido via API). Com `paths-ignore: ['docs/**']`, um PR só de documentação **não dispara o workflow**, o check `test` nunca reporta, e o PR trava em *"Expected — waiting for status to be reported"* sem caminho de merge que não seja bypass de admin. Trocaria "deploy desnecessário" por "PR de docs impossível de mergear" — e como `enforce_admins: false`, a saída natural viraria burlar a regra de novo.
  **Correção proposta (não aplicada — decisão do Wellington): condicionar o JOB `deploy`, não o workflow.** O `deploy` já é gated por `if:` em [`ci.yml:84`](../../.github/workflows/ci.yml); basta o `test` exportar um output `code_changed` (via `git diff --name-only` entre `github.event.before` e `github.sha`, filtrando `^docs/|\.md$`) e o `deploy` exigi-lo. O `test` continua rodando **sempre**, então o required check reporta e o PR de docs mergeia — é a inversão exata do que o `paths-ignore` faria. **Fail-open** no ramo sem base (push inicial, force-push): um deploy a mais é melhor que um deploy que devia acontecer e silenciosamente não aconteceu.
  **Efeito colateral verificado como benigno:** com o deploy pulado, o SHA em produção deixa de ser o HEAD de `main`. A imagem é taggeada com `${{ github.sha }}` e os 3 Cloud Run Jobs apontam para a mesma tag, então tudo fica coerente no último commit **de código**; nada no pipeline assere que produção == HEAD. Só pede um comentário dizendo isso.
  **✅ CORRIGIDO (2026-09-02, commit a seguir).** O job `test` passou a exportar `code_changed` (comparando `github.event.before` com `github.sha`, filtrando `^docs/|\.md$`) e o `deploy` a exigi-lo. O `test` roda **sempre** — o required check reporta e PR de docs mergeia. **Fail-open** sem base confiável. `fetch-depth: 0` no checkout, porque em clone raso o `git cat-file -e` da base falha e o script cairia no fail-open **sempre**, virando no-op com cara de funcionando — e é esse o guard mais sutil de [`test_ci_deploy_gate.py`](../../tests/unit/test_ci_deploy_gate.py).
  **Testado contra os commits REAIS deste repo, não só com stub:** `3e78e12..92bc5dd` — o push exato que causou o finding — devolve `false`; os quatro cenários de código devolvem `true`; e os três de base ausente/zerada/inexistente caem no fail-open. Os guards de lógica foram verificados por **sabotagem nas duas direções** (padrão que classifica tudo como código, e padrão que não classifica nada), cada uma derrubando o grupo de testes esperado.
  **Tropeços registrados, porque a forma se repete:** (1) o literal do caminho do Git Bash foi corrompido por um heredoc que transformou `` em byte de backspace — o teste seguiu passando porque outro candidato resolvia, e só apareceu ao inspecionar os bytes; (2) `shutil.which("bash")` devolve o `bash.exe` do **WSL** em alguns contextos, que existe no PATH e falha ao executar. Presença no PATH não é prova de execução: o helper exercita cada candidato com `bash -c true`.
  **Registrado e fora de escopo:** o push de 02/09 gravou `Bypassed rule violations for refs/heads/main` nomeando as duas regras. Passou por `enforce_admins: false`, que é configuração de repositório — se o objetivo é que a política valha, o ajuste é lá, não no fluxo de quem empurra.

## Smoke em produção das tools novas 2026-09-02 (F139, F140 + reabertura do F131)

> **Gatilho:** a sessão de campo executou o smoke real — `remove_asset_link` em conta de teste do Wellington (`1163862076`, alvos com `[3b.25]` no próprio texto, campanha PAUSED), e `get_assets` sem filtro na conta viva. As tools passaram; o que caiu foi a **leitura** das respostas.

### ⚠️ Reabertura e refechamento do F131 (mesmo dia)

O fix original tinha a sonda de fronteira recebendo `start`/`end` — **a janela do usuário**. Consequência medida em produção: `account_frontier` mudava conforme a janela consultada. Janela 31/08–01/09 devolvia fronteira `2026-08-31` e `status: atrasado`; `TODAY` na mesma conta e no mesmo minuto devolvia `2026-09-02 11:43:39` e `confiavel`. Fronteira da conta que varia com a pergunta não é fronteira da conta.

**O modo de falha é o que importa:** o warning dizia que o fim da janela não tinha indexado, quando na verdade **01/09 foi dia sem write**. Toda janela terminando em dia parado — fim de semana, feriado — sairia `atrasado`. **Warning que dispara em condição normal treina a ignorar o warning**, que é o oposto do que o F131 constrói.

**O defeito estava no guard, não só no código.** O teste chamava-se *"a sonda não herda filtro do usuário"* e assertava a ausência de `resource_types`, `user_email`, `client_type` e `operation` — quatro filtros **enumerados**. A janela entrava como **argumento da função**, então nunca foi candidata a "filtro herdado". Guard que lista em vez de assertar a propriedade: o item fora da lista é o que passa.

**✅ Fix (commit `cc5230c`):** a sonda deixou de aceitar janela e deriva a própria sobre a retenção (`hoje-28 .. hoje+1`). Tirar o parâmetro fecha a classe — não há por onde herdar. Predicado de data continua obrigatório (a API recusa `change_event` com *infinite range*, probado), então a saída não era omitir a cláusula e sim ter janela própria e larga. O guard novo assere a **assinatura** (`params == {"today"}`), verificado por sabotagem.

**Resíduo não reproduzido, sem causa provada:** o campo relatou uma leitura em que a fronteira veio 25s abaixo do máximo real (`11:43:14` contra `11:43:39`). Não reproduz — a query isolada devolve o máximo, e as duas tools devolvem o máximo em 3 de 3 chamadas. A hipótese de `limit` foi testada e caiu; a de réplica atrasada explica os dados mas não foi provada e a janela passou. **Registrado sem causa em vez de fechado com hipótese.**

🔑 **Consequência de desenho que vale além deste caso:** a asserção de smoke não pode ser `account_frontier == MAX(GAQL)`. As duas queries não são simultâneas, então igualdade estrita transforma qualquer deriva — write no intervalo, propagação, réplica — em falha de teste. E asserção flaky é reprovada, investigada, não reproduzida e no fim **ignorada**, perdendo-se justamente a checagem de corretude. O runbook assere `>= MAX − 120s`, com o `MAX` rodando **antes** da tool para a deriva ficar na direção benigna. O que o teste precisa pegar é fronteira **filtrada** (erra por dias) e **estagnada** (erra por sempre), não discordância de segundos.

### F139 (MED) — `applied_count` conta o TENTADO, e tem cara de veredito

Re-remover um vínculo já `REMOVED` devolve `status: applied` e `applied_count: 1` para uma operação que não mudou nada. O único vestígio é `resource_names: [null]`, fácil de não olhar num JSON de sucesso.

**Onde morde:** batch parcial. Removendo 10 vínculos dos quais 6 já estavam `REMOVED`, a resposta diz `applied_count: 10` e o gestor registra "10 removidos". A mudança real foi 4, codificada como *"quantos elementos do array não são null"* — que ninguém conta.

**Não é da tool nova.** `applied_count = target_count` vive em [`mutations.py`](../../src/google_ads/mutations.py) `run_mutation`, e atinge **todo** mutate com `__partial_failure__` — o `remove_audience` tem a mesma cara desde sempre. É a família *"campo com nome de veredito que não é o veredito"*, a mesma do F133 (`total_cost_wasted_brl`) e do §7 da spec de assets — e desta vez a ironia é dupla: a description do `remove_asset_link` diz, com todas as letras, *"contagem de linhas NÃO distingue sucesso de falha"*, e a resposta dela tinha exatamente esse defeito um nível acima.

**A condição real é mais sutil do que parece, e o primeiro fixture não a reproduzia:** o Google **não** reporta falha no no-op. O oneof da op fica setado (ela "sucede"), e só o `resource_name` volta vazio — que `_extract_resource_names` converte em `None` pelo `or None`. Um fixture com op *falhada* passa longe: ali o `applied_count` já acerta, porque o `per_op_results` classifica como `failed`. A asserção pegou o fixture errado antes do commit.

**✅ CORRIGIDO (commit `d359c69`).** Entra `changed_count` ao lado, derivado do sinal que já existia — o Google devolve o `resource_name` do recurso mutado, e um no-op não devolve nada. `applied_count` **fica como está**, por ser contrato em produção. Sem `resource_names` na resposta (drift de SDK), `changed_count` vem `None`: melhor ausente que inventado.
**Deliberadamente fora:** o pré-check no **dry-run**, que marcaria quais alvos já estão `REMOVED` no momento em que o operador ainda pode desistir. Exige parsear `resource_name` → nível → query por camada, o que é uma superfície de falha nova; o `changed_count` resolve o caso de leitura errada com uma linha e sem query adicional. Fica como candidato se o padrão reincidir.

### F140 (LOW) — tool nova só aparece para sessão nova

O catálogo de tools é negociado no **handshake** do MCP. Sessão aberta antes do deploy segue com a lista antiga, e o sintoma é a tool **"não existir"** — `ToolSearch` por nome exato e por keyword não acha —, não um erro que mencione deploy ou versão. Travou o smoke dos dois lados em 02/09: nem a sessão de campo nem esta viam `get_assets`/`remove_asset_link` logo após o deploy, com o servidor já servindo 66 tools. Não é bug; é ciclo de vida. **Vale como linha de runbook de release:** depois de shippar tool nova, reconectar o MCP antes de tentar o smoke.

**Nota de processo, da mesma execução:** a primeira tentativa de rodar o `remove_asset_link` foi **bloqueada pelo classificador de auto mode do Claude Code** — não pelo gate do MCP nem pelo Google. O sintoma é um erro que não menciona o MCP. A sessão de campo parou e levou ao Wellington em vez de contornar, e ele autorizou por ser conta de teste dele. **Smoke de tool destrutiva pode barrar na camada do harness antes de chegar na nossa.**

### O que o `get_assets` mostrou na conta viva (735 vínculos, `limit: 1000`)

Somas consistentes nos dois eixos, `truncated: false`, `orphan_scope: conta_completa`, e **132 assets sem vínculo ativo** — incluindo `144113768040` e `144113768046`, os dois callouts removidos em 02/09. **A tool fecha o ciclo do incidente que a originou:** os 6 vínculos que ninguém enxergava aparecem numa chamada, nos dois níveis, com `ASSET_LINK_REMOVED` explícito.

Três correções de description saíram daí, todas medidas e aplicadas em `d359c69`: `UNSPECIFIED` aparece em `primary_status` (a lista de 6 estava fechada demais — a convenção "sentinela não é valor de operador" do F135 não vale quando a API os emite); `primary_status_reasons` carrega `ASSET_DISAPPROVED` (15) e `ASSET_UNDER_REVIEW` (18), ou seja política visível sem outra query; e `asset_name` vem **vazio em 100%** de sete famílias de texto (SITELINK 71/71, CALLOUT 19/19, CALL 10/10, STRUCTURED_SNIPPET 7/7, BUSINESS_MESSAGE 8/8, BUSINESS_NAME 3/3, PROMOTION 2/2) — o Google só popula `name` em algumas famílias, e campo sempre vazio convida à conclusão errada. **`AD_IMAGE` é 598 de 735 (81%)**, então o default de 200 trunca e afoga as extensões de texto.


## F141 (MED, CORRIGIDO 03/09) — os presets de data resolvem em UTC, e nenhuma das 25 contas esta em UTC

> **✅ CORRIGIDO em 03/09**, junto com F143 e F144 — ver *"Como o bloco F141 + F143 + F144 foi fechado"* no fim do catalogo. `hoje` passou a ser `resolve_account_today(customer_id)` em 24 tools (22 com preset + `get_budget_pacing` + `get_negative_keywords_audit`), `today` e kwarg obrigatorio nos resolvers, e um guard AST impede relogio do servidor em tool Google.

> **Como apareceu:** caiu do **T7 do smoke de assets**, executado em 02/09 pra validar o refix do F131.
> A asserção que falhou não era sobre isto — e é esse o ponto. Sem o `freshness` que o F131 acabou de
> introduzir, a chamada teria devolvido zero linhas **sem sinal nenhum** e passado por "nada mudou hoje".

**Medido, não deduzido.** `get_change_history(customer_id="7862230676", date_range="TODAY")` devolveu
`period: {"from": "2026-09-03", "to": "2026-09-03"}` num instante em que, na conta, ainda era
**2026-09-02**. A conta é `America/Fortaleza` (UTC−3).

**Causa.** [`_common.py`](../../src/google_ads/queries/_common.py) resolve todo preset a partir de:

```python
def _today() -> date:
    return datetime.now(UTC).date()
```

O Google interpreta predicado de data **no fuso da conta**. Levantado por `list_my_accounts` em 02/09,
as 25 contas do MCC estão em **cinco fusos** — `America/Sao_Paulo`, `America/Fortaleza` e
`America/Recife` (UTC−3, 23 contas), `America/Campo_Grande` e `America/Boa_Vista` (UTC−4, 2 contas).
**Nenhuma em UTC.** Não existe conta para a qual o cálculo esteja certo.

**Janela do defeito:** das **21:00 à meia-noite** locais (20:00 nas duas contas UTC−4) — ~3h por dia,
**12,5% do tempo**, todo dia. Fora dela, data UTC e data local coincidem e nada acontece.

**O que sai errado, por família de preset:**

| Preset | Aritmética | Efeito depois das 21:00 |
|---|---|---|
| `TODAY` | `today..today` | Pede um dia que **ainda não começou** na conta → **zero linhas, em silêncio**. Foi o caso medido. |
| `YESTERDAY` | `yesterday..yesterday` | Devolve o dia **corrente parcial** rotulado como "ontem". |
| `LAST_7/14/30/90_DAYS` | `yesterday-N+1 .. yesterday` | A janela **desliza um dia**: entra o dia corrente **parcial** e sai o dia inteiro mais antigo. |
| `THIS_MONTH` / `THIS_WEEK` | ancorados em `today` | Mesmo deslize; no dia 1º e na segunda-feira o mês/semana vira cedo demais. |

**A família de `LAST_N_DAYS` é a mais perigosa, por ser a menos visível.** `TODAY` vazio pelo menos
parece estranho. "Últimos 7 dias" com 6 dias cheios + o parcial de hoje **parece certo** e vem com um
número menor. Em `get_account_overview` o comparativo período-a-período herda o mesmo deslize dos
dois lados, então a variação percentual sai contaminada sem nada indicar.

**Por que nenhum teste pega.** Os testes congelam o tempo com `freezegun`, e sob tempo congelado a
data UTC e a data da conta são a mesma coisa — a diferença que constitui o bug **não é representável**
no fixture. É a mesma classe do F87/F89: teste que codifica a convenção errada não falha, ele
confirma o erro.

**Relação com o F23.** Aquele fix já convivia com isto: o clamp da retenção usa "margem 2-day safety
**contra UTC drift**". A margem trata o sintoma de borda; a causa nunca foi endereçada.

**Não corrigido — mas o fix é mais barato do que parece, e isso foi verificado.** O conserto correto
resolve o preset **no fuso da conta**, e a objeção esperada seria "isso custa uma query por chamada".
**Não custa:** o fuso já está persistido em `google_ads_accounts.time_zone`
([`repositories/google_ads_accounts.py`](../../src/db/repositories/google_ads_accounts.py)), populado
pelo resync a partir de `customer_client.time_zone`, e é de lá que o `list_my_accounts` já lê. É
leitura local, sem chamada extra ao Google.

**O que decidir de fato, antes de mexer:**
- **A coluna é `str | None`.** Precisa de fallback declarado para conta sem fuso sincronizado — e o
  fallback honesto é UTC com o comportamento de hoje, não um palpite de fuso.
- **Onde entra.** `parse_date_range` hoje é pura e não conhece conta. Passar o fuso como argumento
  mantém a pureza; ler o DB lá dentro violaria o F92 (primitivo que lê estado próprio).
- **`zoneinfo` precisa da base de fusos.** No Cloud Run (Linux) ela existe; no Windows local pode
  exigir o pacote `tzdata` — se exigir, é dep de prod e o `requirements.txt` tem que ser regenerado
  no mesmo commit com `--universal` (F113).
- **Usar o fuso do MCC como atalho está errado** para as 2 contas UTC−4. Trocaria um bug silencioso
  por outro menor, e é exatamente a gambiarra que o padrão de solução deste projeto recusa.

Blast radius: **todas** as tools com preset, que são quase todas. Merece sprint próprio, não remendo.


## F142 (HIGH, CORRIGIDO) — a whitelist de `client_type` tem um valor que nao existe e nao tem o que a API emite

> **Como apareceu:** a sessao de campo varreu 23 contas atras de um `REMOVE` historico. Numa delas
> (`4432986150`, Camacari) apareceu uma linha de auto-apply do Google — e o `auto_applied_count` da
> mesma resposta veio **`0`**. Nao foi o objetivo de nenhuma das duas investigacoes; caiu de olhar a
> linha inteira em vez do campo que se estava conferindo.

**Tres defeitos, uma causa.** [`get_change_history.py`](../../src/mcp/tools/get_change_history.py) e
[`drift_detection.py`](../../src/google_ads/drift_detection.py) tratam `client_type` por string
literal. O enum `ChangeClientType` do SDK v24 tem **15** valores; a whitelist da tool tem **14**, e a
diferenca nao e so de tamanho:

| | SDK v24 | whitelist da tool | efeito |
|---|---|---|---|
| regra automatizada | `GOOGLE_ADS_AUTOMATED_RULE` | `GOOGLE_ADS_AUTOMATED_RULES` | **valor morto** — a API rejeita |
| auto-apply por assinatura | `GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION` | *ausente* | **nao filtravel** |

**1. A tool oferece um filtro que o Google recusa.** Medido, nao deduzido — chamada com
`client_types=["GOOGLE_ADS_AUTOMATED_RULES"]` (valor **do proprio schema**) devolve:
`Invalid enum value cannot be included in WHERE clause: 'GOOGLE_ADS_AUTOMATED_RULES'`. Plural que nao
existe. Quem escolher essa opcao da lista leva erro duro.

**2. `auto_applied_count` conta errado.** `_AUTO_APPLY_CLIENT_TYPE` e a string unica
`"GOOGLE_ADS_RECOMMENDATIONS"`, e producao emitiu `GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION`. Medido na
conta `4432986150`: uma linha `user_email: "Recommendations Auto-Apply"`,
`client_type: GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION`, e `summary.auto_applied_count: 0`.

**3. `detect_drift` pega a mudanca e perde o rotulo — e a pegada e por acidente.** Medido na mesma
conta: `total_drift_changes: 1` e **`flags: []`**. A flag `auto_apply_detected` nao sobe num auto-apply
de manual. A linha so entra em drift porque `"Recommendations Auto-Apply"` nao e e-mail valido e
portanto nunca estara em `responsible_user_emails` — ou seja, o mecanismo **desenhado** (a flag) falha,
e o que salva e um efeito colateral do campo ser `format: email`.

🔴 **O caminho que vira falso negativo de verdade** e a pergunta natural do gestor:
`get_change_history(client_types=["GOOGLE_ADS_RECOMMENDATIONS"])` — *"o que o Google aplicou sozinho?"*.
Numa conta com auto-apply por assinatura isso devolve **vazio**, que le como atestado de limpeza. O
`CLAUDE.md` classifica auditoria de auto-apply como "CRITICO antes de tudo"; e exatamente essa consulta.

**A licao, e o motivo de doer:** o F136 foi fechado **no mesmo dia** com um guard que cruza o conjunto
com o enum do SDK. Ele foi aplicado a `ChangeEventResourceType` em dois lugares
([`test_change_event_enum_guards.py`](../../tests/unit/test_change_event_enum_guards.py),
[`test_drift_structural_scope.py`](../../tests/unit/test_drift_structural_scope.py)) e **nao** a
`ChangeClientType` — mesmo arquivo, mesma forma, um enum ao lado. **O guard foi aplicado a instancia,
nao a classe do problema.** Family: `design-gap-via-API-enum-whitelist` (F17/F18/F19/F53/F136).

**✅ CORRIGIDO** em 2026-09-02, por TDD com o RED observado (7 testes falhando contra o codigo
pre-fix antes de qualquer linha de producao mudar). Tres mudancas:

1. `GOOGLE_ADS_AUTOMATED_RULES` → `GOOGLE_ADS_AUTOMATED_RULE`; entra `GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION`.
2. `_AUTO_APPLY_CLIENT_TYPE` (string) vira `AUTO_APPLY_CLIENT_TYPES` (`frozenset` com os dois valores),
   com **fonte unica** em [`drift_detection.py`](../../src/google_ads/drift_detection.py) — havia uma
   copia da constante em cada modulo, e **copia divergente foi o vetor deste proprio finding**.
3. Guard novo em [`test_change_client_type_guards.py`](../../tests/unit/test_change_client_type_guards.py),
   espelhando o irmao de `ChangeEventResourceType`.

🔑 **Correcao de uma recomendacao errada que eu tinha escrito aqui:** a versao anterior deste paragrafo
mandava **derivar** `_CLIENT_TYPES` do enum do SDK em tempo de import. Isso contraria uma decisao ja
tomada e documentada no guard irmao, que so vi ao abrir o arquivo — **producao nao deriva de proposito**,
porque o schema de uma tool MCP e contrato publico e derivar faria um bump do `google-ads` mudar os
valores aceitos pelo gestor **sem diff, sem revisao e sem linha de catalogo**; alem de cravar a versao
da API num import do caminho que atende request. O padrao correto e o que ja existia: producao guarda
snapshot revisado, e o **CI reconcilia** com a fonte autoritativa. Recomendar sem ler o vizinho e como
se chega a "solucao" que desfaz um trade-off que ja tinha sido decidido.

**O guard foi verificado contra 4 variantes quebradas, nao so contra o bug conhecido.** As duas
primeiras mantem `len == 15` de proposito — passariam por um guard de contagem, que era o modo de falha
a evitar: (a) trocar um nome valido por um invalido, (b) reintroduzir o plural removendo o singular,
(c) remover o valor de `_SUBSCRIPTION`, (d) reintroduzir a comparacao por string unica no
`_build_summary`. **4/4 detectadas**, e as duas de `len` constante cairam na assercao de **igualdade de
conjuntos** — que e a diferenca entre este guard e um que so conta.

## F143 (MED, CORRIGIDO 03/09) — `atrasado` afirma lag onde a evidencia so mostra silencio

> **✅ CORRIGIDO em 03/09:** `atrasado` → **`nao_coberto`**, com o texto admitindo as duas hipoteses (lag OU conta parada) e o lag medido (~6 min a >4 dias). A opcao (2) do campo — tolerancia de N horas — foi recusada por embutir contrato de lag que nao existe. Ver o fecho do bloco no fim do catalogo.

> **Como apareceu:** a sessao de campo rodou o `freshness` em 23 contas do MCC e nao viu `confiavel`
> em nenhuma — 15 `atrasado`, 8 `indeterminado`.

**Antes do achado, uma correcao do dado.** O "zero `confiavel` em 23" e **artefato da consulta**, nao
propriedade das contas: a varredura filtrava
`resource_types=["CAMPAIGN","AD_GROUP"] + operation_types=["REMOVE"]` e nao existia evento desses em
conta nenhuma, entao **todo recorte estava vazio por construcao**. Recorte vazio nunca pode ser
`confiavel` — por desenho ele e `ambiguo` ou `atrasado`, e esse e o ponto inteiro do F131. Medido na
mesma conta `4432986150` sem o filtro, janela `06/08 → 01/09`: **`confiavel`**. O 8 `indeterminado`
confirma o desenho funcionando: conta sem nenhum evento na retencao se recusa a fingir frescor.

**O achado que sobra, e e real:** `assess_freshness` decide por
`account_frontier.date() < window_end`. Mas **`account_frontier` so avanca quando alguem mexe na
conta** — conta parada ha tres dias tem fronteira de tres dias atras, e nao porque a indexacao
atrasou, e sim porque nao houve o que indexar. Logo, toda consulta cuja janela chega ate hoje numa
conta sem write hoje sai `atrasado`. O warning **afirma causa** — *"O trecho final da janela ainda nao
indexou"* — e a evidencia sustenta apenas o fato. Em conta de baixa atividade, a explicacao dominante
e a outra. **Alerta que dispara em condicao normal treina a ignorar o alerta**, que e o oposto do que
o F131 constroi — a mesma frase que justificou a reabertura do F131 hoje de manha.

⚠️ **Parte da amostra e F141, nao limiar — e isso muda o dimensionamento.** A varredura usou
`LAST_30_DAYS`, cujo `window_end` e `yesterday`; sob o F141 esse `yesterday` (UTC) e **hoje** na conta.
Medido na `4432986150`, so mudando o fim da janela: `→ 02/09` da `atrasado`, `→ 01/09` da
**`confiavel`**. Ou seja, ao menos um dos dois pontos do campo vira sozinho quando o F141 for
corrigido. **Qual fracao dos 15 e F141 e qual e limiar so da pra saber remedindo depois do F141** —
nao dimensione este fix antes disso.

**Sobre as tres opcoes propostas pelo campo:**
- **(1) trocar o texto, manter a logica — sim, e ir um passo alem.** O rotulo `atrasado` *e* a
  afirmacao; quem le a resposta le o `status`, nao o warning. O campo deve nomear o **fato** (a janela
  passa do ultimo evento indexado), nao a causa. Trocar o valor do enum e mais barato **agora** do que
  em qualquer momento futuro: ele subiu hoje e tem dois consumidores.
- **(2) tolerancia de N horas — nao, como proposto.** Move a linha sem desfazer o erro de categoria:
  conta parada ha 3 dias continua dizendo `atrasado`, e continua errado. Pior, embute uma constante
  magica que finge existir um contrato de lag — quando a premissa declarada do F131, medida, e que
  **nao ha contrato** (~3h a >4 dias). Codificar 24h contradiz o achado que motivou a feature.
- **(3) ritmo da conta — de acordo com o campo: nao agora.** Heuristica nova com erro nos dois sentidos.

**O unico desambiguador real, para registro e nao para agora:** `change_status` e um recurso distinto,
feito pra sync incremental e com caracteristicas de lag proprias. Mudanca recente visivel nele e ausente
do `change_event` seria evidencia **positiva** de lag, separando as duas hipoteses que hoje se
confundem. Custa uma segunda consulta e uma dependencia nova. Nao entra sem necessidade demonstrada.

### Nota de cobertura: `structural_change` nao e testavel pelo caminho que testa as outras

A flag detecta `REMOVE` de CAMPAIGN/AD_GROUP — **operacao que o MCP nao sabe fazer**. Nao existe
`remove_campaign` nem `remove_ad_group`; as descriptions de `update_campaign_status` e
`update_ad_group_status` mandam usar a UI. O smoke dela exige evento vindo **de fora** do MCP, o que e
coerente com o proposito (drift e justamente o que vem de fora) mas significa que nenhum runbook a
exercita sem acao manual na UI. A sessao de campo varreu 23 contas e nao achou um so `REMOVE` dessas
entidades dentro da retencao — a flag nunca disparou em producao ate hoje.


## F144 (HIGH, CORRIGIDO 03/09) — `confiavel` afirma cobertura que a fronteira nao pode provar

> **✅ CORRIGIDO em 03/09:** entrou o status **`em_curso`** — janela que alcanca o dia corrente DA CONTA (F141) ou passa dele nunca sai `confiavel`. Valor proprio, nao reuso de `ambiguo`. Ver o fecho do bloco no fim do catalogo, inclusive a correcao de ordem que o RED forcou (janela futura).

> **Como apareceu:** a sessao de campo removeu uma campanha pela UI (conta de teste `1163862076`) e
> foi conferir se o `structural_change` disparava. Nao disparou — e o que ela achou no caminho foi
> pior: o selo de frescor dizia `confiavel` sobre uma resposta que **omitia a remocao**.
> Reproduzido aqui de forma independente, com o estado confirmado por GAQL antes.

**Medido, com controle.** Estado por GAQL, imediato: campanha `23861545627` → **`REMOVED`**. Na mesma
conta e no mesmo minuto, `detect_drift(LAST_2_DAYS)`:

```
total_drift_changes: 2        <- so os CAMPAIGN_ASSET do smoke; a remocao NAO esta
flags: []                     <- structural_change nao sobe (o evento nao chegou)
freshness: { account_frontier: "2026-09-02 20:44:05",
             status: "confiavel", warning: null }     <- a afirmacao falsa
```

O GAQL e o **controle**: ele estabelece um fato que o `change_event` ainda nao conhece, que e
exatamente a condicao que o `freshness` existe pra detectar. Sem ele, "duas linhas e `confiavel`"
pareceria uma resposta correta.

**O mecanismo.** [`change_freshness.py`](../../src/google_ads/change_freshness.py) decide por
`account_frontier.date() < window_end` — **granularidade de dia**. Fronteira `2026-09-02 20:44` tem
`.date()` igual a `2026-09-02`, entao "cobre" o dia inteiro, incluindo as 3 horas seguintes em que a
remocao aconteceu. Isolado pelo campo, mesma fronteira, so mudando o fim da janela:

| janela | inclui o dia corrente? | status |
|---|---|---|
| 31/08 → 01/09 | nao | `ambiguo` ✅ |
| 01/09 → **02/09** | **sim** | **`confiavel`** ❌ |

🔑 **A premissa que quebra, e vale alem deste caso:** `account_frontier` diz *"o mais recente que eu
vi"*, **nao** *"eu vi tudo ate aqui"*. Sao coisas diferentes, e o codigo tratou a primeira como se
fosse a segunda. Para qualquer janela que inclua o dia corrente, `confiavel` e promessa impossivel —
o dia ainda esta correndo, e sempre pode haver evento posterior a fronteira e anterior ao fim do dia.

**Por que e HIGH, sendo o espelho do F143 (MED).** A assimetria de custo e o que separa os dois:
- **falso `atrasado`** (F143) → ruido. O operador confere por GAQL e segue. Custo: atencao.
- **falso `confiavel`** (este) → confianca indevida. O operador **nao** confere. Custo: a mudanca de
  terceiro passa, que e precisamente o que a feature existe pra impedir.

`confiavel` e a afirmacao mais forte que o campo faz, e errar para o lado permissivo derruba a razao
de ser do mecanismo — o mesmo argumento que justificou nao deixar sonda vazia sugerir frescor.

### O fix nao e isolado: F141, F143 e F144 tem a mesma dependencia

**Nao corrigido, e nao deve ser corrigido sozinho.** A regra certa e *"quando a janela alcanca o dia
corrente, `confiavel` nao e alcancavel"* — e "dia corrente" tem que ser **o da conta**, nao o do
servidor, que e exatamente o que falta no [F141](#f141-med-aberto--os-presets-de-data-resolvem-em-utc-e-nenhuma-das-25-contas-esta-em-utc).
Neste caso as duas pontas coincidiram **por acidente** (o preset resolveu `window_end` em 02/09 e na
conta ainda era 02/09); com fuso diferente divergem. Os tres findings tocam a mesma superficie
pequena e dependem do mesmo fuso da conta:

| | o que muda |
|---|---|
| **F141** | de onde vem `window_end` (fuso da conta, nao UTC) |
| **F143** | o rotulo `atrasado`, que afirma causa nao sustentada |
| **F144** | o teto de `confiavel` quando a janela alcanca o dia corrente |

Fazer os tres numa passada evita mexer no mesmo enum tres vezes — e enum de resposta e contrato.

⚠️ **Cuidado de desenho ao escrever o fix: nao reusar `ambiguo` para este caso.** Hoje `ambiguo`
significa *"a conta esta em dia e o teu recorte esta genuinamente vazio"*. Aqui o recorte **tem
linhas** (2) e o problema e outro: elas podem estar incompletas. Um mesmo rotulo cobrindo
"teu vazio talvez seja real" e "teu nao-vazio talvez esteja faltando linha" pede leituras opostas do
leitor. Este caso merece valor proprio.

**O caso de teste, que a sessao de campo desenhou e vale guardar:** (1) fazer qualquer mutacao na
conta; (2) **confirmar por GAQL que o estado mudou**; (3) rodar com janela terminando hoje;
(4) asserir `freshness.status != "confiavel"`. O passo 2 e o que separa este teste dos outros — sem
ele nao ha controle, e o teste nao distingue "cobertura correta" de "cobertura afirmada por engano".
E determinístico: nao depende de esperar o lag.

### Nota: `structural_change` continua sem poder ser exercido

A remocao de campanha **existe no estado e nao no `change_event`** — o smoke da flag depende de o
evento indexar, o que nao tem contrato de prazo. Somado ao que ja estava registrado (a flag detecta
operacao que o MCP nao sabe fazer, entao exige acao pela UI), a conclusao pratica e que essa flag
so pode ser validada em janela de horas ou dias, nunca dentro de uma sessao.


## F145 (HIGH, CORRIGIDO 03/09) — `structural_change` procura `REMOVE` numa entidade que nunca emite `REMOVE`

> **✅ CORRIGIDO em 03/09** — ver o bloco *"F145 CORRIGIDO"* logo abaixo da entrada. Predicado passou a cobrir `status → REMOVED`, a transicao sai na resposta, e `ENABLED↔PAUSED` por nao-autorizado ganhou `status_change_detected` (medium) por decisao registrada.

> **Como apareceu:** a sessao de campo pediu ao Wellington uma remocao real de campanha pela UI pra
> exercer a flag. O evento indexou, entrou na resposta como drift, e a flag **nao subiu**. Verificado
> aqui de forma independente no `change_event` cru e depois generalizado por probe agregada.

**O evento, medido** (conta `1163862076`, campanha `23861545627`):

```
change_resource_type:      CAMPAIGN
old_resource:              {campaign: {status: "PAUSED"}}
new_resource:              {campaign: {status: "REMOVED"}}
resource_change_operation: UPDATE
changed_fields:            status
```

**O codigo** ([`drift_detection.py`](../../src/google_ads/drift_detection.py)):
`if r.operation == "REMOVE" and r.resource_type in _STRUCTURAL_RESOURCE_TYPES`.

**Remover campanha no Google Ads nao e uma operacao de remocao — e um `UPDATE` do campo `status`.**
A flag procura um verbo que essa entidade nunca emite.

### A regra geral, levantada por probe agregada e nao inferida

`run_gaql` com `aggregate_by` sobre 141 eventos / 28 dias na conta `7862230676` da o mapa
(tipo × operacao) empirico:

| operacao | tipos que a emitem |
|---|---|
| `REMOVE` | `CAMPAIGN_ASSET` (4), `CAMPAIGN_BUDGET` (3), `CUSTOMER_ASSET` (2), `CAMPAIGN_CRITERION` (2) |
| `UPDATE` | `AD_GROUP_CRITERION` (65), `AD` (20), **`CAMPAIGN` (2)**, `CAMPAIGN_BUDGET` (2) |

🔑 **A regra que isso revela vale alem do caso:** entidade que **tem campo `status` com valor
`REMOVED`** e soft-deleted, e o `change_event` registra `UPDATE`. Entidade sem esse campo e
hard-deleted, e registra `REMOVE`. Por isso `AD_GROUP_CRITERION` (keyword, tem status) so aparece como
`UPDATE`, enquanto `CAMPAIGN_CRITERION` (negativa, nao tem) aparece como `REMOVE`.

**Consequencia para os dois membros que sobraram no set:** `CAMPAIGN` esta medido. `AD_GROUP` nao
aparece na amostra, mas tem `AdGroupStatus.REMOVED`, logo cai na mesma regra — **inferencia, com a
regra medida em 6 tipos**, nao medicao direta. Vale confirmar quando surgir um evento real.

### Por que isto e pior que o F136, que "fechou" hoje de manha

O [F136](#f136) tirou `CONVERSION_ACTION` do set por nao existir no enum, e **declarou na description
da tool** que a flag *"cobre REMOVE de CAMPAIGN e AD_GROUP"*. Medido agora: **nao cobre nenhum dos
dois.** O fix daquele finding tornou a promessa mais confiante sobre uma cobertura que nao existe —
e silencio teria sido melhor que garantia falsa, porque o gestor le a description e para de conferir.

**Isto tambem explica, com causa, o que estava registrado sem causa:** a varredura de 23 contas nao
achou um `REMOVE` de CAMPAIGN/AD_GROUP em nenhuma. Foi lido como "essas remocoes sao raras". Nao sao —
**esse par (tipo, operacao) nao ocorre**. A ausencia era o achado, e passou por ruido.

### O fix nao e um `or` a mais

**Predicado sugerido:** `resource_type in {CAMPAIGN, AD_GROUP}` **e** (`operation == REMOVE` **ou**
(`status` em `changed_fields` **e** `new_resource.<entidade>.status == "REMOVED"`)).

Mas a query da tool ([`change_history.py`](../../src/google_ads/queries/change_history.py)) **nao
seleciona `new_resource`** — so `changed_fields`. Entao o fix envolve: campo novo no SELECT (payload
maior — `old_resource`/`new_resource` sao protos aninhados), parser novo, e o predicado. Nao e
one-liner, e mexe no caminho de uma tool de seguranca.

⚠️ **Uma decisao de escopo que precisa ser tomada de proposito, nao por omissao:** `update_campaign_status`
e `update_ad_group_status` do proprio MCP tambem produzem `UPDATE` de `status`. Ou seja **pausar e
remover geram o mesmo `operation`**, e so o valor em `new_resource` distingue. Fica a pergunta: um
terceiro **pausando** a campanha de um cliente e drift estrutural? Hoje nao sobe flag nenhuma. Se
ficar de fora, que fique por escolha registrada — e nao porque o predicado nao olhou.

### ✅ F145 CORRIGIDO (03/09) — e a decisao de escopo que veio junto

**Predicado:** `resource_type ∈ {CAMPAIGN, AD_GROUP}` e (`operation == REMOVE` **ou**
`new_status == REMOVED`). O `REMOVE` fica (hard-delete de vinculo/criterio segue coberto); a
transicao e o caso que a flag nomeava e nunca tinha visto. `changed_fields` nao entra: o Google
nao aceita mutacao em campanha ja removida, entao `new_resource.status == REMOVED` num `UPDATE`
**e** a transicao.

**Dado:** o SELECT ganhou `old_resource`/`new_resource` (validados contra a API na propria query de
verificacao deste finding; o Google so popula os campos que mudaram — payload pequeno, medido). O
formatter extrai `old_status`/`new_status` **keyed pelo `resource_type`** — em proto-plus
`new_resource.campaign` existe (vazio, `UNSPECIFIED`) mesmo numa linha de keyword; olhar pela
presenca do atributo inventaria status. As linhas de `get_change_history` e os `changes[]` do
`detect_drift` passam a **expor** a transicao (`PAUSED → REMOVED`): adicao de contrato.

**`ChangeEventRow`/`DriftChange` ganharam os dois campos SEM default**, e ha guard por introspecao
(`dataclasses.fields`). Default aqui seria a forma exata do F145 de volta: formatter esquece de
popular, tudo vira `None`, o predicado nunca casa, a flag fica cega em silencio — e nenhum teste
de comportamento pega, porque o converter segue populando. A licao do F141 (asserir "sem default"
pela assinatura) aplicada no dia seguinte.

**Decisao de escopo (Wellington, 03/09): `ENABLED↔PAUSED` por nao-autorizado ganhou flag propria,
`status_change_detected` (medium).** Pausar e remover geram o mesmo `operation`; so o valor
distingue. Reativar campanha alheia comeca gasto; pausar para entrega — e o cenario de co-gestao
que a tool existe pra pegar. Reversivel, por isso **nao** e `structural_change`. `REMOVED` sai so
como `structural_change`, nunca as duas.

**Description do `detect_drift` reescrita:** a frase do F136 que prometia "cobre REMOVE de
CAMPAIGN e AD_GROUP" saiu; entrou a verdade — remocao e `UPDATE` de status, a flag cobre as duas
formas, e existe `status_change_detected`.

**Verificacao:** RED observado (13/13 falhas antes de qualquer linha de producao); **sabotagem
7/7 de primeira** — predicado volta ao verbo, formatter devolve `None`, converter derruba o campo,
**tool nao serializa** (`detect_drift` monta o dict a mao — esse e o RED que eu nao tinha visto na
ordem, porque corrigi a serializacao na mesma cadeia em que o fixture estava errado; a sabotagem
foi a prova), SELECT perde `new_resource`, formatter keyed por atributo, e default no dataclass.

**Follow-up nomeado, fora:** generalizar `old_status`/`new_status` para todo tipo com campo
`status` (keyword, anuncio) e barato e util ("quem pausou a keyword?"), mas e outra pergunta.

## Evidencia nova sobre o residuo de 25s (sem ID proprio — fecha a lacuna do F131)

O campo observou, **dentro de uma unica resposta** do `detect_drift`, o `account_frontier` ja em
`23:37:35` enquanto a query principal ainda devolvia 2 linhas (o evento das 23:37 faltando). Re-rodou
segundos depois e vieram 3.

**Isso e a mesma assinatura do `11:43:14` que ficou sem causa de manha** — e agora com as duas leituras
**no mesmo request**, o que descarta as hipoteses de revisao diferente do deploy e de `limit`. A
hipotese de **eventual consistency entre replicas** ganha evidencia forte: a sonda e a query principal
sao chamadas distintas ao mesmo backend e podem pousar em replicas com estados diferentes.

**Duas consequencias praticas:**
1. **Confirma o desenho da tolerancia no runbook.** Asserir `account_frontier == MAX(GAQL)` com
   igualdade estrita seria flaky **por natureza**, nao por acaso — o `>= MAX - 120s` estava certo.
2. **Vale como nota de metodo:** duas leituras do mesmo endpoint com segundos de diferenca podem
   discordar. Qualquer smoke que compare tool contra GAQL tem que tolerar isso ou reprova sem defeito.

**Lag medido, terceiro ponto da distribuicao:** remocao as `2026-09-02 23:37:35`, leitura carimbada
`23:44:05` → **≤ 6min30s** (limite superior). Com os anteriores, a distribuicao vai de **~6 min** a
**~3-4 h** a **>4 dias**, na mesma familia de contas: **tres ordens de grandeza**. A afirmacao de que
o lag nao tem contrato — que esta em description de tool — deixa de se apoiar em dois pontos.


## Como o bloco F141 + F143 + F144 foi fechado (03/09) — e o que caiu no caminho

**Um `hoje` por request, no fuso da conta, passado a tudo.** `account_today(time_zone, *, now)` e
pura (recebe o instante — e a unica forma de o teste representar UTC e conta discordando, o que
`freezegun` nao consegue). `parse_date_range`/`resolve_date_window` recebem `today` como kwarg
**sem default**: dos 22 call-sites, 18 nao tem teste direto, e o guard deles e o **mypy** —
`Missing named argument "today"` — provado por sabotagem, nao suposto. O I/O e um modulo so,
`account_clock.resolve_account_today` (`run_with_reconnect` → `get_by_customer_id`), com o caminho
real coberto por teste de integracao com DB (Fortaleza e Campo Grande dando 02/09 no instante do
bug; conta sem fuso caindo em UTC sem estourar). `tzdata` virou dep de prod: sem ela o Windows nao
acha `America/Fortaleza`, e com ela Linux e Windows ficam identicos.

**O bloco cresceu duas vezes, e as duas por probe, nao por estimativa:** o grep de
`datetime.now(UTC).date()` achou **`get_budget_pacing`** (`days_elapsed = today.day` em UTC — no
ultimo dia do mes, das 21h a meia-noite, projeta o gasto mensal como se fosse de UM dia) e
**`get_negative_keywords_audit`** (janela `hoje-29..hoje` em UTC). Nenhum usa preset, por isso
escaparam da lista dos 22. Mesma classe, mesmo fix, testes proprios.

**Freshness, os rotulos finais:** `confiavel` · `ambiguo` · **`nao_coberto`** (ex-`atrasado`; o
texto admite lag OU conta parada) · **`em_curso`** (janela alcanca o dia corrente da conta) ·
`indeterminado`. **A ordem e contrato**, e o RED corrigiu o desenho antes do codigo sair: a
primeira versao decidia `nao_coberto` antes de `em_curso` em qualquer caso, e uma janela
*futura* sairia rotulada como "lag ou silencio" sobre dias que nao aconteceram. Ficou: janela
**alem** de hoje → `em_curso` primeiro; janela **ate** hoje → `nao_coberto` ganha (fronteira de
ontem e o fato mais grave), `em_curso` so com a fronteira ja em hoje.

**Guard novo, AST:** nenhum tool Google chama `datetime.now`/`date.today` — `hoje` vem da conta.
AST e nao grep porque os comentarios destes arquivos CITAM o padrao proibido. Na primeira
execucao ele pegou `import_offline_conversions.py` (→ F146) e o meu proprio `account_clock.py`
(bug do guard: o leitor legitimo estava na varredura; excluido com motivo e com teste proprio).

**Sabotagem, 7 variantes, 7/7 — na segunda rodada.** Na primeira foram 6/7: a variante que da
default `None` a `today` passou verde porque meu teste asseria `pytest.raises(TypeError)`, e
`None - timedelta` levanta TypeError **pelo motivo errado**. Tipo de excecao e o adjacente da
invariante; a invariante e "nao ha default", e o guard passou a asserir a **assinatura** por
`inspect`. Quarta ocorrencia do modo "assere o adjacente" neste projeto, todas minhas.

**Fora, de proposito:** `governance/rate_limit._today()` (bucket de quota — UTC e o correto) e os
3 tools Meta (fuso proprio no inventario Meta; a mesma classe la e outro finding).

## F146 (LOW, CORRIGIDO 03/09) — `import_offline_conversions` assume BRT fixo, e 2 contas sao UTC-4

> **✅ CORRIGIDO em 03/09** — ver o bloco *"F146 CORRIGIDO"* logo abaixo, que tambem **corrige o sentido do bug** descrito nesta entrada (o -03:00 fixo ADIANTAVA o carimbo em 1h, nao atrasava; o validador nunca rejeitou nada como futura).

Achado pelo guard AST do F141 na primeira execucao. `_validate_payload_shape` compara
`conversion_date_time` (interpretado como `-03:00`, hardcoded em `_BRT`) com `datetime.now(_BRT)`
para rejeitar conversao "no futuro" — e o tool inteiro **anexa `-03:00`** ao que envia ao Google
(docstring: "V4 BR-invariant"). Para `America/Campo_Grande` e `America/Boa_Vista` (UTC-4), uma
conversao das 23:30 locais vira 00:30 BRT: se ainda sao 23:45 em BRT, e rejeitada como futura; e
a que passa vai ao Google com offset errado em uma hora. **Erra alto (rejeita) ou erra o carimbo
(offset), nunca em silencio sobre janela** — por isso nao e F141, e outra classe: contrato de
upload assumindo um fuso que nem toda conta tem. O fix e usar `google_ads_accounts.time_zone`
(ja disponivel via `account_today`) tanto na validacao quanto no offset anexado. Nao entrou no
bloco porque muda o payload enviado ao Google e merece probe propria de importacao. Excecao
registrada com motivo no guard.


### ✅ F146 CORRIGIDO (03/09) — e uma correcao do proprio registro

**Primeiro, o que eu tinha escrito errado acima.** A entrada dizia que uma conversao das 23:30 em
Campo Grande "e rejeitada como futura". **E o contrario**, e foi um teste com controle que
derrubou a afirmacao antes do codigo sair: ler a hora de parede de UTC-4 como `-03:00` torna o
instante **1h mais cedo**, nao mais tarde. O validador nunca rejeitou nada como futura por isso;
o unico erro dele era fechar a janela de **90 dias** 1h antes. O dano de verdade sempre foi o do
builder: o carimbo ia ao Google **1h adiantado, em silencio** — uma conversao das 00:30 locais
caindo no dia anterior. Afirmacao de direcao sem probe e afirmacao errada; registrado em
[[afirmacoes-precisam-de-probe]].

**O fix.** O fuso vem de `google_ads_accounts.time_zone` (`account_clock.resolve_account_zone`,
que devolve o **nome** IANA ou `None` — sem fallback, porque quem decide e o chamador). O handler
resolve UMA vez no dry-run, valida com `tz` (kwarg obrigatorio, guard de assinatura), guarda
`__time_zone__` no payload pendente, e o **preview mostra `time_zone` e `utc_offset`** — o gestor
confirma sabendo o que vai ser enviado. O builder calcula o offset **por timestamp** a partir do
fuso (`%z`), em vez de anexar string fixa.

**Decisao registrada (Wellington, 03/09): conta sem fuso → recusa com erro claro.** No F141 o
fallback UTC valia porque era leitura; aqui e um MUTATE que grava timestamp em conta de cliente —
offset chutado e corrupcao de dado, nao ruido. Token pendente sem `__time_zone__` (criado antes
do deploy, TTL 10 min) → erro pedindo dry-run novo; nunca `-03:00` por baixo.

**Verificacao:** RED 6/6 (o controle no sentido errado falhou e foi corrigido — ver acima);
teste de integracao com DB pro `resolve_account_zone` (nome, `None` pra ausente/nulo/invalido);
sabotagem 6/6: builder volta ao fixo, builder cai em Sao Paulo sem fuso, validador ignora `tz`,
`tz` ganha default, handler cai em Sao Paulo, handler nao guarda o fuso no payload.

**Nao feito, de proposito:** probe real de upload. O formato enviado e a mesma forma de string
que `-03:00` ja usa em producao (`yyyy-mm-dd hh:mm:ss±hh:mm`), e um upload real empurraria uma
conversao falsa numa conta de cliente. A `currency_code=BRL` continua invariante — moeda e da
conta, nao do fuso, e as 25 sao BRL.


## F147 (MINOR, ABERTO) — a reconsulta pos-apply nao tem sentinela de truncamento, e agora precisa de uma

> **Como apareceu:** introduzido pelo proprio fix do Important 2 da revisao final (04/09), e
> pego pela re-revisao escopada no mesmo dia. Adjudicado como residuo: direcao fail-safe,
> arquivado em vez de virar um quinto commit de codigo na branch.

O §7 da spec exige confirmar remocao por `status == REMOVED` no registro alvo, nunca por
ausencia. O fix trocou a reconsulta de `apply_change` para `status="all"` — correto — mas
**criterios REMOVED persistem e continuam consultaveis**, que e a premissa do proprio §7.
Eles acumulam a cada reescrita da grade.

**A conta:** um lote de 20 campanhas cuja grade de 7 dias foi reescrita ~7 vezes chega a
~980 linhas. Em 1001 a leitura e cortada por `LIMIT`, e o `ORDER BY campaign.id, day_of_week,
start_hour` **nao agrupa por status** — entao linhas ENABLED podem ser descartadas.

**O sintoma:** `matches_requested: false` e `hours_per_week` subestimado, **sem nenhum sinal
de truncamento**. O T4 do proprio runbook classifica essa combinacao como achado HIGH.

**Por que e MINOR mesmo assim:** a direcao e fail-safe — produz alarme falso, nunca sucesso
falso —, nenhuma mutacao e afetada (a leitura e posterior a escrita), e o resultado aparece
na resposta em vez de ficar silencioso. O caminho de mutacao ja recusa grade truncada
(Important 4, `update_ad_schedule.py`); e so a confirmacao que ficou sem.

**Fix (uma ramificacao, espelhando o que ja existe):** em `apply_change.py`, na leitura de
confirmacao, `if len(rows) > GRADE_LIMIT:` preencha `confirmation_error` em vez de computar
`resulting` — mesma forma do guard em `update_ad_schedule.py:210`.

**Segundo item, do mesmo lugar:** `resulting_schedule[cid].windows` passou a carregar o
conjunto REMOVED historico inteiro da campanha, nao so as janelas que este apply removeu —
inchaco de resposta alem do que o §7 pede. Filtrar por `campaign_criterion.status IN
('ENABLED', 'REMOVED')` nao resolve (REMOVED antigo tambem casa); o corte util seria por
data de modificacao, que o `campaign_criterion` nao expoe. Fica registrado como custo
conhecido do §7, nao como fix pendente.


## F148 (HIGH, CORRIGIDO) — o dry-run de todo mutate always-CONFIRM e invisivel na trilha

> **Como apareceu:** medido em 04/09 durante o smoke 3b.42, quando a sessao MO-JP notou
> que os dois dry-runs de `update_ad_schedule` que planejavam 10 e 5 operacoes apareciam no
> `get_my_audit_log` como `action_type: read`, `target_count: 0`. A varredura seguinte
> mostrou que o buraco nao e da tool: e das 24.

**Escopo medido, nao estimado:** 24 tools em `src/mcp/tools/` chamam `create_pending`.
**Nenhuma delas grava linha de auditoria propria no caminho de dry-run**, e o
`create_pending` tambem nao. `create_pending` e ponto unico comprovado — `generate_token` e
chamado de um lugar so em todo o `src/` (`dry_run.py:73`) e o `INSERT INTO
pending_confirmations` existe so em `dry_run.py:77`.

**O que aparece hoje, quando aparece:** a linha da consulta GAQL que o preview fez, emitida
por `reports.py:177` com `action_type="read"` e `target_count=len(results)` — a contagem de
linhas **lidas**, nao de operacoes planejadas. Tool cujo dry-run nao le GAQL nao deixa linha
nenhuma.

**A inversao, que e o que faz disto HIGH.** `create_pending` chama `ensure_account_access`
com `level="write"`, e esse gate **audita so quando NEGA**: em `access.py` o `if allowed:
return` vem antes do bloco de audit, e o `action_type="mutate" if level == "write"` vive
dentro do ramo de negacao, com `status="denied"`. Resultado: a trilha guarda os previews que
**foram recusados** e perde todos os que **funcionaram**. A auditoria de tentativa de escrita
esta exatamente ao contrario — registra o que nao aconteceu, perde o que aconteceu.

**Cenario que fecha o argumento:** alguem gera 50 previews de `bulk_pause_by_query` numa
conta de cliente, todos autorizados, nenhum aplicado. A trilha tem **zero linhas**. Se o
acesso dessa pessoa tivesse sido revogado, teria 50. Token mintado e nunca aplicado nao
deixa rastro nenhum.

**Fix, em duas partes e nesta ordem — no `create_pending`, nao nas 24 tools.** O
`create_pending` ja tem o numero em escopo: **as 24 escrevem `__target_count__` no payload**,
sem excecao, e ja existe precedente de leitura assim em `apply_change.py:70`. Ele tambem ja
e `async` com `conn` na mao e ja faz um write no mesmo escopo, entao a linha de auditoria
cabe **na mesma transacao** — o que de quebra cobre o caso de o INSERT da pendencia passar e
a auditoria nao. Espalhar a gravacao pelas 24 seria o padrao que o F57 pune.

1. `create_pending` grava a propria linha, com o `target_count` **planejado**.
2. So entao uma coluna nova **nullable** `dry_run` distingue. Coluna nova, **nunca** valor
   novo em `action_type`: o enum e filtro publico de `get_my_audit_log`
   (`mutate|read|auth|system`) e mexer nele quebra consumidor.

**Cuidado na implementacao:** nao repita o default `1` do `apply_change` ao ler
`__target_count__`. Hoje as 24 preenchem, mas default silencioso e o que deixa a 25a passar
sem ninguem notar — ausente deve gravar NULL ou estourar, nunca "1 operacao" que ninguem
planejou. Migration aditiva, e o `CLAUDE.md` obriga full sweep com Docker.


> **✅ CORRIGIDO em 04/09, em duas partes — e a segunda so apareceu porque a primeira foi
> VERIFICADA EM PRODUCAO.**
>
> **Parte 1 (PR #33) — o registro.** `create_pending` passou a gravar a propria linha:
> `action_type: "mutate"`, `dry_run: true`, `target_count` **planejado** (lido do
> `__target_count__` que as 24 tools ja escreviam no payload). Fix em **sitio unico**, nao
> nas 24: `generate_token` e o `INSERT INTO pending_confirmations` existem so em
> `dry_run.py`, entao espalhar seria o padrao que o F57 pune. **Mesma transacao** que o
> INSERT da pendencia — pendencia sem trilha e o proprio defeito, entao as duas escritas
> vivem ou morrem juntas, e em colisao de token o savepoint desfaz as duas. Migration `007`
> aditiva: coluna **nullable**, nunca valor novo em `action_type`, porque aquele enum e
> filtro publico de `get_my_audit_log`. Sem default silencioso: `__target_count__` ausente
> grava NULL, jamais o `1` do `apply_change` — registrar uma operacao que ninguem planejou e
> pior que registrar que nao se sabe.
>
> **Medido em producao (7862230676, aval do Wellington):** antes, os dois dry-runs deixavam
> so `4065`/`4066`, `read` com `target_count: 0`, enquanto a resposta reportava 10 e 5.
> Depois, `4085` e `4087` com `mutate` e `target_count` 10 e 5. Perguntado "quantas mutacoes
> foram tentadas nesta conta", o log responde **2** em vez de zero.
>
> **Parte 2 (PR #35) — a leitura, que a Parte 1 deixou ambigua.** Uma mutacao **aplicada**
> grava os MESMOS valores que um preview em `action_type` e `target_count`. O
> `list_for_manager` seleciona 11 colunas fixas e a nova nao entrava nelas, entao pela tool
> os dois casos eram identicos. O unico diferenciador acidental era `duration_ms` NULL — que
> nao e sinal desenhado **e nao e exclusivo**: `admin_access_grant` tambem grava `mutate` com
> duracao nula, medido na mesma conta no mesmo dia. Num incidente a pergunta e exatamente
> "isso foi tentativa ou foi aplicado?". `dry_run` entrou no SELECT e no dict de retorno, e a
> description da tool passou a dizer o que o campo distingue, com o aviso de **nao** tentar
> distinguir por `duration_ms`.
>
> **Guards:** `test_create_pending_audita_dry_run.py` (4, com o guard do 25o call-site
> verificado por sabotagem contra diretorio sintetico), 2 de integracao no `test_dry_run.py`
> (round-trip da coluna e atomicidade, falhando a auditoria de proposito), e **os 8 testes de
> ciclo completo que o CI reprovou com `assert 2 == 1`** — eles codificavam a AUSENCIA da
> linha como se fosse contrato. Em vez de trocar 1 por 2, foram separados: o SELECT antigo
> ganhou `AND dry_run IS NOT TRUE` e cada um ganhou assercao sobre a linha de preview. Viraram
> guards do F148 em 8 fluxos de tool.
>
> **Licao de metodo:** o primeiro push saiu sem full sweep (Docker parado) e o CI achou as 8.
> A falha estava certa e era a prova do fix; mas foi o CI, nao eu, que a encontrou.


## F149 (MEDIUM, EM PRODUCAO — smoke 3b.44 pendente) — o unico jeito de mudar o bid_modifier de UMA faixa passa por um estado que interrompe a entrega

> **Como apareceu:** a analise da MO-JP em 04/09 concluiu lance por faixa horaria (JPA fora
> de hora com CPA 18,47 contra 19,87 no comercial; CAB fora de hora 24,46 contra 18,60 no
> fim de semana — sinal OPOSTO por campanha). A execucao esbarrou na superficie da tool.

**A assimetria e nossa, nao do Google.** Cada janela e um `campaign_criterion` proprio com
seu proprio campo `bid_modifier`, e o `get_ad_schedule` **le** modificador por linha. Mas no
`update_ad_schedule` o `bid_modifier` e **escalar no nivel da chamada**, e os itens de
`windows[]` so carregam dia e hora. A tool le um estado que nao consegue reproduzir.

**Os dois caminhos, medidos no codigo** (`diff_schedule`, `ad_schedule.py:142-145`):

- **Omitido** → a guarda `if bid_modifier is not None` deixa `to_update` vazio: **preserva
  todos**, nao permite mudar nenhum.
- **Informado** → toda janela presente nos dois conjuntos cujo valor difira entra em
  `to_update`: **muda todos**, inclusive os que nao eram alvo. Nao existe nocao de "janela
  que o chamador quis tocar" na assinatura.

**A armadilha: o caminho EXISTE, em duas chamadas — e e pior que ser inexprimivel.** Chamada
1 com so a faixa alvo e o modificador (a grade vira **so** essa faixa); chamada 2 com as 168
horas e o modificador **omitido** (a faixa alvo conserva o valor, as outras entram sem —
confirmado em `mutates/ad_schedule.py:41`, que so seta o campo quando nao e None). O
resultado liquido e o desejado. **Mas entre as duas a campanha serve ~50 de 168 horas**, e
as duas sao always-CONFIRM com token de 10 min e aval humano proprio. Se a segunda travar
— aval nao vindo, token expirado, sessao interrompida —, a campanha fica degradada; com
orcamento **compartilhado**, isso nao so corta a entrega dela como **inunda a irma**.

**E nao ha ordenacao segura.** Grade cheia primeiro faz o modificador cair nas 168; remover
e re-adicionar achata as 167. A unica sequencia que chega ao estado certo passa pelo
degradado.

> **✅ A METADE DE BUG FOI CORRIGIDA em 04/09 (PR #34) — o achatamento deixou de ser
> silencioso.** O preview nao dizia o que estava sendo perdido: `bid_modifier_updated` listava
> so dia e hora, e o resumo dizia "5 mudam bid_modifier". Agora cada entrada traz
> `bid_modifier_antigo` ao lado do `novo`, e o preview declara `cobertura`
> (`horas_antes`/`horas_depois`/`reduz`) **sem limiar** — qualquer % estaria errado em alguma
> conta. O destaque (`aviso_cobertura`) fica so para queda **com** orcamento compartilhado,
> porque queda sozinha aparece em quase todo primeiro uso (campanha sem grade serve 168 horas
> naturais) e alarme que aparece sempre ensina a ser ignorado. Nenhuma das partes precisou de
> query nova: `hours_per_week` ja saia do `summarize_current`, o modificador antigo ja estava
> no `CurrentWindow` que o proprio diff compara, e o `shared_budgets` ja vinha no preview —
> ninguem tinha escrito a frase que os soma.

> **✅ EM PRODUCAO em 2026-09-05 (PR [#40](https://github.com/BadWolf1509/v4-ads-mcp/pull/40), merge `0162017`, revisao `v4-ads-mcp-00092-sl2`) — a rota
> segura passou a existir.** `bid_modifier` por janela chegou em `windows[]`
> (Tasks 1-6, `.superpowers/sdd/2026-09-04-bid-modifier-por-janela/progress.md`):
> `Window` ganhou o campo como ATRIBUTO, nunca identidade (`key()` continua com
> 5 posicoes — se o modificador entrasse na chave, muda-lo recriaria o
> criterion e queimaria ~14 dias de re-learning, o mesmo custo que o
> `no_changes` existe para evitar); `diff_schedule` decide por janela, com o
> modificador DA JANELA vencendo o escalar da chamada (que vira default de
> quem nao trouxer o seu), regra centralizada em `modificador_efetivo` para
> nao repetir a familia do F81; `schedule_fingerprint` passa a cobrir o
> modificador (6a posicao) para a concorrencia otimista (Ruling 10) nao ficar
> cega justamente para uma mudanca so de lance. Uma UNICA chamada agora
> resolve o que antes exigia duas com o estado degradado (~50 de 168 horas)
> no meio — prova por teste em
> `test_muda_uma_faixa_sem_desligar_as_outras_em_UMA_chamada`
> (`tests/unit/test_update_ad_schedule.py`).
>
> **A revisao final da branch achou um Critical que a propria feature nova
> expunha, corrigido no mesmo commit desta entrada:** `bid_modifier` e
> `proto.FLOAT` (32 bits) no SDK v24 — o gestor grava `1.4` e o Google devolve
> `1.399999976158142` na proxima leitura. `diff_schedule` comparava por `==`,
> entao TODA chamada repetida pela rota nova nunca convergia — medido contra
> os proprios cenarios do runbook 3b.44 (T4, reenviar a mesma grade, e T5,
> janela com valor igual ao atual, falhavam). Fix: `bid_modifier_diverge`
> (`math.isclose(rel_tol=1e-6)`, `src/google_ads/ad_schedule.py`) — NAO
> aplicado em `schedule_fingerprint`, onde as duas pontas leem do Google pelo
> MESMO parser e igualdade exata e mais estrita e correta. Um Important junto:
> `matches_requested` (a confirmacao pos-apply que existe porque a UI do
> Google ja falhou em silencio duas vezes nesta conta) comparava so a
> IDENTIDADE da faixa, nunca o bid_modifier — a UNICA coisa que este sprint
> acrescentou nao entrava na checagem que prova que a mutacao bateu com o
> pedido. Fix: `windows_bid_modifiers`, chave paralela a `windows` no payload
> pendente, e `matches_requested` passa a comparar os dois, com a MESMA
> tolerancia.
>
> **Guards:** 10 testes novos entre `test_ad_schedule_domain.py`,
> `test_update_ad_schedule.py`, `test_apply_change_ad_schedule.py` e
> `test_get_ad_schedule.py` (1621 no total da suite unitaria, verde) — inclui
> o par que prova a tolerancia nos dois sentidos (float32 nao reabre update;
> diferenca real >= 0,01 continua abrindo) e o par que prova
> `matches_requested` nos dois sentidos (mismatch vira `false`; ruido de
> float32 continua `true`).
>
> **O que FICA de fora:** o **smoke 3b.44 contra conta real**
> (`docs/operacao/phase-3b-44-bid-modifier-smoke.md`, T1-T7) segue `⬜ pending`
> — precisa do Wellington autorizando cada rodada de mutacao NA PROPRIA SESSAO
> que executa (medido em 04/09 no 3b.42/3b.43: aval relayado por sessao-par
> nao passa no classificador de auto mode). A cobertura acima e SO unitaria;
> nao leia esta entrada como "verificado em producao" ate o smoke rodar.


## F150 (HIGH, CORRIGIDO) — `update_ad_schedule` previa e nao aplicava: o builder nunca registrou

> **Como apareceu:** no **T4 do smoke 3b.42**, em conta real, com a tool **ja em producao**
> desde o PR #31. A sessao MO-JP parou a cadeia ali em vez de seguir para T5-T8.

`apply_change` devolvia ao gestor **apenas** `"Erro interno ao executar a ferramenta. O time
foi notificado."`. A mensagem real so existia no audit log: `No mutate builder registered for
'update_ad_schedule'`. Falhou em **100 ms**, sem `provider_request_id` — nunca chegou na API
do Google. **A conta ficou intacta**, sem mutacao parcial, verificado por `get_ad_schedule`
com `status="all"`.

**Causa: uma lista paralela mantida a mao divergiu.** `import_all_builders` tinha 11 imports
escritos um a um, e `mutates/ad_schedule.py` nao estava entre eles. O modulo existe e declara
`@register_builder("update_ad_schedule")` corretamente — mas ninguem o importava, entao o
decorator nunca rodava e a chave nunca entrava no `_BUILDERS`. Diferenca de conjuntos: **12
modulos no pacote, 11 na lista, e o unico de fora era o unico sem builder**.

🔴 **Por que passou por TUDO — e esta e a parte que importa.** O sprint teve 10 tasks com
review por task, uma revisao final da branch inteira e uma re-revisao escopada. **As tres
passaram por cima disto.** Nenhum teste exercitava o caminho de apply desta tool, e T1, T2,
T2b, T3 e T9 passam inteiros sem toca-lo. A razao e estrutural: **toda revisao olha o codigo
ESCRITO, e o defeito era codigo AUSENTE num arquivo que ninguem estava revisando.** Diff-based
review nao ve a linha que nao existe em arquivo que o diff nao toca.

**Fix no padrao, nao na instancia (PR #36).** Acrescentar a linha faltante resolveria hoje e
reabriria no proximo builder. `import_all_builders` passa a **varrer o pacote** com `pkgutil`:
lista paralela mantida por memoria humana diverge, e a unica fonte que nao diverge do pacote e
o proprio pacote. E o `contextlib.suppress(ImportError)` — que engolia falha de import **sem
rastro**, a outra metade do problema — virou `log.exception`, alertavel. Falha de um modulo
continua nao derrubando os outros.

**Guard de propriedade:** `test_builders_todos_registrados.py` le o PACOTE por AST, extrai
toda chave de `@register_builder("x")` e exige que cada uma chegue ao `_BUILDERS`. Le do
**fonte** de proposito: comparar o registry consigo mesmo nao provaria nada. Builder novo
nasce coberto sem ninguem lembrar de inscrever. Verificado por sabotagem. 25 builders (eram 24).

**Licao transferivel, e vale alem desta tool:** *shippar caminho de escrita sem smoke que o
exercite e shippar sem saber se ele funciona.* Revisao de codigo nao substitui execucao — o
smoke achou em uma tarde o que tres camadas de revisao nao acharam, porque ele **roda** em vez
de ler. O corolario pratico: nenhum sprint de tool mutante deveria fechar com o passo de apply
em `⬜ pending`.


## F151 (HIGH, CORRIGIDO) — o preview dizia que `clear_schedule` ZERA a entrega, e ele a RESTAURA

> **Como apareceu:** no **T8 do smoke 3b.42**, o ultimo passo — e o que quase ninguem testa
> porque "e so desfazer". A mutacao estava correta; o preview e que mentia. Bug introduzido
> pelo PR #34, do mesmo dia.

Com `clear_schedule: true` a grade desejada e vazia, e o bloco `cobertura` calculava
`hours_per_week([])` = **0**. Mas grade vazia significa **SEM AGENDA, logo 24x7, logo 168** —
a semantica em que a tool inteira se apoia (`summarize_current([])` devolve `168.0`;
`covers(None, ...)` e sempre verdadeiro). O `cobertura` era o **unico lugar** onde ela nao
estava aplicada.

**A resposta se contradizia sozinha:** o preview dizia `50.0 -> 0, reduz: true` enquanto o
`resulting_schedule` **da mesma resposta** trazia `hours_per_week: 168.0`.

**Por que HIGH e nao cosmetico — e inversao de proposito.** O `cobertura` existe para que
ninguem desligue entrega sem ver. Na **UNICA operacao que RESTAURA entrega**, ele anunciava
perda total. Um gestor leria "vai para 0 horas/semana" e concluiria que `clear_schedule`
desliga a campanha — o oposto do que a descricao da tool diz —, e o efeito pratico e afastar
da rota de restauracao eleita como preferida (Ruling 11).

**Era pior que o relato:** o terceiro teste do fix mostrou que a rota de restauracao tambem
disparava o `aviso_cobertura`, o destaque que fala em **REALOCACAO de gasto** para as
campanhas irmas. Descrevia o contrario do que o passo faz.

> **✅ CORRIGIDO em 04/09 (PR #37).** No caminho `clear_schedule`, `horas_depois` e `168.0` e
> `reduz` e falso. Condicao **explicita** (`limpar`), nao inferencia pelo vazio: `windows` tem
> `minItems: 1` e o pre-flight exige um dos dois, entao `desired == []` so acontece via
> `clear_schedule` — e inferir pelo vazio e justamente a ambiguidade que gerou o bug. Tres
> testes, RED observado nos tres.

🔑 **Simetria com o F150, achado no mesmo dia, horas antes:** os dois sao **ausencia de
tratamento de um caminho**. La o `ad_schedule` fora da lista de imports; aqui o
`clear_schedule` fora do calculo de cobertura. E os dois passaram por revisao, porque
**revisao le o que esta escrito**. O corolario ficou no `Don't do`: sprint de tool mutante nao
fecha sem exercitar o caminho de APPLY **e** o de RESTAURACAO.

---

## F152 (LOW, CORRIGIDO EM PARTE) — o rotulo por-op afirmava um verbo que a camada nao conhece

> **Como apareceu:** observado no T7 e T8 do smoke 3b.42.

`mutations.py:115` grava `{"index": idx, "status": "added", "error": None}` para **toda**
operacao bem-sucedida, seja ela `add`, `update` ou `remove`. No T7 (update via field mask) e
no T8 (remove) os itens vieram todos como `"added"`.

**Nao ha bug de numero:** `applied_count` e `sum(... if r["status"] == "added")`, e como todo
sucesso recebe esse rotulo, a contagem esta certa. O defeito e de **nome**, em dois eixos: o
rotulo por item nao descreve a operacao, e o campo se chama `partial_failures` mas carrega
tambem os sucessos — a familia do rotulo que embute veredito (F133).

**Por que NAO foi corrigido junto do F151:** o caminho e **compartilhado pelos 25 builders**, e
mudar o rotulo exigiria mexer tambem no calculo de `applied_count`. Isso muda a forma da
resposta de **toda** tool de mutacao — contrato de consumidor. Nao entra de carona num fix
pontual; precisa de decisao propria.

> **✅ CORRIGIDO em 04/09 (PR #38), em produção na revisao `v4-ads-mcp-00090-qst`.** O rotulo
> por-op passou a ser **`"success"`**, neutro, e o `applied_count` passou a contar *"nao
> falhou"* em vez de casar o verbo antigo — chavear no verbo amarrava a contagem a um rotulo
> que nao descrevia metade das operacoes.
>
> **Por que NEUTRO e nao o verbo certo (`added`/`updated`/`removed`).** O `oneof` da RESPOSTA
> do Google diz sucesso/falha e o tipo do recurso — **nunca o verbo**. Create, update e remove
> so se distinguem do lado da REQUISICAO. Emitir o verbo aqui exigiria correlacionar resposta
> com request op a op, e a camada generica passaria a **afirmar algo que nao observa**. Rotulo
> neutro e o que esta camada sustenta.
>
> **Nada se perdeu.** As tools que querem verbo de dominio ja remapeiam sozinhas via
> `classify_partial` (`add_keywords`, `add_negatives_from_search_terms`, `apply_audience`), e
> elas leem o campo **`error`**, nunca este `status` — verificado nos call-sites ANTES de
> mexer. O unico consumidor real do rotulo era o `applied_count`, dentro do proprio
> `mutations.py`. Full sweep 7/7: nenhuma das 25 tools de mutacao quebrou, que era a pergunta.

> 🔴 **RENOMEACAO DO CAMPO: considerada e RECUSADA em 04/09 — nao reabrir sem argumento novo.**
> A outra metade do finding era que o campo se chama `partial_failures` e carrega sucessos.
> Custo medido: **40 referencias em 14 arquivos**, num caminho compartilhado pelos **25
> builders**, e a mudanca altera a forma da resposta de **toda** tool de mutacao — contrato de
> consumidor. Ganho: trocar um nome ambiguo por outro. O nome tem leitura defensavel: ele
> nomeia o **MODO** (o relatorio por-op do partial-failure mode), nao o conteudo. O que
> faltava era o docstring dizer isso, e agora diz. Se a renomeacao voltar a mesa, e PR
> proprio, com o objetivo escrito antes.

**Nota vizinha, sem ID (comportamento do Google, nao defeito nosso):** `bid_modifier` volta em
precisao **float32** — pedir `1.1` devolve `1.100000023841858`. Quem comparar `== 1.1` falha.
Segue como candidata a frase na description da tool; e doc, nao codigo.

---

## F153 (HIGH, CORRIGIDO em 2026-09-05) — a correcao do F91 reabriu o F91, e o guard do F91 continuou verde

> **Como apareceu:** na re-revisao da onda de fix da branch `feat/gate-google`, medido com
> probe (`_FakePool`), nao deduzido. Nenhuma das tres revisoes anteriores da mesma branch
> pegou — porque o defeito **nao existia** quando elas rodaram: ele foi introduzido pela
> correcao de um achado delas.

**O que aconteceu.** Uma revisao apontou que a mensagem de negacao do gate Google
(*"peca ao admin pra liberar no painel"*) e conselho impossivel quando a causa e
`is_active = false` — a conta nem aparece na matriz do painel. A correcao acrescentou, no
caminho de negacao, uma leitura para escolher a mensagem certa:

```python
account = await google_ads_accounts.get_by_customer_id(conn, customer_id)
```

Ela ficou **depois** do audit protegido por `best_effort`, mas **dentro** do mesmo closure
que os seis call-sites passam a `connection.run_with_reconnect(...)`. Como
`asyncpg.PostgresConnectionError` esta em `_DROPPED_CONNECTION_ERRORS`, uma conexao morta ali
faz o retry **re-executar o closure inteiro** — inclusive o `INSERT` do audit que ja tinha
tido sucesso.

**Medido, nao inferido:** `audit_log.record` chamado **2x** numa unica negacao; e se a leitura
continuasse falhando, escapava `ConnectionDoesNotExistError` em vez de
`AccountAccessDeniedError` — **negacao limpa virando 500**. Exatamente o que o comentario tres
linhas acima afirma impedir (*"`best_effort` mantem o retry restrito ao read"*).

**🔑 O que faz isto merecer ID proprio, e nao e o bug.** Sao tres coisas, e a terceira e a que
vale para alem deste caso:

1. **A regressao foi introduzida por uma correcao.** As revisoes do codigo original passaram
   — corretamente. O defeito nasceu na onda de fix, que e a fase em que a atencao ja
   afrouxou porque "so estamos fechando achados".
2. **O guard do F91 continuou VERDE.** `test_audit_de_negacao_nao_e_retentado` existe
   justamente para provar que a negacao nao e retentada. Ele nao ficou vermelho porque a
   mesma onda de fix **lhe acrescentou um mock de `get_by_customer_id`** — ou seja, o guard
   foi contornado pela propria mudanca que quebrou a invariante dele. Guard nao e barreira
   quando quem passa por ele pode ajusta-lo no mesmo commit.
3. **A causa raiz era duplicacao de estado.** O `except` repetia
   `_DROPPED_CONNECTION_ERRORS` como tupla literal. Duas fontes de verdade do mesmo dado: no
   dia em que a constante ganhasse um membro, o `except` ficaria para tras **em silencio** e o
   F91 reabriria sem nenhum teste vermelho. E o teste 2 do "padrao de solucao" do `CLAUDE.md`.

**A regra que sai disto, e e mais estreita que "cuidado com retry":** codigo acrescentado
**depois** de um bloco `best_effort`, dentro de um closure que sera retentado, e tao perigoso
quanto codigo dentro dele. O `best_effort` protege o que esta *nele*, nao o que vem *depois*.

> **✅ CORRIGIDO** ([PR #45](https://github.com/BadWolf1509/v4-ads-mcp/pull/45), merge
> `8ad7689`, revisao `v4-ads-mcp-00098-tgs`). A leitura ficou em `try/except`, com `else:`
> escolhendo a mensagem especifica so quando ela de fato respondeu — sem resposta, cai na
> mensagem generica, porque **negar com menos detalhe e infinitamente melhor que quebrar**. O
> `except` passou a **importar** a constante em vez de repetir a tupla.
>
> **Guards, e sao dois porque um so nao fecharia:**
> `test_leitura_de_conta_apos_negacao_nao_e_retentada` cobre o comportamento (verificado
> vermelho contra o pre-fix: `audits=2` e `ConnectionDoesNotExistError` escapando); e
> `test_retentaveis_de_conexao_tem_uma_fonte_de_verdade_so` cobre a estrutura, varrendo **todo
> `src/`** — nenhum `except` fora do `connection.py` pode mencionar por nome uma classe que
> esta na constante. O estrutural existe porque **nenhum teste de comportamento distingue as
> duas formas**: as tuplas eram identicas, entao a unica propriedade afirmavel e "a lista nao
> esta escrita duas vezes". Verificado por sabotagem: com o `except` de volta a tupla literal
> ele aponta `src/google_ads/access.py:105`.
>
> **O que fica de fora:** o guard estrutural nao alcanca `except Exception` generico nem
> captura montada dinamicamente. Cobre a forma que causou este bug, nao a classe inteira.

---

## F154 (MEDIUM, ABERTO) — `/me/adaccounts` nao e prova de alcance, e a fila do painel trata como se fosse

> **Como apareceu:** em 2026-09-05, ao conferir a revogacao das 09:00Z, usei a
> `CA - V4 Lima Soares` como **controle** — ela devia estar intacta, e estava. Mas a
> chamada devolveu `success` **com dados reais** (R$ 11,55 de gasto, 955 impressoes),
> enquanto o inventario marcava `su_reachable: false`, sincronizado no mesmo dia as 09:00.

**A contradicao, medida em duas contas:** `act_1903626271072552` (CA - V4 Lima Soares) e
`act_1428319651342125` (CHUTE 07) estao as duas com `su_reachable = false` — e as duas
devolvem `meta_get_account_overview` com `status: success`. O system user **le as duas**.

**De onde vem cada lado.** `su_reachable` e escrito por `set_reachable`
(`src/jobs/meta_resync.py`) a partir de `reachable_ids`, que sao os ids devolvidos por
**`/me/adaccounts`**. A leitura de insights, por outro lado, usa o token do SU direto contra
a conta. Ou seja: o sinal responde *"esta conta aparece no inventario proprio do SU?"* e o
painel o apresenta como *"o SU alcanca esta conta?"*. **Nao sao a mesma pergunta**, e estas
duas contas provam que a primeira pode ser `nao` com a segunda sendo `sim`.

**A consequencia e concreta:** a fila **"Sem o system user atribuido"** de
`/admin/accounts/meta` existe para dizer ao admin *"va no Business Manager e atribua o SU"*.
Para estas duas contas esse conselho **nao tem o que fazer** — o SU ja le. O admin vai ao BM,
nao encontra nada errado, e a fila continua acusando. Alarme que pede acao impossivel ensina
a ignorar a fila inteira, que e o oposto do que ela existe para fazer.

🔑 **E isto reinterpreta uma medicao de 20/08 que fundou o desenho.** O registro daquele dia
diz: *"a edge do BM devolveu 25 contas e `/me/adaccounts` 23"*, e a diferenca foi lida como
**duas contas sem o SU atribuido**. Se `/me/adaccounts` simplesmente sub-reporta, a leitura
foi errada desde o inicio — nao eram duas contas sem atribuicao, eram duas contas que aquela
edge nao lista. O numero `2` de `unreachable` que o reconciliador reporta todo dia desde
08-21 e, com grande probabilidade, o mesmo artefato.

**O que NAO foi descartado, e e o confundidor honesto:** nao da pra provar que ninguem
atribuiu o SU as duas contas entre 09:00 e 17:50 de 05/09. O que enfraquece essa hipotese e
serem **duas ao mesmo tempo**, e a diferenca de 20/08 apontar na mesma direcao ha duas
semanas. Uma re-sincronizacao manual seguida de nova leitura resolveria de vez: se
`su_reachable` continuar `false` com a leitura funcionando, o confundidor cai.

**Fix candidato, nao decidido:** trocar a fonte do sinal de *"aparece em `/me/adaccounts`"*
para *"uma leitura minima contra a conta responde"* — mais caro (uma chamada por conta), mais
verdadeiro, e alinhado ao que o painel promete. Alternativa barata: manter o sinal e mudar o
texto da fila, de *"Sem o system user atribuido"* para *"Fora do inventario proprio do SU"*,
que e o que ele de fato mede. **A escolha muda o contrato do painel e e do Wellington.**
