# V4 Ads MCP — agent context

**O contexto canônico deste repo é o [`CLAUDE.md`](CLAUDE.md). Leia-o primeiro — ele vale integralmente para o Codex.**

Este arquivo existe só porque o Codex carrega `AGENTS.md` automaticamente. Ele
não repete o conteúdo de propósito.

## Por que não é uma cópia

Até 2026-08-11 este arquivo era um fork do `CLAUDE.md` gerado por find-replace
(daí o antigo "Codex/Codex/Cursor" na abertura). Ele ficou **26 commits
atrasado** e passou a ensinar o oposto do que o repo pratica: dizia "Tailwind
CDN" e "sem build step" depois do CDN ser aposentado, e não conhecia a CSP sem
`unsafe-*`. Um agente seguindo essas instruções escreveria `onclick` inline —
que o browser hoje **bloqueia em silêncio**.

Documento duplicado diverge. A regra aqui é a mesma dos hooks: uma fonte só.

## Específico do Codex

- **Hooks:** `.codex/hooks.json` aponta para os `.ps1` de `.claude/hooks/` — não
  duplique os scripts. A raiz é resolvida por `git rev-parse --show-toplevel`.
- **Subagentes:** `.codex/agents/*.toml`, equivalentes aos `.claude/agents/*.md`.
- **Skills:** `.agents/skills/` — cópia inevitável (o Codex lê desse caminho),
  mantida idêntica à de `.claude/skills/` por guard.
- **MCP:** `.codex/config.toml`.

Os guards que sustentam tudo isso estão em `tests/unit/test_tooling_parity.py`,
inclusive um que impede este arquivo de voltar a ser um fork.
