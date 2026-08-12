---
name: findings-add
description: Adiciona uma nova entrada F## em docs/operacao/findings-catalog.md de forma consistente — auto-incrementa o número F, classifica na bug class correta, atualiza a tabela cross-reference de sprint e os totals do summary. Use após signoff de smoke quando um novo finding emergiu. Side effect — user-only.
disable-model-invocation: true
---

# Skill: `/findings-add`

Adiciona uma nova entrada padronizada ao `docs/operacao/findings-catalog.md`.

## O que essa skill faz

1. Abre `docs/operacao/findings-catalog.md`
2. Determina o próximo F## (max existente + 1)
3. Pergunta ao usuário os dados estruturados do finding
4. Anexa a row na bug class correta
5. Atualiza a tabela "Cross-reference: Sprint → findings introduced"
6. Atualiza a "Summary by status" (+1 no status correto)
7. Atualiza "Total findings tracked"
8. Atualiza o cabeçalho "Last updated"

## Inputs requeridos do usuário

Faça uma única pergunta consolidada (4 sub-questões) usando `AskUserQuestion`:

1. **Sprint origem** — em qual sprint o finding emergiu? (ex: `3b.27`)
2. **Bug class** — qual das 6 classes? Opções:
   - `1` Silent-acceptance design gap (Google API contract gaps via SDK ambiguity)
   - `2` Schema/serialization gaps (Anthropic API + MCP transport)
   - `3` Pre-flight + test convention (mock target mistakes)
   - `4` UX / dogfood ergonomics
   - `5` Runbook typos (documentation fixes)
   - `6` Google constraint (known limitation, not a code bug)
3. **Severity** — CRIT, HIGH, MED, ou LOW
4. **Status** — `Fixed` / `Doc fix only` / `Not-a-bug` / `Known limitation` / `Open`

Em seguida peça (em mensagem separada):
5. **Resumo de 1-3 linhas** do finding (incluir symptom + root cause + fix se aplicável)
6. **Sprint de fix** (se Fixed/Doc fix — ex: `3b.27.1`; se Open ou Not-a-bug, deixar vazio)

## Procedimento de edição

### Passo 1: Ler o catalog
Use `Read` no `docs/operacao/findings-catalog.md`. Localize:
- O F## máximo atual em todas as tabelas de bug class (grep por `\*\*F(\d+)\*\*`).
- O total atual em "Total findings tracked: NN".
- O contador atual em "Summary by status" para a linha que aplica.
- A última row da tabela "Cross-reference: Sprint → findings introduced" — pode precisar adicionar sprint novo se ainda não existe.

### Passo 2: Construir a row nova
Format exato (manter alinhamento e bullets `**...**`):

```
| **F<NN>** | <SEV> | <sprint_origem> | <sprint_fix_or_status> | <resumo>. [<runbook_link>] |
```

Onde `<sprint_fix_or_status>`:
- Fixed → `<sprint_fix>` (ex: `3b.27.1`)
- Doc fix only → `<sprint_fix> doc`
- Not-a-bug → `not-a-bug`
- Known limitation → `doc-only` ou `known limitation`
- Open → `open` (deixar literal)

E `<runbook_link>` aponta pra `phase-3b-XX-bootstrap.md` da sprint origem.

### Passo 3: Aplicar edits

Usando `Edit` no arquivo (1 edit por mudança — não bater em concorrência):

1. **Append row à bug class table escolhida** — encontrar a última row da tabela correta e usar `Edit` pra adicionar logo depois.
2. **Atualizar cross-reference table** — encontrar a row da sprint origem (ex: `| 3b.27 | ...`). Se existir, anexar `F<NN>` à lista. Se não, adicionar row nova preservando ordem cronológica.
3. **Atualizar Summary by status** — incrementar contador da linha do status escolhido. Padrão: `<status> | N` → `<status> | N+1`.
4. **Atualizar Total findings tracked** — `Total findings tracked:** NN (was XX + F<NN>)`.
5. **Atualizar Last updated** — no topo: `> **Last updated:** YYYY-MM-DD (Sprint <origem> signoff)` ou similar.

### Passo 4: Confirmar com o usuário
Mostre as 5 edits aplicadas em sumário:
- Row anexada em "Bug class N"
- Cross-reference: row da sprint X (criada/atualizada)
- Summary: status Y de N → N+1
- Total: NN → NN+1
- Last updated

Pergunte se deve commitar ou se deixa pra commit manual junto com outros docs do sprint.

## Quando NÃO usar

- Bug ainda não confirmado (smoke não rodou) — espera o smoke confirmar
- Finding já catalogado — verificar antes (grep por descrição similar)
- Update de finding existente — usar `Edit` direto, não essa skill

## Exemplo de invocação completa

```
user: /findings-add
assistant: [usa AskUserQuestion com 4 sub-questões]
user: [responde] sprint=3b.27 / class=1 / sev=HIGH / status=Fixed
assistant: [pergunta resumo + fix sprint]
user: "Tool X rejeitou valor Y. Fix: schema removed Y."  / fix=3b.27.1
assistant: [aplica os 5 edits]
assistant: F43 adicionada à bug class 1. Total: 38→39. Cross-ref sprint 3b.27 atualizada. Summary: Fixed de 26→27.
```
