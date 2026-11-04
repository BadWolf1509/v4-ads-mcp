# Google MCP Per-Account Authorization Gate — Design Doc

**Data:** 2026-05-28
**Status:** Proposto (aguardando review do gestor antes de `writing-plans`)
**Origem:** Análise criteriosa das telas do gestor (não-admin), 2026-05-28 — achado Crítico C1/C2.
**Specs relacionadas:** [`2026-05-28-meta-access-matrix-design.md`](2026-05-28-meta-access-matrix-design.md) (o gate Meta que esta spec espelha para o Google).

---

## 0. Contexto e motivador

A matriz `manager_account_access` (gestor × `customer_id`) é respeitada na **UI web** (`/accounts` mostra só contas concedidas; `/audit` escopa por `manager_id`), mas **NÃO é enforçada na camada de tools MCP do Google**. `run_report` e `run_mutation` constroem o client via `build_client_for_manager` usando o `login_customer_id` do MCC (`src/google_ads/client.py:70`), que alcança todas as 25 contas. Nenhuma tool Google chama `can_manager_access` (verificado: grep retorna só `src/meta_ads/reports.py:66`).

**Impacto:** um gestor com Bearer token MCP válido pode chamar qualquer tool (`get_campaign_performance`, `run_gaql`, `update_campaign_status`, …) contra qualquer `customer_id` do MCC — inclusive clientes de outras unidades não concedidos a ele. A UI **promete um limite** ("Contas acessíveis (N)") que o MCP **não cumpre**.

**Por que agora:** hoje o gap é latente (só o admin opera, e ele tem acesso a tudo). Vira **ativo quando os 3 colaboradores V4 LS&Co entrarem** com grants parciais. Fechar antes do onboarding.

**Mitigantes existentes (não suficientes):** só gestores convidados+ativados têm token; todas as chamadas são auditadas (`manager_id`+`customer_id`+operation); mutates exigem CONFIRM. Detective, não preventive; reads são silenciosos.

O Meta já tem o gate equivalente (`run_meta_graph_get` → `can_manager_access`, Sprint Meta Access Matrix). Esta spec é o **retrofit de simetria** que aquela spec listou explicitamente como out-of-scope (§11).

## 1. Decisão de design

**Matriz autoritativa para TODOS, sem bypass por role** (admin incluído). Rationale:
- A UI web já trata a matriz como autoritativa para visibilidade do admin (`/accounts` usa `list_accounts_for_manager`; conta nova não aparece até concedida). O gate MCP apenas **alinha o MCP ao que a UI já faz** — não cria assimetria.
- Consistência com o Meta (que não dá bypass por role); zero mudança no código Meta já shipado.
- Defesa contra erro de LLM/typo: num contexto MCP onde `customer_id` vem de tradução linguagem-natural→args, o gate confina mutação acidental ao conjunto operado.
- Zero disrupção hoje: o admin (Wellington) já tem as 25 contas concedidas.
- Footgun pequeno (conta nova exige 1 grant) e auto-corrige; um bypass `is_admin` é adicionável em 1 linha no futuro se necessário (YAGNI agora).

**Escopo confirmado (3 decisões):** gate em **reads + mutates**; **gate central** cobre `run_gaql` e todas as tools (sem bloquear `run_gaql` por role); re-check no **build E no apply** (defesa em profundidade).

## 2. Architecture Overview

```
MCP tool (manager_id, customer_id, ...)
   ├─ READ:  run_report(...)            ─┐
   ├─ WRITE: run_mutation(...)           ├─ ensure_account_access(conn, manager_id, customer_id, level)
   ├─ WRITE: run_conversion_upload(...)  │     ├─ can_manager_access(...) → False → raise AccountAccessDenied
   ├─ WRITE: run_offline_user_data_job() ─┘     │                                  + audit status="denied"
   └─ BUILD: create_pending(manager_id, ...) ──── (mesmo helper, level="write")
```

Mudança central: a matriz `manager_account_access` passa a ser o **freio real** na camada MCP do Google (hoje só o token MCC freia, e ele alcança tudo).

## 3. Componentes

### 3.1 Novo: `src/google_ads/access.py`
```python
class AccountAccessDeniedError(Exception):
    """Raised when a manager has no grant for the requested Google customer_id."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

async def ensure_account_access(
    conn, *, manager_id: UUID, customer_id: str, session_id: UUID,
    operation_name: str, level: str = "read",
) -> None:
    """Raise AccountAccessDeniedError (PT-BR) + audit status='denied' if the manager
    lacks `level` access to customer_id in manager_account_access."""
```
- Usa `manager_account_access.can_manager_access(conn, manager_id, customer_id, level=level)` (já existe, suporta `read`/`write`).
- Em deny: grava `audit_log.record(..., action_type=<read|mutate>, status="denied", customer_id=customer_id, platform="google")` e levanta `AccountAccessDeniedError` com mensagem PT-BR ("Você não tem acesso à conta {customer_id}. Peça ao admin pra liberar no painel.").
- Mirror do `MetaAccessDeniedError` (que o tool layer já trata via `hasattr(e, "message")`).

### 3.2 Choke points de execução (reads + applies)
Chamar `ensure_account_access` no topo de cada executor, ANTES de `build_client_for_manager`/reserva de quota:
- `src/google_ads/reports.py::run_report` → `level="read"`
- `src/google_ads/mutations.py::run_mutation` → `level="write"`
- `src/google_ads/conversions.py::run_conversion_upload` → `level="write"`
- `src/google_ads/customer_match.py::run_offline_user_data_job` → `level="write"`

Todos recebem `manager_id`, `session_id`, `customer_id` como kwargs (verificado nas assinaturas) → o helper tem acesso direto.

### 3.3 Choke point de build/preview
- `src/governance/dry_run.py::create_pending` ganha param `manager_id: UUID` e chama `ensure_account_access(... level="write")` antes do INSERT. Bloqueia o gestor de até **prever** blast (ex.: "vai pausar 47 keywords na conta X") de conta não concedida.
- Callers de `create_pending` (as tools mutate em modo dry-run) passam `ctx.manager_id`. O plano enumera os callsites via grep.

### 3.4 Tools não afetadas
Tools sem `customer_id` (`list_my_accounts`, `get_my_audit_log`, `get_my_rate_limit_status`, `list_gaql_resources`, `validate_gaql`) não passam pelos executores com gate → comportamento inalterado.

## 4. Comportamento e migração

- **Matriz autoritativa:** após o gate, MCP Google opera SÓ em contas concedidas em `manager_account_access` — alinha com o que a UI web já mostra.
- **Sem migration de DB:** a tabela + `can_manager_access` + `grant_all_active` já existem.
- **Rollout (pré-deploy, espelha o Meta):**
  1. Confirmar que cada manager tem os grants corretos. O admin (Wellington) já tem 25; conferir via `/admin/access` (aba Google).
  2. Quando os colaboradores entrarem: admin concede o subset de cada um via `/admin/access` (toggle/bulk-grant).
  3. Deploy. Conta nova sincronizada depois exige grant explícito antes de operar via MCP (correto).
- **Erro do gestor:** chamada a conta não concedida retorna PT-BR amigável ("sem acesso — peça ao admin") + audit `denied`.

## 5. Testing strategy

- **Unit (`tests/unit/test_account_access.py`):** `ensure_account_access` → allowed (não levanta) vs denied (levanta `AccountAccessDeniedError` + chama `audit_log.record` com `status="denied"`). Mock `can_manager_access` + pool, igual ao `test_meta_reports_gate.py`.
- **Integration:** estender testes existentes dos executores. Onde mockam `run_report`/`run_mutation` no nível da tool, sem mudança. Onde exercitam o executor real, adicionar grant do (manager, customer) no seed OU mockar `ensure_account_access`. Novo teste: gestor sem grant → `run_report`/`run_mutation` levantam denied + audit. `create_pending` sem grant → denied (não cria token).
- **Regressão:** garantir que os testes de mutate/dry-run existentes semeiam o grant (senão passam a falhar com denied) — `grep -rn "create_pending\|run_mutation\|run_report" tests/` no plano.
- `check_pre_push.py` antes do commit; **`check_pre_push_full.py`** obrigatório (toca `reports.py`/`mutations.py`/`dry_run.py` — choke points compartilhados).

## 6. Riscos & Out-of-scope

**Riscos com mitigação:**
- **Testes de integração existentes podem quebrar** se exercitam executores reais sem grant no seed. Mitigação: grep + ajustar seeds no plano; CI valida (testcontainers).
- **Admin bloqueado em conta nova** (footgun): mitigado por grant 1-clique + rollout note; bypass `is_admin` adicionável depois se doer.
- **`create_pending` precisa de `manager_id`:** mudança de assinatura toca N callsites de mutate tools. Mitigação: plano enumera via grep; mudança mecânica (1 kwarg).

**Out-of-scope (deliberado):**
- Bypass `is_admin` (rejeitado — ver §1).
- Bind do token `pending_confirmations` a `manager_id` (achado I1 da análise — defesa adicional, sprint separado; hoje token é por-session e session é 1:1 com manager).
- Refatorar o `login_customer_id` do MCC (continua sendo o token de execução; o gate é a camada de autorização acima dele).
- UX do gestor (Sub-projeto B, spec própria).

## 7. Critérios de signoff
- `ensure_account_access` criado + chamado nos 4 executores + `create_pending`.
- Gestor sem grant → read e mutate retornam denied PT-BR + audit `status="denied"`.
- Tools sem `customer_id` inalteradas.
- Admin com grants completos opera normalmente.
- `check_pre_push_full.py` 6/6 PASS.

## 8. Pre-checklist antes de `writing-plans`
- [ ] Review desta spec pelo gestor.
- [ ] Confirmar grants do admin cobrem as contas ativas (`/admin/access` aba Google).
