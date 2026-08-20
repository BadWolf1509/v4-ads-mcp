# Processo e entrega

> Princípios de código, subagentes, buckets de tool, procedimentos raros. Leia ao planejar trabalho ou executar procedimento operacional.
>
> Extraído do `CLAUDE.md` em 2026-08-19: convenção é estável e específica de
> área, então carregá-la em toda sessão era imposto de contexto. As regras
> curtas (o que faz parar) seguem no `Don't do` do `CLAUDE.md`; aqui fica o
> **porquê**.
>
> Taxonomia completa dos bugs: [`findings-catalog.md`](../operacao/findings-catalog.md).

---

### Princípios de código (Karpathy)


Heurísticas-teste pra reduzir erros típicos de LLM. Complementam o system prompt + cultura YAGNI. Fonte: [`andrej-karpathy-skills`](https://github.com/multica-ai/andrej-karpathy-skills).

- **Teste das 200→50:** se escreveu 200 linhas e dava 50, reescreva. "Um eng. sênior chamaria isso de overcomplicado?" → se sim, simplifique.
- **Rastreabilidade da diff:** cada linha alterada rastreia direto ao pedido. Não "melhore" código adjacente nem refatore o que não está quebrado; remova só os órfãos que SUAS mudanças criaram.
- **Tarefa → meta verificável:** "corrige o bug" → "escreve teste que reproduz, depois faz passar".
- **Premissas explícitas:** múltiplas interpretações → apresente, não escolha em silêncio. Push back quando há caminho mais simples.

### Subagent-driven development


`superpowers:subagent-driven-development` — fresh subagent/task + 2-stage review (spec + quality). Model: **haiku** (mecânico 1-2 arquivos) · **sonnet** (integração multi-arquivo, dispatchers, OAuth) · **opus** (arquitetura/review cross-cutting). Implementers paralelos OK só em arquivos não-overlapping; reviewers paralelos sempre OK. Adaptações comuns: `db_pool`→`db`, `audit_log.id: UUID`→int, `rate_counters.used_today`→`operations_used`.

### Tool bucket classification (post-3b.39 F1)


`@register_tool` aceita `bucket: Literal["always","defer"]` (default `"defer"`). Cada tool: `# bucket: …` line 1 + prefix `[CORE]`/`[DEFER]` + `_meta`. **D3:** bucket="always" → `_meta` inclui `"anthropic/alwaysLoad": true` (Claude Code v2.x `ENABLE_TOOL_SEARCH=true` defere tudo por default; este field promove always-loaded). Source: [`tool-buckets-2026-05-25.md`](../operacao/tool-buckets-2026-05-25.md).

### Procedimentos operacionais (raros)


- **Rotação Bearer v4-ads:** tokens SÓ válidos se issued via UI (NÃO inventar — backend valida hash, 401 se não bate). `/sessions` → Nova session → flash 60s do plaintext → cola em `~/.claude.json` `mcpServers.v4-ads.headers.Authorization` → restart → revoga antigo. NUNCA cole secret em chat.
- **Criar secret GCP (F47):** SEMPRE arquivo binary intermediário, NUNCA pipe `echo|gcloud` no PowerShell (CRLF mangling): `python -c "open('tmp.bin','wb').write(b'<v>')"` → `gcloud secrets versions add <name> --data-file=tmp.bin` → `Remove-Item tmp.bin; Clear-History`.
- **Remover field de `INSIGHTS_FIELDS_*`/enum whitelist:** `grep -rn "field_name" tests/` ANTES (check_pre_push não pega integration DB).
