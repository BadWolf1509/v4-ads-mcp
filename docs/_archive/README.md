# Archive — docs históricos V4 Ads MCP

**Created:** 2026-05-27 pós Sprint 3b.40 cleanup minucioso.

## Por que existe

Docs aqui são de **sprints SHIPPED, validados, estabilizados em produção** — preservados pra rastreabilidade histórica mas **NÃO referência diária**.

Cleanup 2026-05-27 moveu 113 files (104k → 30k lines visíveis no scope normal) pra reduzir noise contextual em sessões Claude futuras. CLAUDE.md "Reference" section atualizada pra apontar apenas docs ativos.

## Conteúdo

| Pasta | Files | O que tem |
|---|---|---|
| `plans/` | 40 | Implementation plans de sprints Phase 0/1a/2 + Sprints 3b.1 → 3b.37 SHIPPED. Execution scripts que serviram durante deploy — agora apenas rastreabilidade. |
| `specs/` | 35 | Design specs de sprints SHIPPED ≥14 dias. Decisional rationale preservado pra auditoria futura. |
| `runbooks/` | 29 | `phase-XX-bootstrap.md` smoke runbooks de sprints SHIPPED ≥7 dias. Validação already-done, smoke results captados em sprint-history.md. |
| `setup/` | 3 | `frontend-audit-2026-05.md` (FE pré-redesign baseline) + `gcp-mcp-setup.md` (failed attempt GCP MCP — reverted) + `standard-access-design-doc.md` (Google Ads Standard Access application doc). |

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
