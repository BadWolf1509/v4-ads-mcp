# Sprint 3b.28 — `upload_customer_match_list` (design spec)

**Date:** 2026-05-20
**Operator:** wellinton.ribeiro@v4company.com
**Sprint shape:** single tool nova + new dispatcher (segundo non-mutate dispatcher do projeto, paralelo ao `run_conversion_upload` do Sprint 3b.26)
**No deadline driver:** sem prazo externo concreto. Sprint executado por sinal do roadmap (next-in-queue pós-3b.27) + valor estratégico (destrava Customer Match V4 playbook + A4 investigation companion futuro).

---

## Background

### Por que essa tool

V4 playbook "-10% CPA via exclusion" usa Customer Match user lists pra excluir clientes existentes de remarketing campaigns. Hoje gestor faz upload manual via Google Ads UI — lento + propenso a erro (PII em planilha desprotegida, ausência de SHA-256 hashing, opt-out pós-LGPD complicado).

`upload_customer_match_list` MCP tool resolve:
1. **PII never leaves V4 boundary unhashed** — tool faz SHA-256 client-side antes do gRPC call
2. **Idempotente + auditável** — `audit_log` registra cada upload com `google_request_id`
3. **LGPD-compliant** — `consent.ad_user_data` + `consent.ad_personalization` setados hardcoded GRANTED (gestor responde pela coleta de consent upstream)
4. **Async-friendly** — tool retorna `job_resource_name` imediatamente após `run_offline_user_data_job`; gestor faz status poll via GAQL quando precisar

### Insight crítico (context7 deep-dive 2026-05-20)

`OfflineUserDataJobService` é assíncrono no backend Google — jobs processam em **horas** após `run`. Synchronous wait com timeout curto NÃO funciona (sempre retorna PENDING/RUNNING). Decisão V0: **fire-and-forget** — tool dispara o job e devolve resource_name; status fica responsabilidade do gestor consultar via `run_gaql`.

Pattern reference: Sprint 3b.26 `import_offline_conversions` (custom dispatcher fora de `GoogleAdsService.mutate`) — mas 3b.26 era 1-call (`upload_click_conversions`). Aqui são **3 calls em sequência** (create_job → add_operations → run_job).

---

## Goal

Entregar Sprint 3b.28 Phase A em produção:

1. Nova tool MCP `upload_customer_match_list` — submit-only V0 (sem status polling embutido)
2. Novo dispatcher `run_offline_user_data_job` em `src/google_ads/customer_match.py` (paralelo a `run_conversion_upload` do 3b.26)
3. Pre-flight async `validate_user_list_for_upload` (existe + tipo CRM_BASED + status ENABLED + Customer Match terms acceptance check via shape do retorno)
4. Layer 2 hashing utility (`_hash_email`, `_hash_phone`) + plaintext detection

Pra que gestor V4 possa upload Customer Match audiences via MCP sem precisar Google Ads UI, mantendo PII hashed local + LGPD compliance + audit trail.

## Non-goals (V0)

- Não criar user_list (gestor cria via UI separado; tool MCP `create_user_list` candidate Sprint futuro)
- Não suportar `remove_all` operation (perigoso; tool dedicada se demanda surgir)
- Não suportar identifier types além de `email` + `phone_number` (address_info / mobile_id / third_party_user_id candidates futuros)
- Não suportar synchronous status wait (jobs assíncronos backend; out of scope V0)
- Não implementar A4 investigation (mecanismo real de Customer Match exclusion pra `(campaign + user_list)` ainda OPEN desde Sprint 3b.4) — Phase B separado
- Não suportar partial_failure parsing detalhado individual por member (V0 echo back o resource_name + count; partial errors via job status poll posterior)

---

## Architecture

### Padrão técnico unificado

Pattern unificado pelos 3b.26 + 3b.28 (custom dispatchers fora de `GoogleAdsService.mutate`):

```
tool entry (args)
  ↓
  [Layer 1] schema validation (jsonschema) — minItems, regex, enum, max, member shape
  ↓
  [Layer 2] _validate_payload_shape + _hash_members
    - Plaintext-detection: rejeita input ja-hashed (`^[a-f0-9]{64}$` em email)
    - Normalize: email lowercase+trim-all-whitespace; phone E.164 (+55 default)
    - SHA-256 hex digest
    - Duplicate detection: rejeita identifier duplicado no batch
  ↓
  [Layer 3] pre-flight async (validate_user_list_for_upload — 1 GAQL pra validar user_list existe + tipo + status)
  ↓
  classify() risk → CONFIRM (sempre — upload de PII tem alto blast radius)
  ↓
  create_pending() OR apply via run_offline_user_data_job
  ↓
  run_offline_user_data_job dispatcher:
    1. client.get_service("OfflineUserDataJobService")
    2. create_offline_user_data_job(customer_id, job) → job_resource
    3. add_offline_user_data_job_operations(resource_name, operations[], enable_partial_failure=True)
    4. run_offline_user_data_job(resource_name) — fire-and-forget
  ↓
  return job_resource_name + to_check_status hint (run_gaql query template)
```

### Módulos novos vs modificados

| Arquivo | Action | Responsabilidade |
|---|---|---|
| `src/mcp/tools/upload_customer_match_list.py` | **NOVO** — tool MCP (Layer 1 schema + Layer 2 sync + chamada do dispatcher) | ~200 linhas |
| `src/google_ads/customer_match.py` | **NOVO** — `run_offline_user_data_job` dispatcher + `_normalize_and_hash_email` + `_normalize_and_hash_phone` + `_build_user_data_operations` builder helper | ~250 linhas |
| `src/google_ads/queries/_common.py` | **MODIFY (append)** — `validate_user_list_for_upload` (existe + tipo CRM_BASED + status ENABLED) | ~60 linhas |
| `src/governance/blast_radius.py` | **MODIFY** — entry `upload_customer_match_list` em `classify()` (sempre CONFIRM) | ~10 linhas |
| `src/mcp/tools/apply_change.py` | **MODIFY** — branch `operation_type == "upload_customer_match_list"` no router | ~5 linhas |
| `tests/unit/test_upload_customer_match_list.py` | **NOVO** — schema + Layer 2 (hashing + plaintext detect + duplicates) | ~250 linhas |
| `tests/unit/test_run_offline_user_data_job.py` | **NOVO** — dispatcher tests via `make_capture_client` (3-step sequence asserts) | ~180 linhas |
| `tests/unit/test_validate_user_list_for_upload.py` | **NOVO** — helper unit tests com mock run_report | ~120 linhas |
| `tests/unit/test_blast_radius.py` | **MODIFY (append)** — TestUploadCustomerMatchListClassify | ~30 linhas |
| `tests/unit/test_tools_schemas.py` | **MODIFY** — whitelists incluem `upload_customer_match_list` | ~5 linhas |
| `tests/integration/test_upload_customer_match_list.py` | **NOVO** — integration tests (mock helper no namespace da tool) | ~200 linhas |
| `docs/operacao/findings-catalog.md` | **MODIFY** — adicionar F-finding row se emergir + update Last updated | ~5 linhas (no signoff) |
| `CLAUDE.md` | **MODIFY** — Sprint 3b.28 shipped row + tool count 50→51 + Pending/future reorder | ~3 linhas (no signoff) |
| `docs/operacao/phase-3b-28-bootstrap.md` | **MODIFY** — runbook existente (esqueleto gerado 19/05) atualizado com V0 escopo confirmado | ~50 linhas atualizadas |

**Total:** ~1370 linhas novas (45% código, 55% testes + docs). 6 modificados, 7 novos.

---

## Component A — Tool MCP `upload_customer_match_list`

### Schema (`_SCHEMA`)

```python
{
  "type": "object",
  "properties": {
    "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
    "user_list_id": {"type": "string", "pattern": "^[0-9]+$"},
    "operation": {"type": "string", "enum": ["add", "remove"]},
    "members": {
      "type": "array",
      "minItems": 1,
      "maxItems": 1000,
      "items": {
        "type": "object",
        "properties": {
          "email": {"type": "string", "minLength": 3, "maxLength": 254},
          "phone_number": {"type": "string", "minLength": 8, "maxLength": 30}
        },
        "additionalProperties": False,
        "minProperties": 1
      }
    }
  },
  "required": ["customer_id", "user_list_id", "operation", "members"],
  "additionalProperties": False
}
```

**Características:**
- `maxItems: 1000` — Google API permite até 10k mas V0 fica conservador (proteção contra payload bombing F2/F22 family + memory ao calcular hashes em batch)
- `members[].minProperties: 1` — cada member tem AO MENOS 1 identifier (email ou phone)
- `members[]` items NÃO têm fields required individualmente (cada um opt; minProperties garante presença)
- Sem composition keywords (convention pós-3b.18/3b.19B)

### Layer 2 — `_validate_payload_shape` + `_hash_members`

#### `_validate_payload_shape`
- **Reject 1:** `members[i]` sem email nem phone — `"member item N sem identificador (precisa email OU phone_number)"`
- **Reject 2:** detectar plaintext input já-hashed (formato `^[a-f0-9]{64}$`) — `"member item N: email '<X>' já parece SHA-256 hash. Passe plaintext; tool faz hash internamente."` (V0 valida em email; phone tem variação grande de formato pra detectar reliable)
- **Reject 3:** email regex inválido — `"member item N: email '<X>' inválido (formato esperado: local@domain)"`
- **Reject 4:** phone E.164 normalize fail — `"member item N: phone_number '<X>' formato inválido (E.164 ou número BR com DDD)"`
- **Reject 5:** identifier duplicado no batch (após normalize) — `"emails duplicados no batch: [...]"` ou `"phone_numbers duplicados no batch: [...]"`

#### `_normalize_and_hash_email(plaintext) → hashed_hex`
```python
def _normalize_and_hash_email(plaintext: str) -> str:
    """SHA-256 hex digest após lowercase + remove ALL whitespace.

    Conforme Google Ads Customer Match spec.
    """
    normalized = "".join(plaintext.split()).lower()
    return hashlib.sha256(normalized.encode()).hexdigest()
```

#### `_normalize_and_hash_phone(plaintext) → hashed_hex`
```python
def _normalize_and_hash_phone(plaintext: str) -> str:
    """E.164 normalize + SHA-256.

    V4 invariant: phone sem country_code prefix → assume +55 (BR).
    Strip non-digit chars except leading +. Lowercase final.
    """
    # Strip non-digits except leading +
    digits_only = re.sub(r"[^\d+]", "", plaintext)
    if not digits_only.startswith("+"):
        digits_only = "+55" + digits_only.lstrip("0")
    # SHA-256 hex digest (lowercase implicit via hashlib)
    return hashlib.sha256(digits_only.encode()).hexdigest()
```

### Layer 3 — `validate_user_list_for_upload` (novo helper em `_common.py`)

```python
async def validate_user_list_for_upload(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    user_list_id: str,
) -> dict[str, Any] | None:
    """GAQL pre-flight: user_list existe + tipo CRM_BASED + status ENABLED.

    Returns None if valid, dict com {error, ...} se problema.

    Sprint 3b.28 — pre-flight pra upload_customer_match_list tool.
    """
    query = (
        "SELECT user_list.id, user_list.name, user_list.type, "
        "user_list.crm_based_user_list.upload_key_type, "
        "user_list.read_only, user_list.size_for_display, "
        "user_list.membership_status "
        "FROM user_list "
        f"WHERE user_list.id = {int(user_list_id)}"
    )
    # ... formatter + run_report + checks
```

**Checks:**
1. Lista existe? Se não, `{error: "user_list_id=X não existe em customer_id=Y", missing_id: X}`
2. `type == CRM_BASED_USER_LIST`? Se não, `{error: "user_list type=Z; upload requer CRM_BASED_USER_LIST"}`
3. `read_only` é `True`? Se sim, `{error: "user_list está read_only; não aceita uploads. Verifique se Customer Match policy foi aceita."}`
4. `membership_status == OPEN`? Se não, `{error: "user_list membership_status=Z; não aceita uploads agora"}`

### Risk classification

```python
elif operation == "upload_customer_match_list":
    members = params.get("members", [])
    return RiskClassification(
        RiskLevel.CONFIRM,
        f"upload_customer_match_list: {len(members)} membro(s) — PII upload, sempre CONFIRM",
    )
```

**Justificativa:** sempre CONFIRM. Upload de PII tem alto blast radius (LGPD audit + Google billing baseado em members ingeridos). Não há AUTO path V0.

### V4 invariants

- `consent.ad_user_data = GRANTED` (hardcoded em metadata)
- `consent.ad_personalization = GRANTED` (hardcoded em metadata)
- Phone default country code `+55` (BR — único país V4)
- `enable_partial_failure = True` na `add_operations` call

### Return shape (apply)

```json
{
  "status": "submitted",
  "operation": "upload_customer_match_list",
  "customer_id": "1163862076",
  "user_list_id": "1234567890",
  "members_submitted": 50,
  "operation_type": "add",
  "job_resource_name": "customers/1163862076/offlineUserDataJobs/9876543210",
  "to_check_status": "Job é assíncrono no backend Google (processa em horas). Pra verificar status, use: run_gaql(customer_id='1163862076', query='SELECT offline_user_data_job.status, offline_user_data_job.failure_reason FROM offline_user_data_job WHERE offline_user_data_job.id = 9876543210')",
  "google_request_id_create_job": "<req_id>",
  "google_request_id_add_ops": "<req_id>",
  "google_request_id_run_job": "<req_id>"
}
```

**Status field** vale `"submitted"` (não `"applied"`) pra sinalizar que job está fila do backend, não finalizado.

---

## Component B — Dispatcher `run_offline_user_data_job`

### Sequência (3 chamadas Google API)

```python
async def run_offline_user_data_job(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    user_list_id: str,
    operation_type: str,  # "add" | "remove"
    hashed_members: list[dict[str, Any]],  # post Layer 2 hashing
) -> dict[str, Any]:
    """3-step sequence: create job → add ops → run job. Returns job_resource_name + 3 request_ids."""

    client = await build_client_for_manager(...)
    service = client.get_service("OfflineUserDataJobService")

    # Step 1: Create job
    job = client.get_type("OfflineUserDataJob")
    job.type_ = client.enums.OfflineUserDataJobTypeEnum.CUSTOMER_MATCH_USER_LIST
    job.customer_match_user_list_metadata.user_list = (
        f"customers/{customer_id}/userLists/{user_list_id}"
    )
    # V4 LGPD invariants
    job.customer_match_user_list_metadata.consent.ad_user_data = (
        client.enums.ConsentStatusEnum.GRANTED
    )
    job.customer_match_user_list_metadata.consent.ad_personalization = (
        client.enums.ConsentStatusEnum.GRANTED
    )
    create_response = service.create_offline_user_data_job(
        customer_id=customer_id, job=job
    )
    job_resource = create_response.resource_name
    create_req_id = <captured from interceptor>

    # Step 2: Add operations
    operations = _build_user_data_operations(
        client, operation_type, hashed_members
    )
    add_request = client.get_type("AddOfflineUserDataJobOperationsRequest")
    add_request.resource_name = job_resource
    add_request.operations = operations
    add_request.enable_partial_failure = True
    add_response = service.add_offline_user_data_job_operations(request=add_request)
    add_req_id = <captured>

    # Step 3: Run job (fire-and-forget)
    service.run_offline_user_data_job(resource_name=job_resource)
    run_req_id = <captured>

    return {
        "job_resource_name": job_resource,
        "google_request_id_create_job": create_req_id,
        "google_request_id_add_ops": add_req_id,
        "google_request_id_run_job": run_req_id,
        "members_submitted": len(hashed_members),
    }
```

### Builder helper `_build_user_data_operations`

```python
def _build_user_data_operations(
    client: Any,
    operation_type: str,  # "add" or "remove"
    hashed_members: list[dict[str, Any]],
) -> list[Any]:
    """Each member becomes 1 OfflineUserDataJobOperation com 1 UserData
    containing 1 ou 2 user_identifiers (hashed_email + hashed_phone)."""

    operations = []
    for member in hashed_members:
        user_data = client.get_type("UserData")

        if "hashed_email" in member:
            identifier = client.get_type("UserIdentifier")
            identifier.hashed_email = member["hashed_email"]
            user_data.user_identifiers.append(identifier)

        if "hashed_phone_number" in member:
            identifier = client.get_type("UserIdentifier")
            identifier.hashed_phone_number = member["hashed_phone_number"]
            user_data.user_identifiers.append(identifier)

        op = client.get_type("OfflineUserDataJobOperation")
        if operation_type == "add":
            op.create = user_data
        else:  # "remove"
            op.remove = user_data
        operations.append(op)

    return operations
```

### Apply_change router

```python
elif saved.operation_type == "upload_customer_match_list":
    result = await run_offline_user_data_job(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=saved.customer_id,
        user_list_id=saved.payload["user_list_id"],
        operation_type=saved.payload["operation"],
        hashed_members=saved.payload["hashed_members"],
    )
```

---

## Data flow

### Flow A — Happy path (CONFIRM dry_run → apply)

```
Claude → upload_customer_match_list(customer_id, user_list_id, "add", members=[{email, phone}, ...])
   ↓
[upload_customer_match_list.py]
   ├── Layer 1 jsonschema validation (registry)
   ├── Layer 2 _validate_payload_shape (plaintext detect + duplicate check + email regex)
   ├── Layer 2 _hash_members (SHA-256 normalize + hash email/phone)
   ├── Layer 3 validate_user_list_for_upload (GAQL — exists + CRM_BASED + ENABLED + writable)
   ├── classify → CONFIRM (sempre — PII upload)
   ├── create_pending → dry_run_tokens (payload contém hashed_members, NÃO plaintext)
   ↓
{status: "dry_run", confirmation_token, members_count_preview, to_apply}

Claude → apply_change(confirmation_token)
   ↓
[apply_change.py]
   ├── token lookup
   ├── route → run_offline_user_data_job
   ↓
[customer_match.py → run_offline_user_data_job]
   ├── Step 1: create_offline_user_data_job → job_resource (req_id_1)
   ├── Step 2: add_offline_user_data_job_operations → success (req_id_2)
   ├── Step 3: run_offline_user_data_job → fire-and-forget (req_id_3)
   └── audit_log entry (operation_type=upload_customer_match_list, 3 request_ids)
   ↓
{status: "submitted", job_resource_name, to_check_status: "Use run_gaql..."}
```

### Flow B — Pre-flight reject path

```
[upload_customer_match_list.py]
   ├── Layer 3 validate_user_list_for_upload
   │     └── user_list.read_only=True (Customer Match terms not accepted)
   ↓
{status: "error", error: "user_list está read_only; verifique se Customer Match policy foi aceita."}

NOTAS:
- rate_counter NÃO incrementa pra mutate
- audit_log da GAQL preflight FICA (debug)
- PII plaintext ainda NÃO foi hasheada (Layer 3 vem após Layer 2)
```

### Flow C — Layer 2 hashing failure path

```
[upload_customer_match_list.py]
   ├── Layer 2 _validate_payload_shape
   │     └── member[3].email = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8" (já hash)
   ↓
{status: "error", error: "member item 3: email '5e8848...' parece SHA-256 hash já. Passe plaintext; tool faz hash internamente."}
```

### LGPD note no flow

PII plaintext **nunca** sai do processo tool. Sequence:
1. Tool recebe plaintext em args (memória do processo Python)
2. Layer 2 normaliza + hash em-memory
3. dry_run_tokens armazena APENAS `hashed_members` (plaintext discardado)
4. Apply usa hashed_members do token
5. gRPC envia hashed (plaintext nunca toca disk nem network outbound)

audit_log armazena `member_count`, `operation_type`, request_ids — **NÃO armazena identificadores** (nem hashed nem plaintext). Aderência LGPD §16 (minimização).

---

## Error handling

### Mapa de erros por camada

| Camada | Trigger | Failure mode | Response | Rate counter? | Audit log? |
|---|---|---|---|---|---|
| **Layer 1** schema | maxItems, regex, minProperties violado | `validation_error` MCP transport | ❌ | ❌ |
| **Layer 2** `_validate_payload_shape` | member sem identifier, email já-hashed, email regex inválido, phone inválido, duplicado | `{status: "error", error: "..."}` | ❌ | ❌ |
| **Layer 2** `_hash_members` | (não tem failure path próprio — hashlib stdlib não falha em valid string) | N/A | N/A | N/A |
| **Layer 3** `validate_user_list_for_upload` | missing / wrong type / read_only / wrong status | `{status: "error", error: "..."}` | ✅ +1 (GAQL) | ✅ preflight entry |
| **Dispatcher Step 1** (create_job) | Customer Match policy não aceita | `{status: "error_google_api", error: <Google msg>, step: "create_job"}` | ✅ +1 | ✅ partial |
| **Dispatcher Step 2** (add_ops) | invalid hashed_value format | `{status: "error_google_api", error: <Google msg>, step: "add_ops", job_resource_name: <X>}` | ✅ +N | ✅ entry |
| **Dispatcher Step 3** (run_job) | quota exceeded daily | `{status: "error_google_api", error: <Google msg>, step: "run_job", job_resource_name: <X>}` | ✅ +1 | ✅ entry |
| **Token expired** | Token > 10min | `{status: "error_token_expired"}` | ❌ | ❌ |
| **Rate limit** | >15.000 ops/dia | `{status: "error_rate_limit"}` | ❌ | ✅ rate_limit_hit |

### Mensagens PT-BR específicas

**Layer 2:**
- `"member item N sem identificador (precisa email OU phone_number)"`
- `"member item N: email '{X}' já parece SHA-256 hash. Passe plaintext; tool faz hash internamente."`
- `"member item N: email '{X}' inválido (formato esperado: local@domain)"`
- `"member item N: phone_number '{X}' formato inválido (E.164 ou número BR com DDD)"`
- `"emails duplicados no batch após normalize: {list}. Cada email aparece no máximo 1 vez."`
- `"phone_numbers duplicados no batch após normalize: {list}. Cada phone aparece no máximo 1 vez."`

**Layer 3:**
- `"user_list_id={X} não existe em customer_id={Y}. Verifique IDs via run_gaql ou Google Ads UI."`
- `"user_list_id={X} type={Z}; upload requer CRM_BASED_USER_LIST. Crie nova lista via Google Ads UI > Audience Manager > Customer Match."`
- `"user_list_id={X} está read_only. Provável causa: Customer Match policy não aceita pra conta. Aceite em Google Ads UI > Tools > Audience Manager > Customer lists > Accept terms."`

### Recovery em case de partial failure mid-sequence

3-step sequence pode falhar em qualquer step. Tratamento:

| Step que falhou | Recovery |
|---|---|
| Step 1 (create_job) | Sem job criado; gestor pode retentar |
| Step 2 (add_ops) | Job criado mas vazio. Response inclui `job_resource_name` pra gestor descartar via UI ou retentar add separado |
| Step 3 (run_job) | Job criado + ops added mas não submetido. Response inclui `job_resource_name`. Gestor pode rodar `run_offline_user_data_job` manual via separate tool futuro, OU descartar |

V0: documentar isso em error responses; sem retry automático. Gestor decide.

---

## Testing strategy

### Unit tests — `tests/unit/test_upload_customer_match_list.py` (~250 linhas)

**Pattern obrigatório:** `make_capture_client` pra builder; mock at TOOL namespace pra integration. Convention pós-3b.5/3b.8 + F42 lesson.

Test cases (~10):
1. `test_schema_has_no_composition_keywords` — F18/F25 regression guard
2. `test_schema_explicit_types` — F1 lesson
3. `test_schema_member_requires_at_least_one_identifier` — `minProperties: 1`
4. `test_validate_payload_shape_rejects_member_without_identifier`
5. `test_validate_payload_shape_rejects_already_hashed_email`
6. `test_validate_payload_shape_rejects_invalid_email_format`
7. `test_validate_payload_shape_rejects_duplicate_email_after_normalize`
8. `test_validate_payload_shape_rejects_duplicate_phone_after_normalize`
9. `test_hash_email_normalize_lowercase_and_strip_whitespace`
10. `test_hash_phone_E164_default_to_BR_plus_55`

### Unit tests — `tests/unit/test_run_offline_user_data_job.py` (~180 linhas)

Test cases (~6):
1. `test_dispatcher_creates_job_with_customer_match_metadata` — proto_capture asserts on `job.type_`, `job.customer_match_user_list_metadata.user_list`, `consent.ad_user_data`, `consent.ad_personalization`
2. `test_dispatcher_user_list_resource_name_format` — `customers/{cid}/userLists/{lid}`
3. `test_dispatcher_consent_lgpd_invariants_granted`
4. `test_dispatcher_add_operations_partial_failure_true`
5. `test_dispatcher_add_operations_user_data_with_hashed_email_and_phone`
6. `test_dispatcher_remove_operation_uses_remove_field_not_create`

### Unit tests — `tests/unit/test_validate_user_list_for_upload.py` (~120 linhas)

Test cases (~5):
1. `test_user_list_exists_crm_based_enabled_returns_none`
2. `test_missing_user_list_returns_error_with_id`
3. `test_wrong_type_returns_error_with_type_name`
4. `test_read_only_returns_error_mentioning_policy_acceptance`
5. `test_membership_status_closed_returns_error`

### Integration tests — `tests/integration/test_upload_customer_match_list.py` (~200 linhas)

**Mock pattern crítico:** `patch("src.mcp.tools.upload_customer_match_list.validate_user_list_for_upload", AsyncMock(...))` — NÃO `_common.py`. F-class lesson.

Test cases (~5):
1. `test_layer2_rejects_no_identifier`
2. `test_preflight_missing_user_list_returns_error`
3. `test_happy_path_returns_dry_run_token`
4. `test_apply_submits_job_and_returns_resource_name` (mock dispatcher)
5. `test_remove_operation_passes_remove_to_dispatcher`

### Cross-cutting

- `test_tools_schemas.py` whitelists incluem `upload_customer_match_list`
- `test_blast_radius.py` adicionar `TestUploadCustomerMatchListClassify` (sempre CONFIRM)

### Smoke runbook

Estrutura inspirada no 3b.27 + 3b.26. Tests planejados (~12):

**Pre-flight setup:**
- T0a: GAQL pré-smoke — listar UserLists CRM_BASED em Nutry (`SELECT user_list.id, name, type, read_only, size_for_display, membership_status FROM user_list WHERE user_list.type = 'CRM_BASED_USER_LIST'`)
- T0b (se nenhum CRM_BASED existe): criar UserList via Google Ads UI **antes do smoke** — Wellington manual setup. Marcar SKIP se Nutry sem terms acceptance.

**Pure validation tests (sem PII real):**
- T1: Layer 2 reject member sem identifier
- T2: Layer 2 reject email já-hashed (SHA-256 input)
- T3: Layer 2 reject email inválido
- T4: Layer 2 reject phone inválido
- T5: Layer 2 reject duplicate email (após normalize)
- T6: Layer 3 reject — user_list_id 9999 não existe
- T7: schema regression — maxItems 1001 members → "is too long"

**Happy path tests (PII fictícia):**
- T8: dry_run happy path — 5 members com email synthetic (`smoke+1@v4.com`, `smoke+2@v4.com`, ...) → CONFIRM token retornado
- T9: apply T8 → `status: submitted` + job_resource_name retornado. **DEFERRED** se Nutry sem Customer Match terms acceptance (F41-equivalent).
- T10: status poll via run_gaql (manual usando job_resource_name de T9) → PENDING ou RUNNING ou SUCCESS
- T11: operation_type=remove — repete T8 com `operation: "remove"` → dry_run + apply OK
- T12: V4 invariants verify — bit-a-bit via interceptor capture (post-deploy): `consent.ad_user_data=GRANTED`, `consent.ad_personalization=GRANTED`, `enable_partial_failure=True`, phone prefix `+55` default

**Expected:** 10-12/12 PASS pra signoff. F-findings esperados: 1-3 (média histórica dispatchers custom).

### Defense-in-depth

`mcp-tool-quality-reviewer` antes do push:

```
Agent(subagent_type: mcp-tool-quality-reviewer, prompt: "Audite src/mcp/tools/upload_customer_match_list.py + src/google_ads/customer_match.py + src/google_ads/queries/_common.py::validate_user_list_for_upload. Sprint 3b.28 com novo dispatcher fora de mutate (paralelo a 3b.26). Atenção especial Group 2.1 ProtoFieldCapture nos dispatcher tests (F42 lesson — retrofit feito em test_run_conversion_upload commit e055ef7).")
```

---

## Risks / open questions

### Risk 1 — Nutry sem Customer Match terms acceptance (HIGH likelihood)

**Impact:** T9 happy-path apply pode cair em DEFERRED (F41-equivalent). Smoke signoff fica parcial. Wellington precisaria conta V4 real pra signoff completo.

**Mitigação:** T1-T7 + T11 (pure validation + remove operation dry_run) cobrem 80% da tool. T9 + T12 dependem do env. Documentar DEFERRED no runbook se aplicável.

### Risk 2 — 3-step dispatcher pode falhar mid-sequence (MED likelihood)

Já descrito em Error handling. V0: documentar `job_resource_name` em qualquer erro pós-Step 1, gestor decide manual.

### Risk 3 — proto_capture ainda não cobre OfflineUserDataJobService

`make_capture_client` cobre `MutateOperation` style + custom enums. Dispatcher tests vão precisar:
- `client.get_type("OfflineUserDataJob")` returns capture
- `client.get_type("UserData")` + `.user_identifiers.append(...)` captures
- `client.get_type("OfflineUserDataJobOperation")` returns capture
- Service call `service.create_offline_user_data_job(...)` retorna mock response com `resource_name`

Pode precisar **extension do fixture proto_capture.py** — adicionar mock pra `OfflineUserDataJobService` methods retornando proper proto-like responses. **30-60 min de trabalho de fixture** antes de tests funcionais.

**Mitigação:** primeiro dispatcher test escreve mostra qual extensão precisa; resto dos tests reusa.

### Risk 4 — Async job model — gestor confuso?

`status: "submitted"` é diferente do `applied` familiar. Gestor pode esperar feedback imediato. Mitigação: descrição da tool + return shape explicitly menciona "Job é assíncrono no backend Google (processa em horas)" + `to_check_status` template.

### Risk 5 — A4 investigation companion não tocado V0

A4 (Customer Match exclusion mechanism aberto desde 3b.4/3b.5) NÃO é resolvido aqui. Phase B futura. Documentar no findings-catalog que A4 permanece OPEN pós-3b.28.

---

## Sign-off plan

Pra considerar Sprint 3b.28 shipped:

- [ ] Pre-push gate 5/5 PASS
- [ ] Pre-push full 6/6 PASS (Docker required — dispatcher tem integration tests críticos)
- [ ] mcp-tool-quality-reviewer subagent: PASS (FAIL aceitável só convention-drift LOW)
- [ ] Production deploy `/health` 200
- [ ] Smoke 10-12/12 PASS em Nutry (T9 + T12 podem DEFERRED se Nutry sem Customer Match terms — F41-equivalent)
- [ ] CLAUDE.md row Sprint 3b.28 (in_progress → shipped, count 50→51)
- [ ] findings-catalog updated com qualquer F-finding emergido + Last updated
- [ ] Wellington valida em conta V4 real (post-deploy ou em sprint follow-up — opcional pra signoff técnico, mandatório pra validar real-world LGPD compliance)

---

## Refs

- **Pattern reference:** Sprint 3b.26 `import_offline_conversions` (custom dispatcher 1-call). `run_conversion_upload` em `src/google_ads/conversions.py`. ProtoFieldCapture retrofit em `test_run_conversion_upload.py` shipped commit `e055ef7` (Sprint 3b.28 prep)
- **Context7 ground truth:** Google Ads Python SDK v24 `OfflineUserDataJobService` example completo (queried 2026-05-20)
- **A4 finding (OPEN):** [findings-catalog.md](../../operacao/findings-catalog.md) §A4
- **Runbook esqueleto:** [phase-3b-28-bootstrap.md](../../operacao/phase-3b-28-bootstrap.md) (gerado 19/05 via subagent `smoke-runbook-generator`, será refinado com escopo V0 confirmado)
- **LGPD §16 (minimização de dados):** audit_log armazena apenas counts + request_ids; nunca identifiers (hashed ou plaintext)
- **Hashing convention Google:** [Customer Match upload requirements](https://developers.google.com/google-ads/api/docs/remarketing/audience-types/customer-match#data-formatting)
