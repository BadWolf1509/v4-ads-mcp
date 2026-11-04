---
name: findings-add
description: Adiciona entradas F## em docs/operacao/findings-catalog.md na convenção atual (seção `## F<n>` no fim do arquivo, um ID por causa comum) e atualiza o Last updated e a cross-reference. Use quando um finding foi confirmado (medido, não suposto). Side effect — user-only.
disable-model-invocation: true
---

# Skill: `/findings-add`

Registra findings confirmados no [`findings-catalog.md`](../../../docs/operacao/findings-catalog.md).

**Convenção vigente (desde o F141, 03/09):** cada finding é uma **seção no fim do arquivo**. As tabelas
das "Bug class 1–7" e o bloco "Summary and open items" são históricos (até ~F140) — **não** acrescente
linha nelas e **não** atualize contadores: o catálogo aboliu a contagem de IDs de propósito (F192, ver
"Como ler" no topo do arquivo).

## Passo 1 — o que entra

Pergunte num único `AskUserQuestion`:

1. **Quais achados** (multiSelect) — liste os candidatos da sessão com uma linha de evidência cada.
2. **Numeração** — um F por causa comum, com os bugs como subitens (padrão do F193, F200, F206), ou um F
   por bug.
3. **Onde vai o commit** — na branch/PR já aberto da sessão, branch própria, ou só local.

Não pergunte sprint, bug class nem severidade: proponha você, a partir da evidência, e o usuário corrige.

## Passo 2 — antes de escrever

- **Próximo ID:** `grep -on "^## F[0-9]\+" docs/operacao/findings-catalog.md | tail -1` (+1). Confira
  também `| **F<n>** |` e `- **F<n> (` — um ID aparece em três formas.
- **Duplicado:** grep pela palavra-chave do sintoma; se já existe, edite a entrada existente.
- **Toda afirmação da entrada precisa de fonte nesta sessão** (teste, log, ledger, commit). O que não foi
  medido entra como "não medido", nunca como feito (ex.: sabotagem que o ledger não registra).

## Passo 3 — a entrada

```markdown
## F<n> (<SEV>, ✅ CORRIGIDO <AAAA-MM-DD>, #<PR>, revisão `<rev>`) — <título: o sintoma em uma frase>

**Sintoma:** o que o gestor ou o CI viu.

**Causa (medida):** o mecanismo, com a evidência (probe, log, arquivo:linha).

**✅ O que foi feito:** a correção e o **guard** (nome do teste; vermelho contra o código antigo, verde
agora).

**Fora, com o motivo:** o que ficou deliberadamente de fora.

**🔑 Lição:** só quando há uma que vale para outras frentes.
```

Status: `✅ CORRIGIDO <data>`, `ABERTO`, `em parte`, `limitação da API`, `not-a-bug`. SEV: LOW, MEDIUM,
HIGH, CRITICAL.

## Passo 4 — o entorno

1. **Last updated** (topo do catálogo): prefixe a linha com a data e os IDs novos.
2. **Cross-reference** (tabela "Sprint → findings introduced"): uma linha da sessão.
3. **Faixa de IDs:** "IDs de **F1 a F<n>**" no "Como ler" do catálogo e "F1–F<n>, ~N linhas, N KB" no
   `CLAUDE.md` (o `CLAUDE.md` tem orçamento — `tests/unit/test_docs_links.py`).
4. **`estado-atual.md` e o handoff da sessão:** troque "aguarda `/findings-add`" pelos IDs; finding
   ABERTO entra na tabela "Findings abertos".
5. Rode `scripts/check_pre_push.py` (links e orçamento) antes do commit.

## Quando NÃO usar

- Bug não confirmado (smoke não rodou, hipótese sem probe).
- Atualização de finding existente — edite a entrada direto.
