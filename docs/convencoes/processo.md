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


`superpowers:subagent-driven-development` — fresh subagent/task + 2-stage review (spec + quality). Model: **haiku** (mecânico 1-2 arquivos) · **sonnet** (integração multi-arquivo, dispatchers, OAuth) · **opus** (arquitetura/review cross-cutting). Nunca despache implementers em paralelo em arquivos OVERLAPPING — só em arquivos não sobrepostos; reviewers paralelos sempre OK. Adaptações comuns: `db_pool`→`db`, `audit_log.id: UUID`→int, `rate_counters.used_today`→`operations_used`.

### Tool bucket classification (post-3b.39 F1)


`@register_tool` aceita `bucket: Literal["always","defer"]` (default `"defer"`). Cada tool: `# bucket: …` line 1 + prefix `[CORE]`/`[DEFER]` + `_meta`. **D3:** bucket="always" → `_meta` inclui `"anthropic/alwaysLoad": true` (Claude Code v2.x `ENABLE_TOOL_SEARCH=true` defere tudo por default; este field promove always-loaded). O prefixo e o kwarg sao a MESMA afirmacao em dois lugares e `test_prefixo_da_descricao_concorda_com_o_bucket` (`tests/unit/test_registry_bucket.py`) cobra os dois de toda tool registrada — reclassificar so no kwarg deixa a descricao mentindo sem quebrar nada. Source: [`tool-buckets-2026-09-04.md`](../operacao/tool-buckets-2026-09-04.md) (reclassificacao mensal; a de maio esta superseded).

### Fechamento de sprint com tool mutante: APPLY e RESTAURAÇÃO nunca ficam `⬜ pending`


Sprint que shippa ou muda uma tool mutante não fecha com os passos de **APPLY** ou de **RESTAURAÇÃO** marcados `⬜ pending` no checklist — os dois já morderam na mesma sprint (04/09, F150/F151). O F150 foi pra produção **prevendo** a mutação (dry-run) sem que o builder jamais tivesse sido registrado: ninguém tinha exercitado o caminho de aplicar de fato. O F151 foi o inverso — o preview de `clear_schedule` dizia que a restauração **zerava** a entrega quando na verdade a `RESTAURAVA` (a única operação que devolve a campanha a 24x7). As duas são a mesma classe — **ausência de tratamento de um caminho** —, e nas duas **três revisões de código passaram por cima**, porque revisão lê o código ESCRITO, não a lacuna do que nunca rodou. Corolário prático: nenhum sprint de tool mutante fecha sem smoke que exercite o caminho de APPLY **e** o de RESTAURAÇÃO — revisão de código não substitui execução.

### Procedimentos operacionais (raros)


- **Rotação Bearer v4-ads:** tokens SÓ válidos se issued via UI (NÃO inventar — backend valida hash, 401 se não bate). `/sessions` → Nova session → flash 60s do plaintext → cola em `~/.claude.json` `mcpServers.v4-ads.headers.Authorization` → restart → revoga antigo. NUNCA cole secret em chat.
- **Criar secret GCP (F47):** SEMPRE arquivo binary intermediário, NUNCA pipe `echo|gcloud` no PowerShell (CRLF mangling): `python -c "open('tmp.bin','wb').write(b'<v>')"` → `gcloud secrets versions add <name> --data-file=tmp.bin` → `Remove-Item tmp.bin; Clear-History`.
- **Remover field de `INSIGHTS_FIELDS_*`/enum whitelist:** `grep -rn "field_name" tests/` ANTES (check_pre_push não pega integration DB).
- **`uv pip compile` sempre com `--universal`, em qualquer lugar que instrua o comando** (doc, workflow, commit): sem a flag o `pywin32` sai sem marker de plataforma e o buildpack CNB quebra o build no Linux (F113) — já aconteceu pelo próprio `ci.yml`, que chegou a documentar o comando sem a flag.
- **Campo obrigatório novo em `Settings` → declare TAMBÉM nos 3 Cloud Run Jobs do `deploy.yml`** (`migrate`, `resync`, `backup`): os três rodam o mesmo codebase e chamam `get_settings()`, que valida o `Settings` inteiro na subida — inclusive `migrate` e `backup`, que funcionalmente só usam o banco (F114). Edite o env desses jobs com `--update-*` (merge), nunca `--set-*` (replace): é job cujo estado atual você não consegue enumerar de antemão.
- **Capture a revisão de rollback ANTES do deploy — nunca deduza por ordem de criação:** deduzir a revisão anterior pela ordem de criação só coincide com "a que estava servindo" quando o deploy chega a criar uma revisão nova; um `gcloud run deploy` que falhe SEM criar revisão (imagem inexistente, flag inválida, quota) desloca a dedução em um, e o rollback tiraria tráfego da revisão saudável que está no ar pra pousar numa mais velha — regressão provocada pelo próprio mecanismo de segurança (F116).
- **Não deixe check bloqueante só no CI:** o gate local (`check_pre_push.py`) tem que cobrir o mesmo check, senão ele só aparece tarde, depois da espera do runner, já em push (F115; nasceu do guard do Tailwind, que por um tempo só existia nos 9 steps do CI e não nos 5 do gate local).
- **Antes de adicionar qualquer dependência, cheque "no build step":** este projeto não tem build step nem em runtime nem em deploy — HTMX via CDN, Tailwind gerado offline (`python scripts/build_tailwind.py`, CSS commitado) — e nenhuma dependência nova pode introduzir um (node/Vite/React etc.). Confirme isso ANTES de editar `pyproject.toml`, não depois.
- **Dependência nova de PROD:** edite `pyproject.toml` E regenere `requirements.txt` no MESMO commit com `uv pip compile pyproject.toml -o requirements.txt --universal` — sem markers de plataforma o `pywin32` win-only quebra o build Linux/CNB; buildpack e CI instalam desse lockfile.
