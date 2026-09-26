> **Relatório bruto** de um dos 5 agentes da varredura de 21/09 — recorte: contratos da camada Meta.
> Recuperado do transcript da sessão em 25/09 e reproduzido **sem edição**. Os status
> ("CONFIRMADO", "PLAUSÍVEL") são do agente, não verificação nossa; o destino de cada
> achado está no [índice](README.md).

---

I have enough verified material. Here are the findings.

## Ranked findings — Meta Ads layer

All SDK claims below are from `facebook_business` **25.0.2** as installed at `C:\Users\welli\AppData\Local\Programs\Python\Python313\Lib\site-packages\facebook_business`, read with `inspect.getsource`. Nothing touched graph.facebook.com.

---

### 1. CRITICAL — CONFIRMED. The system-user token travels in the query string on every SDK call, and any connection-level failure puts it verbatim into the error the gestor, the logs and `audit_log` all receive.

`D:\v4-ads-mcp\src\meta_ads\client.py:53` → `D:\v4-ads-mcp\src\meta_ads\errors.py:63` → `D:\v4-ads-mcp\src\meta_ads\reports.py:179,191,199,202` → `D:\v4-ads-mcp\src\mcp\tools\_meta_common.py:27`

**Assumed:** we hand the token to the SDK and it authenticates. The repo's own F82 invariant, written at `src/meta_ads/graph.py:36`, is *"token no HEADER, nunca na query: quem lê a URL num log contorna tudo."*

**Real,** `facebook_business/session.py`, `FacebookSession.__init__`:
```python
params = {'access_token': self.access_token}
if app_secret:
    params['appsecret_proof'] = self._gen_appsecret_proof()
self.requests.params.update(params)
```
The token and the appsecret_proof are baked into `requests.Session.params`. There is no opt-out: `FacebookAdsApi.call` never removes them (verified — the string `access_token` does not appear in its body), and its `headers=` argument is additive. I instantiated the real object via `build_meta_api` and read back `{'access_token': 'SU_TOKEN', 'appsecret_proof': '45246b96…'}`.

**What breaks.** `errors.py:63` is the fallback for anything that isn't a `FacebookRequestError` — i.e. every `requests`/`urllib3` transport failure — and it interpolates `str(e)` raw. I proved the leak on loopback only (`127.0.0.1:9`, never Meta): a sentinel token placed in `Session.params` comes back inside `str(ConnectTimeout)` and survives both `to_friendly_meta_error` and `meta_error_message`:

```
Erro inesperado: HTTPConnectionPool(host='127.0.0.1', port=9): Max retries exceeded with url:
/v22.0/act_123/insights?access_token=SYSTEM_USER_TOKEN_SENTINEL&amp;appsecret_proof=PROOF_SENTINEL&amp;level=campaign
```

Scenario: one egress hiccup on Cloud Run during `meta_get_ad_performance`. That string goes three places at once — `log.warning(error=friendly.message)` → Cloud Logging; `audit_log.record(error_message=…)` → a Postgres `TEXT` column (`001_initial_schema.sql:82`); and the tool's error envelope → the LLM's context and the chat transcript. It is the never-expiring token for ~24 ad accounts. Whoever reads any of the three bypasses `can_manager_access` entirely — the matrix the repo documents as the *only* freio in Modelo B.

**Why it hid.** F82 was closed on one of the two paginations. `tests/unit/test_meta_secret_leak.py` asserts the invariant exclusively against `src/auth/meta_oauth.py` and `graph.py` (httpx). The SDK path — used by all five performance tools — kept the exact defect F82 was about. No redaction exists anywhere: `src/logging.py:69-70` only silences the `httpx`/`httpcore` loggers, which are not involved here.

**Secondary, latent:** that same test's docstring records probe result (D) — *authenticating by header, Graph stops embedding the token in `paging.next`*. The contrapositive is that on the SDK path (query-param auth) `paging.next` **does** carry the token, so `reports.py:165` passes a token-bearing URL as `path`, and `FacebookRequestError.__str__` prints `"  Path:    %s"`. Dormant only because `_MAX_PAGES == 1`.

**Guard that would have caught it:** drive `run_meta_graph_get` against a real `FacebookSession`-backed api whose transport raises a `ConnectionError`, and assert a sentinel token is absent from the friendly message, the `audit_log.record` kwargs, and the log event. Asserting on `friendly.message` alone is not enough — the audit write is a separate sink.

---

### 2. HIGH — CONFIRMED. No HTTP timeout on any Graph call. A hung socket pins a worker thread forever.

`D:\v4-ads-mcp\src\meta_ads\client.py:53`

**Assumed:** the SDK has a sane default timeout. **Real:** `FacebookSession.__init__(self, app_id=None, app_secret=None, access_token=None, proxies=None, timeout=None, debug=False)` stores `self.timeout = timeout`, and `FacebookAdsApi.call` passes `timeout=self._session.timeout` straight to `requests`. `client.py:53` never passes one. Read back off the live object: `api._session.timeout` is `None`. `requests` with `timeout=None` blocks indefinitely.

**What breaks.** `reports.py:174` offloads through `run_blocking` → `anyio.to_thread.run_sync`, whose default capacity limiter is a fixed, small pool shared process-wide. A stalled Graph connection holds one slot with no cancellation path — you cannot interrupt a blocked `requests` socket read from the event loop. Enough of them and every blocking call in the instance starves, **including the five Google executors**. The `asyncio.timeout(5)` that `src/blocking.py:15-19` describes for deep health does not cover this: the coroutine is parked waiting on a thread, not on I/O.

The contrast is in the repo: the httpx Meta call sites set it explicitly — `src/auth/meta_oauth.py:256` and `:535`, both `httpx.AsyncClient(timeout=30.0)`. Same class of call, opposite posture, because one went through the SDK and the SDK's default was never read.

---

### 3. HIGH — CONFIRMED. `FacebookAdsApi.call` does not raise on 5xx with a non-JSON body, and `cast(dict, resposta.json())` is a runtime lie.

`D:\v4-ads-mcp\src\meta_ads\reports.py:166,168`

**Assumed:** `call()` raises on failure, so whatever comes back is a dict. **Real,** `FacebookResponse.json()`:
```python
def json(self):
    try:
        return json.loads(self._body)
    except (TypeError, ValueError):
        return self._body      # ← the raw string, verbatim
```
and `is_success()` on a *str* body skips the `Mapping` branch, hits `elif bool(json_body)`, then returns `'Service Unavailable' not in json_body` — a substring test that is True for an HTML error page. So `is_failure()` is False and `call()` returns normally. `typing.cast` is a no-op at runtime: mypy is satisfied, the interpreter is not.

Measured against the real SDK classes (no network):

| body | `call()` | then `corpo.get("data")` |
|---|---|---|
| 502, HTML containing "error" | does **not** raise, `json()` → `str` | `AttributeError: 'str' object has no attribute 'get'` |
| 503, clean HTML | does **not** raise, `json()` → `str` | same |
| 200, HTML containing "success" | raises `TypeError: string indices must be integers` **from inside the SDK** | — |

**What breaks.** Any intermediary error page — LB/CDN 502, proxy, captive network — reaches the gestor as `"Erro inesperado: 'str' object has no attribute 'get'"`, with `retryable=False`, so a transient upstream failure is presented as permanent. It also routes straight into finding #1's leaky branch.

Adjacent, same read: a Graph JSON error body lacking the `error` key yields `"Erro Meta API (None/None): None"` (`errors.py:59`), because `FacebookRequestError.__init__` only populates the codes under `if self._body and 'error' in self._body`.

**Fix direction:** validate shape at the boundary (`if not isinstance(corpo, dict): raise` naming the HTTP status), don't `cast`.

---

### 4. MEDIUM-HIGH — divergence CONFIRMED, correct side PLAUSÍVEL. Two modules read the same three Graph fields by three different rules, for the same account.

| field | `src/meta_ads/insights.py` | `src/meta_ads/account_overview.py` |
|---|---|---|
| `purchase_roas` | `:152` — `roas_list[0].get("value")`, blind index 0, ignores `action_type` | `:143-147` — filters `action_type in ("purchase","omni_purchase")` |
| `ctr` | `:180` — `float(ctr) / 100` → decimal fraction | `:77` — raw, no division |
| conversions | `:184,187` — counts only `purchase` and `lead` | `:10-19` + `:139-140` — **sums** `purchase` + `lead` + `complete_registration` + the three `offsite_conversion.fb_pixel_*` variants |

The divergence itself is confirmed by reading both files; they cannot both be right. The `ctr` one is the sharpest: `meta_get_account_overview` and `meta_get_campaign_performance` both emit a key named `ctr`, for the same account and window, differing by 100×, with no unit in the key to catch it. The conversions one is worse if Meta's `actions` array carries overlapping rollups — then the overview double- or triple-counts what the campaign tool counts once.

Minor, same family: `int(...)` at `insights.py:184,187` and `account_overview.py:81` **truncates** rather than rounds — 2.9 purchases reports as 2.

**PLAUSÍVEL half — exactly one probe answers all three.** One call, `/act_&lt;id&gt;/insights`, `level=account`, `fields=actions,action_values,purchase_roas,ctr`, 30-day window on an account with purchases, and **dump the raw arrays, not the parsed output**: (a) how many entries `purchase_roas` has and their `action_type`s; (b) whether `purchase` and `offsite_conversion.fb_pixel_purchase` coexist with identical `value`; (c) the magnitude of `ctr` against a CTR you read in Ads Manager. Then repeat at `level=campaign` over the same window — if summing campaign rows does not equal the account row, the taxonomy is why.

---

### 5. MEDIUM — absence CONFIRMED, impact PLAUSÍVEL. The attribution contract is entirely implicit.

`D:\v4-ads-mcp\src\meta_ads\insights.py:110-131` and `D:\v4-ads-mcp\src\mcp\tools\meta_get_account_overview.py:128-144`

A grep over all of `src/` returns **zero** hits for `action_attribution_windows`, `use_unified_attribution_setting`, and `action_report_time`. Every `/insights` call omits all three.

**Assumed:** Meta's defaults are what the gestor sees in Ads Manager. **Real:** unstated, and not the same question — `action_report_time` (impression time vs conversion time) decides which *day* a conversion lands in, which directly moves a window-bounded report. So `purchases`, `purchases_value_brl` and `purchase_roas` may not reconcile with Ads Manager, and can shift without a code change on our side.

**Probe:** the same `/insights` call three times over one fixed window — as today; with `use_unified_attribution_setting=true`; with `action_report_time=conversion`. If any differ, the tools are reporting a window Meta chose rather than the one the gestor sees; pin it explicitly and say so in the tool description. This is the F53/F54/F55 shape precisely — a param the API accepts quietly either way, so a 200 proves nothing.

---

### 6. MEDIUM — PLAUSÍVEL. `reach`/`frequency` under breakdowns: an absent field becomes a measured-looking `0`.

`D:\v4-ads-mcp\src\meta_ads\insights.py:182-183`

`_COMMON_INSIGHTS_FIELDS` (`:37-48`) requests `reach` and `frequency` at every level, and `meta_get_performance_breakdown` adds `breakdowns` on top (`meta_get_performance_breakdown.py:144`). The parser does `int(row.get("reach") or 0)` — confirmed local behavior: a field Meta omits is indistinguishable from a field Meta measured as zero. Meta restricts unique metrics under some breakdowns; if it omits rather than erroring, the tool fabricates zeros. The code already admits the gap — `insights.py:26-28` marks `device`/`geo` as *"PROVISIONAL v0 … o smoke per-valor é o gate antes do ship."*

**Probe — four calls, one per enum value,** same account and window: `/act_&lt;id&gt;/insights?level=campaign&amp;fields=spend,reach,frequency&amp;breakdowns=&lt;publisher_platform|impression_device|country|hourly_stats_aggregated_by_advertiser_time_zone&gt;`. For each, the question is not "did it 200" but **are `reach` and `frequency` present in the row's keys**. Absent-on-200 is the dangerous outcome and only raw key inspection shows it.

---

### 7. MEDIUM — CONFIRMED. The BUC throttle signal records "unknown" as a measured `0`, and the app-level quota is never read at all.

`D:\v4-ads-mcp\src\governance\rate_limit.py:173-212,233,246-252`

`_parse_buc_header_pct` returns `0` on three distinct unknown paths — malformed JSON (`:190`), non-dict (`:193`), and no key matching the account (`:212`, empty `pcts`) — and `record_actual_meta` persists that via `update_throttle(throttle_pct=0)`, indistinguishable from a genuinely idle account. It can overwrite a previously recorded high value. This is the repo's own named anti-pattern applied to the one signal that warns the **shared** token is about to be throttled for all 24 accounts.

Second half, and a direct echo of F110 ("não reportar quota sem dizer qual quota; a menor é a que barra"): only `x-business-use-case-usage` is read. Meta's app-level `x-app-usage` — the other quota on the same shared app — is not read anywhere in `src/`.

Adjacent and outside my assigned area: `:235` uses `date.today()`, the **server** clock, to bucket the counter, while `src/meta_ads/account_clock.py::resolve_meta_account_today` exists precisely to avoid that (F141's Meta twin). The AST guard `test_no_server_clock_in_google_tools.py` exempts `meta_*` by design, so nothing catches it.

---

### 8. MEDIUM — CONFIRMED structural, latent today. The gate's subject is not tied to the request's target.

`D:\v4-ads-mcp\src\meta_ads\reports.py:86-90` vs `:156`

The hard-gate runs against the `ad_account_id` kwarg; the request goes to `edge`. Nothing ties them. All three current callers derive both from the same variable, so today they agree — but F72 made `ad_account_id` *mandatory*, not *authoritative over the URL*. A future tool whose edge is `/{campaign_id}/insights` or `/{business_id}/owned_ad_accounts`, or one that takes the edge from an argument, gates account A and reads account B, on a token that reaches ~24 accounts.

The gate tests (`tests/unit/test_meta_reports_gate.py:36-38`, `:70`, `:116`) always pass a matching pair, so they stay green through exactly that change. This is the F57 shape one level up: the invariant that would hold — *the account the gate approved is the account in the URL* — is nowhere stated. Cheap guard: assert `ad_account_id` occurs in `edge` (or derive the gate subject **from** the edge), plus a unit test passing a divergent pair and expecting a raise.

Related: after the F189 fix, `:165` sends the request to a URL lifted from Meta's response body, with no relation to the gated account. Dormant because `_MAX_PAGES == 1`.

---

### 9. LOW — CONFIRMED. `_brl` hardcoded into metric keys on a multi-currency inventory.

`src/meta_ads/insights.py:179,181,185` emit `spend_brl`, `cpc_brl`, `purchases_value_brl`, while `_meta_performance.py:148` and `meta_get_performance_breakdown.py:183` return the account's *real* `currency` as a sibling. The system knows currency varies — it's a column, `partnership.py:22` fetches it, `meta_list_my_ad_accounts` returns it — yet the metric keys assert BRL. A USD account yields `spend_brl: 1200` next to `currency: "USD"`, and an LLM reading the key name will report reais.

### 10. LOW — CONFIRMED. Stray `ad_account_id` query param survived the Task 3.4 cleanup.

`meta_get_account_overview.py:143` and `:167` still put `"ad_account_id": ad_account_id` into the Graph `params` dict. `build_insights_call` had this removed and `insights.py:96-103` documents why; the overview tool builds its params by hand and kept it. Harmless in practice, but it is a param sent to an external API that nobody verified is ignored, and it contradicts a documented cleanup.

---

### Meta-observation: two paginations, and only one is ever fixed

`src/meta_ads/graph.py` (httpx, header auth, token never in the URL, explicit `complete` flag) and `src/meta_ads/reports.py:148-172` (SDK, query-string auth, last-page `paging` as the truncation signal) are the same mechanism twice. F82 fixed one; F189 fixed the other; finding #1 is the third instance of that split, and #2 is a fourth (the httpx sites set `timeout=30.0`; the SDK site cannot). Consolidating reads onto the httpx implementation retires #1 and #2 together — the cost is losing `appsecret_proof`, which would have to be computed by hand.

---

## What I did NOT examine

- **No HTTP request to Graph and no MCP tool call**, per the restriction. Everything marked PLAUSÍVEL is unverified by design; the probes are specified, not run. Findings 4, 5 and 6 can be answered by a single script against one account.
- **`src/db/repositories/manager_meta_account_access.py` and `meta_ad_accounts.py` — never opened.** I took `can_manager_access` on faith, and it is the entire Modelo B freio. Specifically unchecked: whether the gate normalizes the `act_` prefix the way `partnership.py:40-43` does on write (a mismatch there would be a silent fail-open or fail-closed), and whether a soft-revoked grant still passes. **If you extend this pass, start there** — it outranks several items above.
- **`src/governance/rate_limit.py`** — I read only `_parse_buc_header_pct` and `record_actual_meta`. The Google side and the `mgr:&lt;uuid&gt;` machinery I did not look at.
- **`src/auth/meta_oauth.py`** — read only `_fetch_all_adaccounts` and the two timeout sites. The OAuth callback, state HMAC, signed-request/data-deletion callback and token encryption are unexamined.
- **The reconciliation job.** I read `reconcile.py` (pure decision) and `partnership.py`, but not whatever applies the plan. F154 and F129 I did not investigate beyond the reference at `partnership.py:1-8`.
- **~30 of the ~34 Meta test files.** I read `test_meta_secret_leak.py`, `test_meta_client.py`, `test_meta_paginacao_usa_url_completa.py`, and skimmed `test_meta_reports_gate.py`. I verified specifically that no guard covers #1; I did **not** do that check for #2–#10, so a guard may already exist for one of them.
- **`src/meta_ads/labels.py`** — read its import sites only.
- **SDK areas not read:** the retry/`FacebookAdsApiBatch`/async-job machinery and the `AdAccount`/`AdsInsights` object layers. The repo doesn't use them, but a future mutate sprint would.
- I ran no test, no ruff, no mypy, no `check_pre_push.py`, and edited nothing.
