---
name: sprint-bootstrap
description: Inicia uma nova sprint V4 Ads MCP — cria o plano em docs/superpowers/plans/, dispara o subagent smoke-runbook-generator pro runbook de smoke, e adiciona row "in progress" na tabela Current state do CLAUDE.md. Use no começo de cada sprint depois de alinhar o escopo e antes de começar implementação. Side effect — user-only.
disable-model-invocation: true
---

# Skill: `/sprint-bootstrap`

Empacota a criação dos 3 artefatos que toda sprint V4 Ads MCP produz no kickoff.

## O que essa skill faz

1. Coleta metadados da sprint (número, tool name, escopo, account de smoke)
2. Cria o plano em `docs/superpowers/plans/YYYY-MM-DD-sprint-<numero>-<slug>.md`
3. Cria o runbook em `docs/operacao/phase-<numero>-bootstrap.md` (delega ao subagent `smoke-runbook-generator`)
4. Adiciona row "in progress" na tabela "Current state" do `CLAUDE.md`

## Inputs requeridos

Use `AskUserQuestion` com 4 questões consolidadas:

1. **Sprint number** — formato `3b.XX` (ex: `3b.27`). Verificar no `CLAUDE.md` o último número usado e sugerir o próximo.
2. **Tool name** — snake_case (ex: `upload_customer_match_list`). Será usado nos 3 arquivos.
3. **Escopo em 1-2 sentences** — o que essa sprint vai entregar? (vai pro Purpose do plano e do runbook).
4. **Account de smoke** — default `1163862076` (Nutry sandbox). Perguntar se for diferente.

## Procedimento

### Passo 1: Validar pré-condições
- Conferir `git status`. Se houver mudanças não commitadas em `src/`, avisar ao usuário e perguntar se deve seguir mesmo assim (não bloquear).
- Conferir se o sprint number ja existe (`docs/superpowers/plans/*sprint-<numero>*` ou `docs/operacao/phase-<numero>-bootstrap.md`). Se existir, perguntar se quer sobrescrever ou usar próximo número.

### Passo 2: Criar o plano

Path: `docs/superpowers/plans/{YYYY-MM-DD}-sprint-{numero}-{slug}.md`

Onde:
- `YYYY-MM-DD` = hoje (`Get-Date -Format "yyyy-MM-dd"`)
- `slug` = `tool_name` com hífen ao invés de underscore (ex: `upload-customer-match-list`)

Template do plano (manter terso — o detalhe vai na execução):

```markdown
# Sprint <numero> — <tool_name>

**Started:** <YYYY-MM-DD>
**Operator:** wellinton.ribeiro@v4company.com
**Smoke account:** <account_id> (<account_name>)

## Purpose

<escopo do user>

## Scope

- [ ] Schema + tool registration em `src/mcp/tools/<tool_name>.py`
- [ ] Builder + dispatcher (se aplicável) em `src/google_ads/`
- [ ] Unit tests em `tests/unit/test_<tool_name>.py` (use `make_capture_client` se mutate)
- [ ] Integration test em `tests/integration/test_<tool_name>_*.py` se há pre-flight async
- [ ] Smoke runbook em `docs/operacao/phase-<numero>-bootstrap.md`
- [ ] V4 invariants hardcoded (BR + pt-BR + BRL + -03:00 timezone + LGPD se aplicável)

## Out of scope

[O que NÃO vai nessa sprint — listar pra evitar scope creep]

## V4 invariants pra essa tool

[Listar invariantes que aplicam — depende do tipo do tool. Exemplos:
- country=BR
- language_code=pt-BR
- currency_code=BRL
- timezone=-03:00
- consent.ad_user_data=GRANTED (LGPD)]

## Pre-flight design

- **Layer 1 (schema):** [validations JSON Schema — maxItems, pattern, enum, etc]
- **Layer 2 (runtime _validate_*):** [validations Python pré-Google call]
- **Layer 3 (async pre-flight):** [GAQL queries pra validar IDs/types]

## Test scenarios (vão pro runbook)

[Listar T1..TN — o subagent smoke-runbook-generator usa essa seção pra montar o runbook.]

- **T1** — dry_run happy path
- **T2** — pre-flight: invalid ID
- **T3** — [...]
- **TN** — per-value empirical probe (se há enum whitelist)

## Risks / open questions

[Lista de incertezas pra resolver durante implementação]

## Dependencies

[Outros tools, migrations, helpers compartilhados que precisam existir antes]
```

### Passo 3: Disparar o subagent smoke-runbook-generator

Use o `Agent` tool com `subagent_type: smoke-runbook-generator`. Passe:

```
Crie o runbook de smoke para Sprint <numero>, tool <tool_name>, account <account_id>.
Spec/plan path: docs/superpowers/plans/<YYYY-MM-DD>-sprint-<numero>-<slug>.md
```

Aguarde o subagent terminar antes do próximo passo. O subagent escreve o arquivo direto.

### Passo 4: Atualizar CLAUDE.md

Localize a tabela "Shipped + in production" em `CLAUDE.md`. Logo após a última row "shipped" adicionar:

```
| Sprint <numero> — `<tool_name>` (<descricao curta>) | 🚧 in progress | Plan: [docs/superpowers/plans/...]. Runbook: [docs/operacao/phase-<numero>-bootstrap.md]. Tool count NN → NN+1. |
```

Use `Edit` no CLAUDE.md. Marker pra append: a row anterior última.

### Passo 5: Reportar ao usuário

Resposta final (terse, PT-BR):

```
Sprint <numero> bootstrapped:
- Plan: docs/superpowers/plans/<YYYY-MM-DD>-sprint-<numero>-<slug>.md
- Runbook: docs/operacao/phase-<numero>-bootstrap.md (TN tests scaffolded)
- CLAUDE.md: row "in progress" adicionada

Próximo: edite o plano com test scenarios concretos antes de começar implementação.
```

## Quando NÃO usar

- Sub-sprint fix iteration (ex: 3b.26.1) — usar `Edit` direto no runbook existente, não esta skill.
- Mudança em tool existente sem nova sprint — `Edit` direto.

## Erros comuns a evitar

- **Não pular o subagent.** O smoke-runbook-generator tem o contexto certo dos runbooks anteriores (3b.24/25/26). Se você gerar o runbook inline aqui, vai sair mais pobre.
- **Não adicionar row "shipped" no CLAUDE.md** — usar "in progress". Wellington atualiza pra "shipped" só após o smoke signoff.
- **Não criar plano em outro lugar.** Convenção do repo é `docs/superpowers/plans/`.
