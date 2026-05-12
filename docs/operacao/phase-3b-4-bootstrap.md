# Phase 3b.4 — manual smoke runbook

**Purpose:** Verify `apply_audience` works against real V4 accounts before declaring Sprint 3b.4 done.

**Operator:** wellinton.ribeiro@v4company.com
**Account (AUTO sandbox):** `1163862076` "Rayane Ribeiro - Nutry" (paused campaigns, zero traffic — same sandbox used in 3b.1/3b.2/3b.3 smokes)
**Account (real biz exclusion test):** `7862230676` "Mestre da Obra - João Pessoa" (Customer Match dormente identificada no dogfood P1b)

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (restart Claude Code session) — tools list includes `apply_audience`

## Test 1 — AUTO observation user_interest (1 attachment)

Anexar 1 in-market segment como observation a 1 ad_group da Nutry (paused, zero impact). Reusa um in-market category genérico — pode ser qualquer userInterests/{id} válido. Resource_name precisa existir na conta.

Primeiro listar in-market disponíveis (read-only):
```
run_gaql(customer_id="1163862076", query="SELECT user_interest.user_interest_id, user_interest.name FROM user_interest LIMIT 5")
```

Pick um id → call:
```
apply_audience(
  customer_id="1163862076",
  target_type="ad_group",
  mode="observation",
  attachments=[{
    "target_id": "183008426336",
    "audience_type": "user_interest",
    "audience_resource_name": "customers/1163862076/userInterests/<id_from_step1>"
  }]
)
```

Expected:
- [ ] `status: "applied"`, `applied_count: 1`, real `google_request_id`
- [ ] `attachments_result[0].status: "attached"`
- [ ] AUTO path triggered (observation ≤20)
- [ ] Verificar via `get_audience_performance(customer_id="1163862076")` que a attachment apareceu

## Test 2 — CONFIRM observation >20 (NÃO aplicar)

25 attachments numa call para forçar CONFIRM path:
```
apply_audience(
  customer_id="1163862076",
  target_type="ad_group",
  mode="observation",
  attachments=[
    {"target_id": "183008426336", "audience_type": "user_interest",
     "audience_resource_name": f"customers/1163862076/userInterests/{i}"}
    for i in range(91500, 91525)
  ]
)
```

Expected:
- [ ] `status: "dry_run"`, `confirmation_token` returned
- [ ] `confirmation_reason` cita "observation com >20"
- [ ] **Do NOT call apply_change** (token expira em 10min naturalmente; evita criar 25 attachments de teste)

## Test 3 — CONFIRM exclusion (real biz opportunity Mestre da Obra JP)

Esta é a **ação biz real** identificada no P1b dogfood: anexar Customer Match `clientes mestre da obra jp` (id `9377822529`, 1200 users CRM) como exclusion na campanha de aquisição `22169885957` (CAB).

V4 playbook estima -10% CPA. Decisão de aplicar fica com o gestor:

```
apply_audience(
  customer_id="7862230676",
  target_type="campaign",
  mode="exclusion",
  attachments=[{
    "target_id": "22169885957",
    "audience_type": "user_list",
    "audience_resource_name": "customers/7862230676/userLists/9377822529"
  }]
)
```

Expected (dry-run):
- [ ] `status: "dry_run"`, `confirmation_token` returned
- [ ] `confirmation_reason` cita "exclusion mode — sempre confirma"
- [ ] `blast_summary` clara sobre o que será aplicado
- [ ] **Decisão Wellington:** aplicar ou descartar? Se aplicar → `apply_change(token)` + monitorar CPA WoW na próxima semana (esperado ~-10%)

## Test 4 — Schema rejection (bid_modifier em exclusion)

```
apply_audience(
  customer_id="1163862076",
  target_type="campaign",
  mode="exclusion",
  attachments=[{
    "target_id": "22804468687",
    "audience_type": "user_list",
    "audience_resource_name": "customers/1163862076/userLists/123456789",
    "bid_modifier": 1.5
  }]
)
```

Expected:
- [ ] `status: "error"`
- [ ] PT-BR error mentioning "bid_modifier" + "exclusion"
- [ ] Pre-flight rejection — no mutation in Google Ads

## Test 5 — Schema rejection (audience_type vs resource_name mismatch)

```
apply_audience(
  customer_id="1163862076",
  target_type="ad_group",
  mode="observation",
  attachments=[{
    "target_id": "183008426336",
    "audience_type": "user_list",
    "audience_resource_name": "customers/1163862076/userInterests/91501"
  }]
)
```

Expected:
- [ ] `status: "error"`
- [ ] PT-BR error mentioning audience_type/resource_name mismatch
- [ ] Pre-flight rejection

## Cleanup

- T1 efetivamente criou attachment real na Nutry. **Não temos `remove_audience` tool ainda** (mesmo gap do Sprint 3b.3 finding A2). Opções:
  - (a) UI manual: detach via Google Ads UI no ad_group `183008426336`
  - (b) Leave-in-place: Nutry é paused, zero traffic — sem impacto. Documentar como follow-up.

**Recomendação cleanup:** (b) leave-in-place. Spawn-task `remove_audience` para sprint futura (também resolve gap A2 do Sprint 3b.3 sobre REMOVED status que não funciona).

- T3 (real biz): se Wellington aplicou em Mestre da Obra JP → monitorar CPA WoW próxima semana. Se decidir reverter, mesma constraint cleanup (sem `remove_audience` tool ainda).

## Sign-off

- [ ] T1-T5 todos passaram
- [ ] No errors em service logs
- [ ] `/admin/audit` mostra `apply_audience` row com custom params_summary
- [ ] Decisão sobre T3 documentada (aplicado / descartado)
- [ ] CLAUDE.md atualizado: Sprint 3b.4 shipped, tool count 37 → 38

**Date completed:** ____
