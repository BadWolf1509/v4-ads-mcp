# Testes e validação

> Convenções de fixture, builder, pré-flight e validação empírica de whitelist. Leia ao escrever teste ou ao shippar tool nova.
>
> Extraído do `CLAUDE.md` em 2026-08-19: convenção é estável e específica de
> área, então carregá-la em toda sessão era imposto de contexto. As regras
> curtas (o que faz parar) seguem no `Don't do` do `CLAUDE.md`; aqui fica o
> **porquê**.
>
> Taxonomia completa dos bugs: [`findings-catalog.md`](../operacao/findings-catalog.md).

---

### Test fixture pattern (integration)


Consuma `pg`/`db`/`app_with_db`/`client` de `tests/integration/conftest.py`; **NÃO redeclare localmente** (NÃO `db_pool` — não existe). 1 container Postgres **session-scoped** + template database (`tpl_app`, migrations rodam uma vez) — cada teste clona um banco novo via `CREATE DATABASE ... TEMPLATE` (isolamento total, sem pagar boot+migrations por teste). Mark `@pytest.mark.integration`. **Teste que exercita executor real precisa de grant no seed** (`manager_account_access.grant(...)`) senão o hard-gate levanta `AccountAccessDeniedError`. Generator de streaming com cursor: o teste DEVE **consumir** o output, não só disparar a rota (F58 — CSV export ficou quebrado em prod porque nenhum teste iterou).

### Mutate builder test convention (post-3b.5, F16/F42/F44/F51)


**Use `tests/unit/fixtures/proto_capture.py::make_capture_client` (NÃO MagicMock)** ao assertar proto field assignments — MagicMock aceita qualquer atributo e mascara bugs.

```python
from tests.unit.fixtures.proto_capture import make_capture_client
client = make_capture_client()
ops = build_my_thing(client, customer_id, payload)
assert ops[0].field("ad_group_criterion_operation.create.negative") is True
assert ops[0].has("ad_group_criterion_operation.create.bid_modifier") is False
```

**Field rename guard (F51):** campo proto renomeado entre versões SDK → assertar presença do nome novo E **ausência** do antigo (`__setattr__` aceita qualquer atributo silenciosamente):
```python
assert ops[0].has("campaign_operation.create.start_date_time") is True
assert ops[0].has("campaign_operation.create.start_date") is False
```
Meta SDK usa dicts (não proto) — pattern future-only (`MetaCaptureClient` análogo quando houver mutate Meta).

### Pre-flight test convention (post-3b.5/3b.8)


Pré-flight via helper de `_common.py` → **mock o helper no namespace do TOOL** (NÃO `_common.py`):
```python
with patch("src.mcp.tools.<your_tool>.<helper_name>", AsyncMock(return_value=None)):
```
Patches em `src.mcp.tools.<tool>.run_report` NÃO cobrem o site de pré-flight. Mitigação: `check_pre_push_full.py`.

### Schema whitelist empirical validation (post-3b.19A)


Todo valor de enum em whitelist DEVE ser validado empiricamente em smoke runbook (criar entidade real por valor — SDK descriptors contêm valores que o runtime rejeita). Família: F17/F18/F19/F25/F27/F31/F32/F34/F36/F44. Smoke runbook inclui per-value probe (batch 5/call). Rejeitado → remove do schema + documenta out-of-scope.

### No JSON Schema composition keywords (post-3b.19B.1)


`input_schema` NÃO pode ter `oneOf`/`allOf`/`anyOf` em nenhum nível (Anthropic validator rejeita). Constraints cross-field via `_validate_*` helper privado. Guard: `test_no_composition_keywords_in_any_schema`.
