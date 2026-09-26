> **Relatório bruto** de um dos 5 agentes da varredura de 21/09 — recorte: mocks que não conseguem expressar o bug.
> Recuperado do transcript da sessão em 25/09 e reproduzido **sem edição**. Os status
> ("CONFIRMADO", "PLAUSÍVEL") são do agente, não verificação nossa; o destino de cada
> achado está no [índice](README.md).

---

## Population measured first

| Métrica | Valor |
|---|---|
| Arquivos de teste | **328** (247 unit / 81 integração), 48.940 linhas unit |
| Usam `MagicMock` | 161 |
| Usam `patch`/`monkeypatch` | 216 |
| Definem fake que recebe argumentos | 63 |
| **Fakes que ignoram TODOS os parâmetros nomeados** (varredura AST) | **49, em 20 arquivos** |
| Guards estruturais com varredura própria | 31 (25 usam `_guard_harness`, 13 reimplementam) |

Dos 49 fakes cegos, 38 são `fake_run_report(**kwargs)` em validadores de pré-flight e 6 são smoke tests de envelope cujas docstrings dizem "smoke" — não afirmam cobrir discriminação. Descartei ambos os grupos.

---

## Achado 1 — CONFIRMADO (o único)

**`Unpack` do protobuf: o fake não consegue expressar a falha, e ainda rejeitaria a correção**

- **Fake:** `D:\v4-ads-mcp\tests\unit\test_mutations_partial_failure.py:82` — `def fake_unpack(target_pb: MagicMock) -&gt; None: target_pb.errors = fake_errors`
- **Mesmo fake em mais 5 sítios:** `tests\unit\test_reporta_o_que_aconteceu.py:303` e `:627`; `tests\integration\test_add_keywords.py:84`, `test_apply_audience.py:81`, `test_remove_audience.py:90`, `test_add_negatives_from_search_terms.py:86`
- **Código coberto:** `D:\v4-ads-mcp\src\google_ads\partial_failure.py:90-93`

O que o teste **afirma** cobrir: a extração de quem falhou num lote parcial (`erros_por_indice`), base de `partial_failures`, `members_failed` e `failures`.

**Probe empírica (local, sem rede).** `Any.Unpack()` devolve `bool`; em mismatch devolve `False`, **não levanta**, e **não toca o alvo**. Rodei o decoder real com `GoogleAdsFailure` reais:

```
A) servidor v24, cliente v24  -&gt; {1: ErroDeLinha(...)}          filtro passou: True
B) servidor v22, cliente v24  -&gt; {}   (silencioso)              filtro passou: True
```

A linha 90 filtra por **substring** (`"GoogleAdsFailure" not in raw.type_url`), que admite qualquer versão; a linha 93 **descarta o retorno** do `Unpack`. Resultado: skew de versão → `failure_pb.errors` vazio → `{}` sem exceção, logo o `except Exception: log.exception(...)` nunca dispara. **Nada fica vermelho e nada é logado.**

**A implementação errada concreta contra a qual o teste passa verde:** a que está em produção — `raw.Unpack(failure_pb)` com retorno descartado. O fake popula `target_pb.errors` incondicionalmente, então v20 e v24 dão o mesmo verde, exatamente como lista e string davam no F189.

**E o inverso, que é mais grave:** a correção defensiva

```python
if not raw.Unpack(failure_pb):
    log.warning("partial_failure_type_url_incompativel", type_url=raw.type_url, **contexto)
    continue
```

faria os testes ficarem **VERMELHOS** — `fake_unpack` devolve `None` (falsy), o loop pularia, e `test_mutations_partial_failure.py:172` (`"error": "CRITERION_EXISTS"`) quebraria. O fake não apenas deixa de expressar o bug: ele **bloqueia o conserto**.

**Sinal de que isso já corroeu:** 6 arquivos fixam `type_url` em **v20** — versão que **não existe no SDK instalado** (`google-ads==31.1.0` expõe apenas v21–v24). O resto do repo migrou para v24; esses não, porque o fake ignora o campo e nada quebrou. É a anotação `path: list[str]` de novo, em outra roupa. Não há guard algum de consistência de `type_url` (`grep type_url` → só esses 6 testes e o próprio decoder).

**Consequência em produção, por chamador** (o dano não é uniforme):

1. **`src\google_ads\customer_match.py:306-315` — GRAVE.** `membros_recusados` vem **exclusivamente** de `erros_por_indice`; a própria docstring diz que esse RPC não tem lista por-op. Com `{}`: `submetidos() = member_count - 0` (linha 129) e `members_failed = 0` (linhas 401/447/458). A tool reporta **o lote inteiro de PII hasheada como aceito** quando o Google recusou membros — reintroduz em silêncio exatamente o bug que o comentário R1-I3 diz ter corrigido ("Sem ler isto, `members_submitted` reportava o lote INTEIRO"). Família F182/F184/F187: não medido virando zero.
2. **`mutations.py:80` e `conversions.py:292` — moderado.** A detecção de falha vem de outra via (`WhichOneof` / `conversion_action` vazio), então as contagens sobrevivem; degradam só as mensagens para `"Unknown partial failure"` / `"no detail"`.

Testes hoje verdes: `python -m pytest tests/unit/test_mutations_partial_failure.py -q` → 4 passed.

---

## Hipóteses investigadas e DESCARTADAS (não são achados)

- **`fake_detail._pb` desviado por auto-atributo do `MagicMock`.** Provei que `hasattr(mock, "_pb")` é sempre `True` e desviaria o `raw`, matando a injeção. Mas **os 6 sítios setam `_pb` explicitamente**. Descartado.
- **Builders de proto com `MagicMock`.** Todos os 21 `*_builder.py` usam `make_capture_client`; os 3 sem ele são guards, não builders. Descartado.
- **`fake_run_mutation(**kwargs)` (38 ocorrências).** O contrato é partido: a tool passa `payload`, e o conteúdo das ops é coberto pelos builder tests com `make_capture_client`. Descartado.
- **Guards de varredura sem piso de não-vacuidade.** `_guard_harness.py` levanta `EscopoVazioError` com zero arquivos; `test_rotas_de_mutacao_tem_guard.py` tem `examinadas &gt;= 19`; `test_builders_pedem_a_linha_sentinela.py` tem `_PISO_DE_FUNCOES`/`_PISO_DE_LIMITES`; `test_no_secrets_in_query_params.py` não tem piso explícito, mas `test_a_allowlist_descreve_a_realidade` funciona como piso de fato (varredura vazia → allowlist obsoleta → vermelho). Descartado.
- **Gates de acesso.** Asseridos por propriedade (predicado bem-formado, conjunção pura, JOIN puro) e respaldados por integração contra DB real. Descartado.
- **`fake_run_report(**kwargs)` em `test_get_change_history.py`.** São smoke de envelope; a discriminação por query está em `test_change_freshness.py`, que despacha por `query` e asserta "sonda foi emitida". Descartado.

---

## O que NÃO examinei

Li de fato **~20 dos 328** arquivos (4 integrais, 16 parciais), mais 6 de `src/`. Os 308 restantes passaram só pela varredura mecânica (AST de fakes cegos, grep de `Unpack`/`type_url`/`MagicMock`/`make_capture_client`/versões). Não cobri: `tests/web/` e testes de painel/HTMX/a11y além dos guards citados; os ~40 arquivos de repositório/migração; testes de Meta fora de paginação e insights; e não avaliei asserções tautológicas (item 3 da sua lista) de forma sistemática — só onde cruzei com elas. Um scan AST para "asserção cujo valor esperado é idêntico ao retorno do mock" é o próximo passo de maior rendimento e não foi feito.
