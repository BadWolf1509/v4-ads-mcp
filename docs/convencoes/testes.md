# Testes e validação

> Convenções de fixture, builder, pré-flight e validação empírica de whitelist. Leia ao escrever teste ou ao shippar tool nova.
>
> Extraído do `CLAUDE.md` em 2026-08-19: convenção é estável e específica de
> área, então carregá-la em toda sessão era imposto de contexto. As regras
> curtas (o que faz parar) seguem no `Don't do` do `CLAUDE.md`; aqui fica o
> **porquê**.
>
> Taxonomia completa dos bugs: [`findings-catalog.md`](../operacao/findings-catalog.md).

---

### Test fixture pattern (integration)


Consuma `pg`/`db`/`app_with_db`/`client` de `tests/integration/conftest.py`; **NÃO redeclare localmente** (NÃO `db_pool` — não existe). 1 container Postgres **session-scoped** + template database (`tpl_app`, migrations rodam uma vez) — cada teste clona um banco novo via `CREATE DATABASE ... TEMPLATE` (isolamento total, sem pagar boot+migrations por teste). Mark `@pytest.mark.integration`. **Teste que exercita executor real precisa de grant no seed** (`manager_account_access.grant(...)`) senão o hard-gate levanta `AccountAccessDeniedError`. Generator de streaming com cursor: o teste DEVE **consumir** o output, não só disparar a rota (F58 — CSV export ficou quebrado em prod porque nenhum teste iterou).

### Mutate builder test convention (post-3b.5, F16/F42/F44/F51)


**Use `tests/unit/fixtures/proto_capture.py::make_capture_client` (NÃO MagicMock)** ao assertar proto field assignments — MagicMock aceita qualquer atributo e mascara bugs.

```python
from tests.unit.fixtures.proto_capture import make_capture_client
client = make_capture_client()
ops = build_my_thing(client, customer_id, payload)
assert ops[0].field("ad_group_criterion_operation.create.negative") is True
assert ops[0].has("ad_group_criterion_operation.create.bid_modifier") is False
```

**Field rename guard (F51):** campo proto renomeado entre versões SDK → assertar presença do nome novo E **ausência** do antigo (`__setattr__` aceita qualquer atributo silenciosamente):
```python
assert ops[0].has("campaign_operation.create.start_date_time") is True
assert ops[0].has("campaign_operation.create.start_date") is False
```
Meta SDK usa dicts (não proto) — pattern future-only (`MetaCaptureClient` análogo quando houver mutate Meta).

### Pre-flight test convention (post-3b.5/3b.8)


Pré-flight via helper de `_common.py` → **mock o helper no namespace do TOOL** (NÃO `_common.py`):
```python
with patch("src.mcp.tools.<your_tool>.<helper_name>", AsyncMock(return_value=None)):
```
Patches em `src.mcp.tools.<tool>.run_report` NÃO cobrem o site de pré-flight. Mitigação: `check_pre_push_full.py`.

### Schema whitelist empirical validation (post-3b.19A)


Todo valor de enum em whitelist DEVE ser validado empiricamente em smoke runbook (criar entidade real por valor — SDK descriptors contêm valores que o runtime rejeita). Família: F17/F18/F19/F25/F27/F31/F32/F34/F36/F44. Smoke runbook inclui per-value probe (batch 5/call). Rejeitado → remove do schema + documenta out-of-scope.

### Guard estrutural: use o harness, não abra travessia própria (F155)

Guard estrutural é o teste que varre o source pra impedir a reincidência de uma classe de bug (`test_structural_guards.py`, `test_frontend_a11y_guards.py`, `test_ci_local_parity.py`…). **Todos passam por [`tests/unit/_guard_harness.py`](../../tests/unit/_guard_harness.py), e um guard novo também tem que passar.**

O harness existe porque 17 guards reimplementaram cada um a própria varredura, e cada reimplementação trouxe o próprio defeito de cobertura — `glob` não-recursivo, substring no texto do arquivo, leitura linha a linha, igualdade de nome de classe em vez de subclasse, caminho relativo que vê zero arquivos fora da raiz. Nenhum era erro de raciocínio sobre a invariante; eram todos erros de varredura, e o 18º apareceu exatamente porque quem o escreveu não sabia dos outros 17. Taxonomia completa: **F155** no [`findings-catalog.md`](../operacao/findings-catalog.md).

**Do que ele é dono — as duas dimensões que o guard não deve reimplementar:**

- **Escopo de arquivos:** `fontes_py()` (src/), `testes_py()` (tests/), `templates_html()`, `markdown()`, `workflows()`. Recursivos, absolutos (ancorados em `__file__`, nunca no cwd), ordenados, com `_IGNORADOS` aplicado. Âncoras prontas: `h.SRC`, `h.TESTES`, `h.TEMPLATES`, `h.RAIZ`.
- **Casamento por AST:** `arvore()`, `chama()`, `nomes_locais()` (desfaz alias de import), `funcoes()`, `lambdas()`, `excecoes_do_handler()`, `classe_de_excecao()`. Mais `rel()` pra mensagem de erro legível.

**A invariante que mata a vacuidade: escopo vazio levanta `EscopoVazioError`, nunca devolve `[]`.** Guard que varreu zero arquivos passa verde sem afirmar nada, e foi assim que o guard do relógio ficou verde ao rodar de fora da raiz do repo — 74 arquivos viravam 0, em silêncio. Nunca capture essa exceção pra "ser tolerante": ela é o sinal de que o caminho está errado.

**Limites conhecidos — não presuma cobertura que não existe:**

- `chama()` não vê despacho dinâmico (`getattr(mod, "alvo")()`), subscript, decorator bare, nome ligado por atribuição (`g = alvo; g()`) nem `functools.partial(alvo)`. Limitação de qualquer matcher sintático.
- `funcoes()` devolve só `def`/`async def`. **Lambda vem de `lambdas()`** — somar as duas é o que dá "todo escopo executável" (a promessa a mais na docstring de `funcoes()` já custou cobertura no guard do F58).
- `classe_de_excecao()` resolve só `builtins` e `asyncpg` (allowlist); nome que não resolve devolve `None` e **o guard decide** — o padrão seguro é tratar desconhecido como ofensor, nunca como isento.
- `markdown()` enraíza na RAIZ e se defende por denylist de nomes. Entra em `_IGNORADOS` o diretório que é TODO ele scratch de ferramenta; nome parcialmente versionado (ex.: `.claude`) não entra.
- `workflows()` casa só `*.yml`, não-recursivo.
- O `EscopoVazioError` protege a TRAVESSIA, não o predicado: se o guard filtra depois (`if p.name.startswith("test_")`, `_arquivos_google()`…), o conjunto pós-filtro pode ficar vazio em silêncio. Quem filtra afirma a própria população — piso ou contagem exata.

**Ao escrever ou apertar um guard:** a asserção tem que distinguir código bom de quebrado, então prove a mordida contra o código PRÉ-fix (sabotagem ou cópia — **nunca `git checkout`**) e acompanhe cada sabotagem de um controle positivo, senão um `assert False` também ficaria vermelho. Enumerar formas ofensoras não é afirmar a propriedade; e um falso positivo é pior que guard ausente, porque ensina a contorná-lo.

### No JSON Schema composition keywords (post-3b.19B.1)


`input_schema` NÃO pode ter `oneOf`/`allOf`/`anyOf` em nenhum nível (Anthropic validator rejeita). Constraints cross-field via `_validate_*` helper privado. Guard: `test_no_composition_keywords_in_any_schema`.
