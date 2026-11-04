# Archive — docs históricos V4 Ads MCP

**Created:** 2026-05-27 pós Sprint 3b.40 cleanup minucioso.

## Por que existe

Docs aqui são de **sprints SHIPPED, validados, estabilizados em produção** — preservados pra rastreabilidade histórica mas **NÃO referência diária**.

Cleanup 2026-05-27 moveu 113 files (104k → 30k lines visíveis no scope normal) pra reduzir noise contextual em sessões Claude futuras. CLAUDE.md "Reference" section atualizada pra apontar apenas docs ativos.

## Conteúdo

| Pasta | Files | O que tem |
|---|---|---|
| `plans/` | 83 | Planos de implementação de frentes entregues (Phase 0 → 3b.40 em 27/05; o resto em 04/11). |
| `specs/` | 58 | Specs de design de frentes entregues; a decisão e o porquê ficam preservados. |
| `runbooks/` | 38 | Runbooks de smoke de sprints entregues, `tool-buckets` antigos. Os de 3b.41–3b.44 ficam em `docs/operacao/`: o `test_resumo_bate_com_o_detalhe` os varre. |
| `handoffs/` | 22 | Handoffs de sessão de 29/05 a 06/10. Os 3 mais recentes ficam em `docs/operacao/`. |
| `setup/`, `dogfood/`, `varredura-2026-09-21/` | — | Material de setup, dogfood e da varredura de 21/09. |

**2ª limpeza, 2026-11-04:** 91 arquivos saíram da doc viva: planos e specs entregues há mais de 7 dias,
handoffs anteriores aos 3 últimos, o runbook do RSA e os `tool-buckets` antigos. Os
links da doc viva foram reescritos por script e conferidos pelo `tests/unit/test_docs_links.py`.

## Quando usar

✅ **OK:** Debug deep histórico ("por que sprint 3b.X tomou approach Y?"), auditoria de decisão arquitetural antiga, recovery de pattern usado em sprint específica.

❌ **NÃO usar pra:** Reference comum em sessão Claude (use `docs/operacao/sprint-history.md` que tem rows verbose com 1000+ chars per sprint), bug history (use `findings-catalog.md`), current sprint context (use active docs em `docs/superpowers/specs/` e `docs/operacao/`).

## Política

- **NÃO add novos files aqui** — adicione em `docs/superpowers/specs/` ou `docs/operacao/` primeiro
- **Move aqui** quando sprint shippar + estabilizar ≥7 dias (smoke validado, bugs caught + fixed)
- **NUNCA delete** — git history preserva mas physical access em archive é mais fluido
- **Revisitar trimestral** se algum file merece restore (improvável)

## Como acessar

```bash
# Search específico
grep -rn "F47\|PowerShell" docs/_archive/

# Restaurar arquivo pra active reference
git mv docs/_archive/specs/2026-05-XX-sprint-Y-design.md docs/superpowers/specs/

# Ver git history original (preservado)
git log --follow docs/_archive/plans/2026-05-XX-sprint-Y.md
```
