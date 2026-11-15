# Revogação de acesso na desativação do gestor: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Desativar um gestor revoga os grants Google e Meta dele, e reativá-lo devolve só esses. A rota faz isso na hora, e o job diário converge o que escapou.

**Architecture:** Duas funções novas no núcleo dos repositórios gêmeos (`_acesso_comum.py`), que operam sobre o **estado** (gestor desativado × grant vivo) e não sobre o delta. A rota `toggle-active` as chama para um gestor, na mesma transação do UPDATE e do audit. Uma etapa nova do `account_resync` as chama para todos, atrás da trava `manager_offboarding_apply`. As restaurações de churn (`restore_for_account`, Google e Meta) passam a respeitar o gestor desativado. Regra dos motivos: **o motivo nomeia o que bloqueia agora; com dois bloqueios, vale o da conta**.

**Tech Stack:** Python 3.13, asyncpg (SQL cru), FastAPI, pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-11-15-revogacao-na-desativacao-design.md`

## Global Constraints

- **Motivo novo:** `MANAGER_DEACTIVATED_REASON = "manager_deactivated"` em `src/db/repositories/motivos.py`.
- **Predicado SQL de "desativado":** `(is_active = false OR status = 'inactive')`, igual a `Manager.is_deactivated`. `invited` não conta como desativado.
- **Nada apaga linha de grant.** Revogação é `revoked_at = now()` com motivo. Restauração é `revoked_at = NULL, revoked_reason = NULL`.
- **Reativar devolve só `manager_deactivated`:** `admin_revoked`, `bulk_copy_replaced`, `left_mcc` e `partnership_ended` não voltam por esse caminho.
- **`TabelaDeAcesso` continua só com nomes** (`tests/unit/test_acesso_gemeos_conformes.py::test_descritores_diferem_so_nos_nomes`). O motivo de churn de cada lado entra por parâmetro, vindo do módulo do lado (Google `LEFT_MCC_REASON`, Meta `PARTNERSHIP_ENDED_REASON`), não como campo do descritor.
- **Trava:** `manager_offboarding_apply: bool = False` em `Settings`. Desligada, a etapa do job calcula e audita sem escrever.
  - **Não** ligar no `deploy.yml` nesta entrega: ligar é ação de produção com aval nominal, depois da primeira rodada auditada.
- **Rota:** é transação, não `best_effort`. Falha em qualquer passo desfaz o UPDATE do gestor, as revogações e o audit (`test_acesso_e_audit_sao_atomicos.py` é o modelo).
- **Gate:** antes de todo commit, `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py > /dev/null 2>&1; echo $?` tem de dar `0`, sem pipe.
- **Full sweep obrigatório** (`scripts/check_pre_push_full.py`): toda task mexe em query ou transação.
- **Guard novo** só vale com sabotagem conferida contra o código pré-fix, com controle positivo. Nunca `git checkout`.
- **Commits** `feat(db|admin|...): …` em PT-BR, com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Grant concedido a gestor já desativado** (admin marca caixa na matriz depois da desativação): a etapa do job revoga na rodada seguinte com `manager_deactivated`. Teste em T4.
2. **Conta sai do MCC enquanto o gestor está desativado, e volta antes da reativação:** a volta da conta não reabre o grant, e a reativação reabre. Teste em T2.
3. **Reativação por SQL direto** (`status` de `inactive` para `active`, com `is_active` já true): a etapa do job restaura. Teste em T4.
4. **Duas execuções seguidas** (duplo clique, retry do job): a segunda muda zero linhas e audita `had_effect=False` / contagem 0. Testes em T1 e T3.
5. **Gestor `invited`:** não é tratado como desativado, nem pelo predicado nem pela etapa. Teste em T1.

---

### Task 1: núcleo — revogar de desativados, restaurar de reativados

**Files:**
- Modify: `src/db/repositories/motivos.py` (motivo novo)
- Modify: `src/db/repositories/_acesso_comum.py` (predicado + duas funções)
- Modify: `src/db/repositories/manager_account_access.py`, `src/db/repositories/manager_meta_account_access.py` (wrappers de cada lado)
- Test: `tests/integration/test_revogacao_na_desativacao.py` (novo, `@pytest.mark.integration`, fixture `db`)
- Test: `tests/unit/test_predicado_desativado.py` (novo)

**Interfaces:**
- Produces:
  - `_acesso_comum.PREDICADO_DESATIVADO: str` = `"(m.is_active = false OR m.status = 'inactive')"`, com o alias `m` de `managers`.
  - `_acesso_comum.revogar_de_desativados(conn, t: TabelaDeAcesso, *, manager_id: UUID | None = None) -> list[tuple[UUID, str]]`: devolve `(manager_id, conta)` de cada grant revogado.
  - `_acesso_comum.restaurar_de_reativados(conn, t: TabelaDeAcesso, *, motivo_churn: str, manager_id: UUID | None = None) -> tuple[list[tuple[UUID, str]], list[tuple[UUID, str]]]`: devolve `(restaurados, remarcados_como_churn)`.
  - **Wrappers:**
    - `manager_account_access.revogar_de_desativados(conn, *, manager_id=None)` e `.restaurar_de_reativados(conn, *, manager_id=None)`, este com `motivo_churn=LEFT_MCC_REASON`;
    - em `manager_meta_account_access`, os mesmos dois wrappers, com `motivo_churn=PARTNERSHIP_ENDED_REASON`.
  - **Contagem sem escrita, para o dry-run da T4:** `_acesso_comum.planejar_convergencia(conn, t, *, motivo_churn: str) -> dict[str, int]`, com chaves `a_revogar`, `a_restaurar` e `a_remarcar`.

- [ ] **Step 1: testes de integração (falham)**, com sementes de gestor + conta + grant nas duas tabelas (parametrize `lado` em `["google", "meta"]`). Os testes:
  - `test_revoga_grants_vivos_de_desativado_com_motivo`: gestor `is_active=false` com 2 grants vivos e 1 `admin_revoked` → retorno com 2 pares; as 2 linhas ficam com `revoked_reason='manager_deactivated'`; a `admin_revoked` fica intocada.
  - `test_status_inactive_tambem_e_desativado`: `is_active=true, status='inactive'` → revoga.
  - `test_invited_nao_e_desativado`: `status='invited'` → retorno `[]`, grant vivo.
  - `test_com_manager_id_so_atinge_aquele_gestor`: dois desativados → `manager_id=A` só revoga os de A.
  - `test_restaura_so_manager_deactivated_em_conta_ativa`: gestor reativado com linhas `manager_deactivated` (conta ativa), `admin_revoked` e `bulk_copy_replaced` → só a primeira volta (`revoked_at IS NULL`, `revoked_reason IS NULL`).
  - `test_restaurar_em_conta_inativa_remarca_como_churn`: linha `manager_deactivated` numa conta `is_active=false` → continua revogada, com o motivo trocado para `left_mcc` (Google) ou `partnership_ended` (Meta); vem em `remarcados_como_churn`.
  - `test_restaurar_ignora_gestor_ainda_desativado`: gestor desativado com linha `manager_deactivated` → nada muda.
  - `test_duas_rodadas_a_segunda_nao_muda_nada`: revogar e restaurar duas vezes → a 2ª devolve vazio.
  - `test_planejar_convergencia_conta_sem_escrever`: os três números batem com o que as duas funções fariam, e nenhuma linha muda.

- [ ] **Step 2: teste unitário (falha)**: `test_predicado_sql_igual_ao_python`. Para os 6 pares `status` ∈ {`invited`, `active`, `inactive`} × `is_active` ∈ {true, false}, o `Manager.is_deactivated` Python bate com o predicado avaliado no Postgres. Fica no arquivo de integração se precisar de banco; o nome é esse.

- [ ] **Step 3: rodar** `D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/integration/test_revogacao_na_desativacao.py -m integration -q`. Expected: FAIL, por `AttributeError` ou `ImportError` nas funções novas.

- [ ] **Step 4: implementar** o motivo, o predicado, as três funções e os wrappers.
  - Cada função é **um** `UPDATE … FROM managers m … RETURNING` (ou um `SELECT count` em `planejar_convergencia`), com `_exigir_descritor(t)` no início e todo valor por bind.
  - A restauração faz dois UPDATEs na mesma conexão: primeiro remarca o que está em conta inativa, depois restaura o que está em conta ativa.
  - Quem abre a transação é o chamador.

- [ ] **Step 5: rodar de novo** o comando do Step 3. Expected: PASS. Rodar também `tests/unit/test_acesso_gemeos_conformes.py`. Expected: PASS, sem campo novo no descritor. Se o registro de gêmeos exigir as funções novas, registre-as como gêmeas.

- [ ] **Step 6: gate 0, depois commit** com a mensagem `feat(db): revogar e restaurar grants pela desativação do gestor`.

### Task 2: restaurações de churn respeitam o gestor desativado

**Files:**
- Modify: `src/db/repositories/manager_account_access.py` (`restore_for_account`)
- Modify: `src/db/repositories/manager_meta_account_access.py` (`restore_for_account`)
- Test: `tests/integration/test_revogacao_na_desativacao.py`

**Interfaces:**
- Consumes: `PREDICADO_DESATIVADO`, `MANAGER_DEACTIVATED_REASON` (T1).
- Produces: as assinaturas e os retornos de `restore_for_account` não mudam (Google `list[str]`, Meta `int`). Contam só os restaurados de fato.

- [ ] **Step 1: testes (falham)**, parametrizados por lado:
  - `test_volta_da_conta_nao_reabre_grant_de_desativado`: gestor desativado com linha `left_mcc` (ou `partnership_ended`) → `restore_for_account` não o inclui no retorno; a linha fica revogada, com `revoked_reason='manager_deactivated'`.
  - `test_volta_da_conta_reabre_gestor_ativo`: controle; o gestor ativo volta como hoje.
  - `test_ordem_conta_volta_depois_gestor_reativa`: conta sai, gestor desativa, conta volta, gestor reativa (`restaurar_de_reativados`) → grant vivo.
  - `test_ordem_gestor_reativa_depois_conta_volta`: conta sai, gestor desativa, gestor reativa (vira churn, T1), conta volta → grant vivo.

- [ ] **Step 2: rodar** os quatro. Expected: FAIL só nos três primeiros; o controle passa.

- [ ] **Step 3: implementar.** Em cada `restore_for_account`, na mesma conexão:
  - primeiro, um UPDATE que troca o motivo para `manager_deactivated` nas linhas de churn da conta cujo gestor satisfaz o predicado;
  - depois, o UPDATE de restauração atual, que continua filtrando o motivo de churn.

- [ ] **Step 4: rodar** os quatro mais os testes que já existem: `tests/integration/test_manager_account_access.py`, `test_manager_meta_account_access.py` e `test_admin_accounts*` se houver. Expected: PASS.

- [ ] **Step 5: gate 0, depois commit** com a mensagem `feat(db): volta de conta não reabre grant de gestor desativado`.

### Task 3: a rota `toggle-active` revoga e restaura

**Files:**
- Modify: `src/web/routes/admin_overview.py` (`admin_managers_toggle_active`)
- Test: `tests/integration/test_revogacao_na_desativacao.py`
- Test: `tests/integration/test_acesso_e_audit_sao_atomicos.py` (estender)

**Interfaces:**
- Consumes: os wrappers da T1.
- Produces: o audit `admin_manager_toggle_active` ganha `params_summary` com as chaves:
  - ao desativar: `{"revogados_google": int, "revogados_meta": int}`;
  - ao reativar: `{"restaurados_google": int, "restaurados_meta": int, "remarcados_google": int, "remarcados_meta": int}`.

  O toast leva o total (ex.: "Gestor desativado: 50 acessos revogados.").

- [ ] **Step 1: testes (falham)**, chamando a função da rota como o teste de atomicidade faz:
  - `test_desativar_pela_rota_revoga_e_audita_contagens`: gestor com 3 grants Google e 2 Meta → todos com `manager_deactivated`; o audit tem `revogados_google=3`, `revogados_meta=2`, `had_effect=True`.
  - `test_reativar_pela_rota_devolve_so_o_que_tirou`: depois do anterior, um `admin_revoked` extra fica revogado; os 5 voltam.
  - `test_segundo_clique_nao_muda_nada`: desativar duas vezes → o 2º audit tem `had_effect=False`, sem chamar as funções de acesso e sem `params_summary` de contagem.
  - Em `test_acesso_e_audit_sao_atomicos.py`, `test_toggle_active_nao_revoga_se_audit_falha`: o audit levanta → `is_active` continua true e os grants continuam vivos.

- [ ] **Step 2: rodar.** Expected: FAIL nos três primeiros, por contagens ausentes. O de atomicidade falha ou passa por vacuidade, porque hoje nada é revogado; só conta depois da implementação, com a sabotagem do Step 5.

- [ ] **Step 3: implementar.** Dentro do `async with pool.acquire() as conn, conn.transaction():` que já existe, depois de `definir_ativo` e só quando `mudou`, chamar os wrappers das duas tabelas com `manager_id=manager_id`, e montar o `params_summary` passado ao `_audit_admin`. Se `_audit_admin` não aceitar `params_summary`, acrescente o parâmetro opcional com default `None`.

- [ ] **Step 4: rodar** os quatro e `tests/browser`. Expected: PASS. O browser usa a rota fake, então o texto do toast não pode quebrar o seletor.

- [ ] **Step 5: sabotagem** do teste de atomicidade, por monkeypatch: as revogações rodam numa conexão fora da transação → o teste fica vermelho. Desfazer.

- [ ] **Step 6: gate 0, depois commit** com a mensagem `feat(admin): desativar gestor revoga acessos e reativar devolve`.

### Task 4: etapa de convergência no job diário, atrás da trava

**Files:**
- Modify: `src/config.py` (`manager_offboarding_apply: bool = False`, com comentário igual ao das outras travas)
- Modify: `src/jobs/account_resync.py` (`_etapa_gestores` e a ordem em `_corpo`)
- Test: `tests/integration/test_revogacao_na_desativacao.py`
- Test: os testes do `account_resync` que fixam a ordem das etapas, se existirem (`grep -rn "_etapa_" tests`)

**Interfaces:**
- Consumes: os wrappers e `planejar_convergencia` (T1).
- Produces: `async def _etapa_gestores(pool: connection.PoolValidado, settings: Settings) -> bool` (True = falhou), mais uma linha de audit por plataforma via `record_job_run`:
  - `operation="manager_offboarding_reconcile"`;
  - `platform` = `"google"` ou `"meta"`;
  - `status="success"`;
  - `target_count` = revogados + restaurados;
  - `params_summary={"apply": bool, "a_revogar": n, "a_restaurar": n, "a_remarcar": n}`, mais, com apply, os efetivos `revogados`, `restaurados` e `remarcados`.

- [ ] **Step 1: testes (falham):**
  - `test_etapa_com_trava_desligada_audita_e_nao_escreve`: 2 desativados com grants → nenhuma linha muda; 2 audits com `apply=False` e `a_revogar` corretos.
  - `test_etapa_com_trava_ligada_converge`: revoga os vivos de desativados (Review Focus 1) e restaura um reativado por SQL (`status` `inactive`→`active`, Review Focus 3).
  - `test_etapa_roda_mesmo_sem_oauth`: `_etapa_google` devolve `SEM_OAUTH` → `_etapa_gestores` roda mesmo assim, e o exit code continua 1.
  - `test_etapa_que_falha_entra_no_exit_code`: a etapa levanta → o job termina o purge e sai com 1, com `record_job_run(status="error")`.

- [ ] **Step 2: rodar.** Expected: FAIL.

- [ ] **Step 3: implementar.**
  - **Ordem em `_corpo`:** Google → Meta → **gestores** → purge. No `SEM_OAUTH`, rodar gestores e purge antes do `return 1`: a etapa não depende do Google.
  - **A etapa:** uma conexão e uma transação para as duas tabelas. Com a trava desligada, só `planejar_convergencia`. Com ela ligada, `planejar_convergencia` e depois as funções.
  - **Audit:** sob `best_effort`, depois do commit, como o purge.

- [ ] **Step 4: rodar** os quatro e os testes do `account_resync`. Expected: PASS.

- [ ] **Step 5: full sweep** (`D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push_full.py`). Expected: `All pre-push checks passed`.

- [ ] **Step 6: gate 0, depois commit** com a mensagem `feat(jobs): convergência diária de grants de gestor desativado, atrás de trava`.

**Pronto (depois do merge, cada passo com aval nominal):**
1. Deploy e `/health?deep=1`.
2. Clique em produção: desativar e reativar um gestor de teste sem grants reais, ou um dos 2 já desativados se o Wellington preferir, e conferir as contagens no audit.
3. A primeira rodada do job: ler o audit `manager_offboarding_reconcile` com `apply=False` (espera-se cerca de 95 `a_revogar`).
4. Ligar `MANAGER_OFFBOARDING_APPLY=true` no `JOB_ENV_VARS` do `deploy.yml`.
