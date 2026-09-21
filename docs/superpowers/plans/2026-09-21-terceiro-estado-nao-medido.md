# O terceiro estado: "não medido" como valor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer seis superfícies distinguirem "medi e deu zero" de "não consegui medir", em vez de devolverem a segunda como se fosse a primeira.

**Architecture:** Um tipo novo (`LeituraDeFalhas`) substitui o `dict` que `erros_por_indice` devolvia, forçando via mypy strict que as três leitoras reconheçam a incerteza. Cada consumidor traduz isso para o vocabulário da sua superfície — `null` em resposta de tool, coluna nullable no `audit_log`, sentinela de fim no CSV. Um guard AST fecha a classe contra o próximo caso.

**Tech Stack:** Python 3.13 · mypy strict · pytest · asyncpg (raw SQL) · protobuf/`google-ads` 31.1.0 · FastAPI `StreamingResponse`

**Spec:** [`docs/superpowers/specs/2026-09-21-terceiro-estado-nao-medido-design.md`](../specs/2026-09-21-terceiro-estado-nao-medido-design.md)

## Global Constraints

- **Gate antes de cada commit:** `python scripts/check_pre_push.py` (~120s) tem de sair 6/6, EXIT=0. **Nunca** com pipe antes do `&&` — o exit code de um pipeline é o do último comando, e isso já deixou passar commit com gate vermelho. Rode mudo e leia `$?`.
- **Full sweep obrigatório** (`python scripts/check_pre_push_full.py`, Docker) nas Tasks 5 e 6 — há migration nova e query com cursor. Se o Docker não subir, diga isso no relatório e deixe o CI validar; **não** declare verde o que não rodou.
- **Guard verificado contra o código PRÉ-fix**, por sabotagem ou cópia — **nunca `git checkout`**, que descarta trabalho não commitado.
- **Não assertar superfície de API externa por analogia.** O comportamento do `Unpack` já foi sondado e está na §2 do spec; qualquer outra suposição sobre o proto exige probe.
- **Sem `datetime.now`/`date.today` em caminho de conta Google** — `hoje` vem de `await resolve_account_today(customer_id)` (F141, guard AST ativo).
- **Não montar envelope de mutate à mão** — use os helpers de `src/mcp/tools/_mutate_common.py`.
- Commits: `fix(scope): …` / `test(scope): …` / `feat(scope): …`. Scopes desta feature: `google_ads`, `web`, `db`, `mcp`. Trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **PT-BR** em docstrings e mensagens novas, seguindo o arquivo em que você mexe.

---

## Estrutura de arquivos

| arquivo | responsabilidade nesta feature |
|---|---|
| `src/google_ads/partial_failure.py` | **núcleo** — define `LeituraDeFalhas` e passa a ler o `bool` do `Unpack` |
| `src/google_ads/customer_match.py` | leitora 🔴 (PII) — `membros_recusados` vira `None` sob incerteza |
| `src/google_ads/mutations.py` | leitora 🟡 — mensagem por linha vira `None` em vez de `"Unknown partial failure"` |
| `src/google_ads/conversions.py` | leitora 🟡 — idem |
| `src/db/migrations/011_audit_log_had_effect.sql` | **criar** — coluna nullable `had_effect` |
| `src/db/repositories/audit_log.py` | `record()` aceita `had_effect`; `export_csv_rows()` ganha sentinela |
| `src/web/routes/_shared.py` | `_audit_admin()` repassa `had_effect` |
| `src/web/routes/admin_invites.py` | F179 — lê o `bool` de `delete_invite` |
| `src/web/routes/admin_audit.py` · `src/web/routes/audit.py` | as duas rotas de CSV ganham `try/except` |
| `src/google_ads/queries/audit_{zombie_keywords,quality_score,orphan_smart_actions}.py` | cada builder passa a devolver os filtros que aplicou |
| `src/mcp/tools/audit_{zombie_keywords,quality_score,orphan_smart_actions}.py` | `filters_applied` derivado do builder |
| `src/mcp/tools/get_ad_schedule.py` | `campanhas_com_grade_incerta` ganha o gêmeo do filtro `status` |
| `tests/unit/test_terceiro_estado_guard.py` | **criar** — o guard AST da classe |
| `tests/unit/test_mocks_de_unpack_sao_fieis.py` | **criar** — impede o mock voltar a devolver `None` |

---

## Correção ao spec, aplicada aqui

O spec §4.7 desenhou o guard varrendo `ast.Expr` cujo `.value` é `ast.Call`. **Medido depois de aprovado, isso pega 1 dos 3 alvos:**

```
Unpack:            1 chamada,  1 com retorno DESCARTADO
delete_invite:     1 chamada,  0 com retorno descartado   <-- perdido
erros_por_indice:  3 chamadas, 0 com retorno descartado
```

Duas causas, as duas reais:

1. `await managers_repo.delete_invite(...)` é `ast.Expr → ast.Await → ast.Call`. Sem desembrulhar o `Await`, o guard perde **todo `await` descartado** — num codebase async, quase todos.
2. **`erros_por_indice` nunca tem o retorno descartado.** Ele é sempre consumido; o defeito é que o valor consumido não consegue expressar incerteza. Guard de "retorno descartado" é vacuamente verde nele, e o mecanismo correto é o **mypy** (Task 2), não uma segunda asserção.

A Task 9 implementa o guard corrigido: desembrulha `Await`, acusa `Unpack` e `delete_invite`, e trata `erros_por_indice` **só** como controle anti-vacuidade — sem duplicar a invariante que o mypy já mantém.

---

## Task 1: Os mocks de `Unpack` ficam fiéis ao proto

**Por que primeiro:** o fake devolve `None`. Assim que a Task 2 ler o retorno, `None` é falsy e **todo teste de partial failure entra no ramo "não medi"** — vermelho sem que haja bug. Se estas duas coisas acontecerem juntas, o vermelho não distingue mock de defeito.

**Files:**
- Modify: `tests/integration/test_add_keywords.py:84`
- Modify: `tests/integration/test_add_negatives_from_search_terms.py:86`
- Modify: `tests/integration/test_apply_audience.py:81`
- Modify: `tests/integration/test_remove_audience.py:90`
- Modify: `tests/unit/test_mutations_partial_failure.py:87`
- Modify: `tests/unit/test_reporta_o_que_aconteceu.py:308,632`
- Create: `tests/unit/test_mocks_de_unpack_sao_fieis.py`

**Interfaces:**
- Consumes: nada.
- Produces: todo `fake_unpack` em `tests/` devolve `bool`. A Task 2 depende disso.

- [ ] **Step 1: Escreva o guard que exige fidelidade**

Crie `tests/unit/test_mocks_de_unpack_sao_fieis.py`:

```python
"""O fake de `Any.Unpack` tem de devolver `bool`, como o proto real devolve.

Sondado em 2026-09-21 contra o protobuf instalado:

    Unpack(tipo CERTO)  -> True
    Unpack(tipo ERRADO) -> False   (sem excecao, e o alvo fica intocado)

O fake antigo devolvia `None`. Enquanto a producao descartava o retorno isso
nao aparecia; no minuto em que ela passou a ler, `None` virou falsy e os
testes de partial failure teriam ficado vermelhos SEM bug nenhum — o modo
"o mock que bloqueia o conserto".

Este guard existe para que o fake nao volte a mentir sobre a forma do proto.
Teste que codifica a convencao errada e PIOR que teste ausente (F87, F89).
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _guard_harness as h  # noqa: E402

# Medido em 2026-09-21: 6 arquivos stubam `Unpack`. O piso vem da CONTAGEM,
# nunca de estimativa — um piso chutado ja disparou por engano neste repo.
PISO_DE_ARQUIVOS = 6


def _funcoes_fake_unpack() -> list[tuple[str, ast.FunctionDef]]:
    achados: list[tuple[str, ast.FunctionDef]] = []
    for arq in h.testes_py():
        arv = h.arvore(arq)
        for no in ast.walk(arv):
            if isinstance(no, ast.FunctionDef) and no.name == "fake_unpack":
                achados.append((h.rel(arq), no))
    return achados


def test_todo_fake_unpack_devolve_bool() -> None:
    achados = _funcoes_fake_unpack()
    arquivos = {nome for nome, _ in achados}
    if len(arquivos) < PISO_DE_ARQUIVOS:
        raise h.EscopoVazioError(
            f"esperava >= {PISO_DE_ARQUIVOS} arquivos com `fake_unpack`, "
            f"achei {len(arquivos)}: {sorted(arquivos)}. O fake foi renomeado "
            "ou removido — este guard parou de olhar para alguma coisa."
        )

    culpados = [
        f"{nome}:{fn.lineno}"
        for nome, fn in achados
        if not any(
            isinstance(no, ast.Return) and no.value is not None
            for no in ast.walk(fn)
        )
    ]
    assert not culpados, (
        "fake_unpack sem `return`: o proto real devolve bool, e um fake que "
        f"devolve None faz a producao ler falsy sem bug. Culpados: {culpados}"
    )
```

- [ ] **Step 2: Rode e veja FALHAR**

Run: `python -m pytest tests/unit/test_mocks_de_unpack_sao_fieis.py -v`
Expected: FAIL — `fake_unpack sem return`, listando os 6 arquivos (7 ocorrências: `test_reporta_o_que_aconteceu.py` tem duas).

- [ ] **Step 3: Torne os 7 fakes fiéis**

Em cada um dos 7 pontos, a função hoje é:

```python
        def fake_unpack(target_pb: MagicMock) -> None:
            target_pb.errors = fake_errors
```

Troque por:

```python
        def fake_unpack(target_pb: MagicMock) -> bool:
            target_pb.errors = fake_errors
            return True
```

A indentação varia por arquivo (algumas são aninhadas em `if`, outras no corpo da função de fixture) — preserve a do arquivo. Não mude mais nada: o `type_url` v20 fica como está (ver "Fora de escopo" no spec; uniformizar versão aqui tornaria o vermelho ambíguo).

- [ ] **Step 4: Rode o guard e a suíte**

Run: `python -m pytest tests/unit/test_mocks_de_unpack_sao_fieis.py -v`
Expected: PASS

Run: `python -m pytest tests/unit/test_mutations_partial_failure.py tests/unit/test_reporta_o_que_aconteceu.py -v`
Expected: PASS — nada muda de comportamento, porque a produção ainda descarta o retorno.

- [ ] **Step 5: Gate e commit**

```bash
python scripts/check_pre_push.py
```
Leia `$?`. Só commite com EXIT=0.

```bash
git add tests/
git commit -m "test(google_ads): fake de Unpack devolve bool, como o proto real"
```

---

## Task 2: `LeituraDeFalhas` — o tipo e o produtor

**Files:**
- Modify: `src/google_ads/partial_failure.py:60-103`
- Modify: `src/google_ads/mutations.py:76-87`
- Modify: `src/google_ads/conversions.py:290-293`
- Modify: `src/google_ads/customer_match.py:306-316`
- Test: `tests/unit/test_leitura_de_falhas.py` (criar)

**Interfaces:**
- Consumes: Task 1 (fakes devolvendo `bool`).
- Produces: `LeituraDeFalhas(erros: dict[int, ErroDeLinha], medido: bool)`, exportado de `src.google_ads.partial_failure`. `erros_por_indice(response, client, **contexto) -> LeituraDeFalhas`. As Tasks 3 e 4 leem `.medido`.

**Regra de conversão, para não inventar semântica:**

| situação | resultado |
|---|---|
| sem `partial_failure_error`, ou `code == 0` | `LeituraDeFalhas({}, medido=True)` — vazio **medido** |
| `code != 0` e ao menos um detail desempacotou | `medido=True` |
| `code != 0` e algum `Unpack` devolveu `False` | `medido=False` |
| `code != 0` e **nenhum** detail desempacotou | `medido=False` |
| o `except Exception` disparou | `medido=False` |

A quarta linha é a que se esquece: `code != 0` afirma que *houve* falha; sair dali com `erros={}` e `medido=True` seria o defeito original com roupa nova.

- [ ] **Step 1: Escreva os testes que falham**

Crie `tests/unit/test_leitura_de_falhas.py`:

```python
"""`erros_por_indice` sabe dizer que NAO conseguiu ler quem falhou."""

from typing import Any
from unittest.mock import MagicMock

from src.google_ads.partial_failure import LeituraDeFalhas, erros_por_indice


def _resposta(*, code: int, unpack_ok: bool, com_detail: bool = True) -> Any:
    resp = MagicMock()
    resp.partial_failure_error.code = code
    if not com_detail:
        resp.partial_failure_error.details = []
        return resp

    erro = MagicMock()
    erro.message = "invalid format"
    erro.error_code = "offline_user_data_job_error: invalid format"
    erro.location.field_path_elements = [MagicMock(index=2)]

    def fake_unpack(target_pb: MagicMock) -> bool:
        if not unpack_ok:
            return False
        target_pb.errors = [erro]
        return True

    raw = MagicMock()
    raw.type_url = "type.googleapis.com/google.ads.googleads.v24.errors.GoogleAdsFailure"
    raw.Unpack = fake_unpack
    detail = MagicMock()
    detail._pb = raw
    resp.partial_failure_error.details = [detail]
    return resp


def _cliente() -> Any:
    client = MagicMock()
    client.get_type.return_value._meta.pb.return_value = MagicMock(errors=[])
    return client


def test_unpack_recusado_nao_vira_lote_limpo() -> None:
    leitura = erros_por_indice(_resposta(code=1, unpack_ok=False), _cliente())
    assert isinstance(leitura, LeituraDeFalhas)
    assert leitura.medido is False, "Unpack False tem de virar 'nao medi', nao '{}' mudo"


def test_sem_falha_alguma_e_medido() -> None:
    """CONTROLE POSITIVO. Sem ele, uma implementacao que devolve medido=False
    sempre passaria no teste de cima — e o guard nao distinguiria codigo bom de
    quebrado, que e a definicao de nao-guard."""
    leitura = erros_por_indice(_resposta(code=0, unpack_ok=True), _cliente())
    assert leitura.medido is True
    assert leitura.erros == {}


def test_unpack_ok_le_os_erros_e_afirma_que_mediu() -> None:
    leitura = erros_por_indice(_resposta(code=1, unpack_ok=True), _cliente())
    assert leitura.medido is True
    assert leitura.erros[2].error_message == "invalid format"


def test_code_nao_zero_sem_detail_nenhum_nao_e_medido() -> None:
    """`code != 0` afirma que HOUVE falha. Sair dali com erros={} e medido=True
    seria o defeito original com roupa nova."""
    leitura = erros_por_indice(_resposta(code=1, unpack_ok=True, com_detail=False), _cliente())
    assert leitura.medido is False
    assert leitura.erros == {}
```

- [ ] **Step 2: Rode e veja FALHAR**

Run: `python -m pytest tests/unit/test_leitura_de_falhas.py -v`
Expected: FAIL com `ImportError: cannot import name 'LeituraDeFalhas'`.

- [ ] **Step 3: Implemente o tipo e o produtor**

Em `src/google_ads/partial_failure.py`, logo depois de `ErroDeLinha`:

```python
@dataclass(frozen=True, slots=True)
class LeituraDeFalhas:
    """O que se sabe sobre QUEM falhou num lote — e se da para saber.

    `medido=False` NAO e "nenhuma linha falhou": e "nao consegui ler quem
    falhou". Quem consome traduz isso para o vocabulario da sua superficie; o
    que nao pode e ler `erros` vazio como ausencia de falha.

    E um dataclass, nao `tuple[dict, bool]`, de proposito: tupla e
    desempacotavel por descuido, e `erros, _ = ...` passaria batido numa
    revisao. Sem `.items()`, os tres call-sites de hoje quebram no MYPY, que e
    onde se quer que quebrem.
    """

    erros: dict[int, ErroDeLinha]
    medido: bool
```

Troque o corpo de `erros_por_indice` (mantendo a assinatura de parâmetros) por:

```python
def erros_por_indice(
    response: Any,
    client: Any,
    **contexto: Any,
) -> LeituraDeFalhas:
    """Mapa `indice da operacao -> erro`, mais se a leitura foi CONFIAVEL.

    Antes devolvia `dict` cru, e `{}` significava duas coisas incompativeis:
    "nenhuma linha falhou" e "nao consegui ler". A justificativa escrita aqui
    para engolir a falha era que "quem chama ja tem a contagem de falhas por
    outra via" — verdade em `run_mutation` (le `WhichOneof`) e em
    `run_conversion_upload` (heuristica em `results`), e FALSA no Customer
    Match, cuja resposta so tem o `partial_failure_error`. A docstring do
    modulo ja dizia isso, dois paragrafos acima, sem que ninguem cruzasse os
    dois fatos.
    """
    erros: dict[int, ErroDeLinha] = {}
    pfe = getattr(response, "partial_failure_error", None)
    if pfe is None or getattr(pfe, "code", 0) == 0:
        return LeituraDeFalhas(erros, medido=True)

    medido = True
    desempacotou_algum = False
    try:
        for detail in getattr(pfe, "details", []) or []:
            # proto-plus embrulha; o `Any` cru mora em `_pb`.
            raw = detail._pb if hasattr(detail, "_pb") else detail
            # Duck-typing em vez de isinstance: a classe `google.protobuf.any_pb2.Any`
            # muda de caminho entre versoes do SDK.
            if not (hasattr(raw, "type_url") and hasattr(raw, "Unpack")):
                continue
            # `GoogleAdsFailure` e o unico detail que o Google manda aqui; o
            # type_url evita importar a classe versionada do proto.
            if "GoogleAdsFailure" not in raw.type_url:
                continue
            failure_pb = client.get_type("GoogleAdsFailure")._meta.pb()
            # O retorno do `Unpack` era DESCARTADO. Sondado em 21/09: ele
            # devolve bool, NAO levanta na divergencia, e compara pelo NOME
            # COMPLETO do tipo — entao um type_url de outra versao deixa
            # `failure_pb` zerado e o laco abaixo nao roda. O filtro acima e
            # agnostico de versao de proposito; o alvo aqui e versionado. A
            # defesa esta num lado e a sensibilidade no outro.
            if not raw.Unpack(failure_pb):
                medido = False
                log.warning(
                    "partial_failure_unpack_recusou",
                    type_url=str(raw.type_url),
                    **contexto,
                )
                continue
            desempacotou_algum = True
            for gae in failure_pb.errors:
                if not gae.location.field_path_elements:
                    continue
                idx = int(gae.location.field_path_elements[0].index)
                erros[idx] = ErroDeLinha(
                    error_code=_codigo(gae),
                    error_message=str(gae.message),
                )
    except Exception:
        log.exception("partial_failure_detail_unpack_failed", **contexto)
        medido = False

    # `code != 0` afirma que HOUVE falha. Chegar aqui sem ter desempacotado
    # nenhum detail significa que nao se sabe QUAIS — dizer "medi e nao achei"
    # seria o defeito original com roupa nova.
    if not desempacotou_algum:
        medido = False
    return LeituraDeFalhas(erros, medido=medido)
```

- [ ] **Step 4: Adapte os três call-sites (mecânico, sem mudar comportamento)**

O mypy vai acusar os três. Adapte cada um lendo `.erros` — **o comportamento honesto entra nas Tasks 3 e 4**, não aqui.

`src/google_ads/mutations.py`, no lugar do dict comprehension atual:

```python
    leitura = erros_por_indice(
        response,
        client,
        origem="run_mutation",
        operation=operation_type,
        customer_id=customer_id,
    )
    error_by_index = {idx: e.error_message for idx, e in leitura.erros.items()}
```

`src/google_ads/conversions.py`:

```python
    leitura = erros_por_indice(response, client, origem="run_conversion_upload")
    row_errors = {
        idx: {"error_code": e.error_code, "error_message": e.error_message}
        for idx, e in leitura.erros.items()
    }
```

`src/google_ads/customer_match.py`:

```python
            leitura = erros_por_indice(
                add_response,
                client,
                origem="run_offline_user_data_job",
                customer_id=customer_id,
            )
            progresso.membros_recusados = [
                {"index": idx, "error_code": e.error_code, "error_message": e.error_message}
                for idx, e in sorted(leitura.erros.items())
            ]
```

- [ ] **Step 5: Rode**

Run: `python -m pytest tests/unit/test_leitura_de_falhas.py -v`
Expected: PASS (4 testes)

Run: `python -m mypy src/`
Expected: sem erro — se sobrar algum call-site, o mypy o nomeia.

- [ ] **Step 6: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add src/google_ads/ tests/unit/test_leitura_de_falhas.py
git commit -m "fix(google_ads): erros_por_indice distingue 'zero falhas' de 'nao consegui ler'"
```

---

## Task 3: Customer Match para de reportar lote de PII como 100% aceito

**Por que esta é a grave:** `customer_match` é a **única** das três leitoras cuja detecção de falha depende inteiramente de `erros_por_indice` — o comentário do próprio código diz *"A resposta deste RPC nao tem lista por-op"*. E `submetidos()` calcula `member_count - len(membros_recusados)`: lista vazia por não-medição vira **o lote inteiro reportado como aceito**, numa tool que carrega PII hasheada.

**Files:**
- Modify: `src/google_ads/customer_match.py:86` (campo), `:129` (`submetidos`), `:306` (atribuição), `:400-401` (audit), `:441-447` (log), `:457-459` (retorno)
- Test: `tests/unit/test_customer_match_nao_afirma_lote_limpo.py` (criar)

**Interfaces:**
- Consumes: `LeituraDeFalhas` da Task 2.
- Produces: `_Progresso.membros_recusados: list[dict[str, Any]] | None`; `_Progresso.submetidos(member_count: int) -> int | None`. A chave `failures` da resposta passa a ser `list | None`.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_customer_match_nao_afirma_lote_limpo.py`:

```python
"""Sob leitura nao-medida, o Customer Match diz que nao sabe — nao que deu tudo certo."""

from src.google_ads.customer_match import _Progresso


def test_sem_medicao_os_tres_campos_dizem_desconhecido_juntos() -> None:
    """`null` ao lado de `0` le como zero. Tres campos que descrevem a mesma
    coisa desconhecida tem que dizer desconhecido JUNTOS — e a regra que o
    `get_ad_schedule` ja aplica no bloco do F147."""
    p = _Progresso(create_id="a", add_id="b", membros_recusados=None)
    assert p.submetidos(500) is None, "lote de 500 sem medicao nao e '500 aceitos'"


def test_com_medicao_o_calculo_continua_o_mesmo() -> None:
    """CONTROLE POSITIVO: sem ele, uma implementacao que devolve None sempre
    passaria no teste de cima."""
    p = _Progresso(create_id="a", add_id="b", membros_recusados=[{"index": 1}])
    assert p.submetidos(500) == 499


def test_parada_antes_do_passo_2_continua_zero() -> None:
    """`pii_anexada` False vence: nao houve resposta do add, entao nao ha o que
    medir E nada saiu. Zero e a verdade aqui, nao 'desconhecido'."""
    p = _Progresso(create_id="a", membros_recusados=None)
    assert p.submetidos(500) == 0
```

- [ ] **Step 2: Rode e veja FALHAR**

Run: `python -m pytest tests/unit/test_customer_match_nao_afirma_lote_limpo.py -v`
Expected: FAIL no primeiro teste — `submetidos` devolve `500` (porque `len(None)` levanta `TypeError`, ou devolve o lote se o campo ainda for `[]`).

- [ ] **Step 3: Torne o campo anulável**

`src/google_ads/customer_match.py`, na declaração de `_Progresso` (linha ~86):

```python
    # `None` = a leitura do `partial_failure_error` nao foi confiavel (ver
    # `LeituraDeFalhas.medido`). Lista vazia continua significando "medi e o
    # Google nao recusou ninguem" — sao coisas diferentes, e antes as duas
    # eram `[]`.
    membros_recusados: list[dict[str, Any]] | None = field(default_factory=list)
```

E `submetidos`:

```python
    def submetidos(self, member_count: int) -> int | None:
        if not self.pii_anexada:
            return 0
        if self.membros_recusados is None:
            return None
        return member_count - len(self.membros_recusados)
```

Mantenha a docstring existente e **acrescente** ao fim dela:

```
        `None` quando a leitura das recusas nao foi confiavel: subtrair de uma
        lista que nao se conseguiu ler devolveria o lote INTEIRO como aceito,
        que e a afirmacao mais cara desta tool.
```

- [ ] **Step 4: Faça a atribuição respeitar `medido`**

No lugar do bloco da Task 2:

```python
            # Tres campos que descrevem a mesma coisa desconhecida dizem
            # desconhecido juntos: `membros_recusados=None` propaga para
            # `members_failed` e `members_submitted` mais abaixo.
            progresso.membros_recusados = (
                [
                    {"index": idx, "error_code": e.error_code, "error_message": e.error_message}
                    for idx, e in sorted(leitura.erros.items())
                ]
                if leitura.medido
                else None
            )
```

- [ ] **Step 5: Propague nos quatro pontos de leitura**

Defina este helper em **nível de módulo**, logo depois da classe `_Progresso`
(não dentro da função — ele é chamado de três escopos diferentes):

```python
def _quantos(recusados: list[dict[str, Any]] | None) -> int | None:
    """`len`, ou `None` quando a leitura nao foi confiavel."""
    return None if recusados is None else len(recusados)
```

Troque as quatro ocorrências de `len(progresso.membros_recusados)` por
`_quantos(progresso.membros_recusados)`:

- no `params_summary` do audit (`"members_failed"`),
- no `log.info("run_offline_user_data_job_done", ...)` (`members_failed=`),
- no dict de retorno (`"members_failed"`).

O quarto ponto é o `"failures": progresso.membros_recusados`, que já propaga `None` sozinho — não mude.

- [ ] **Step 6: Rode**

Run: `python -m pytest tests/unit/test_customer_match_nao_afirma_lote_limpo.py -v`
Expected: PASS (3 testes)

Run: `python -m mypy src/google_ads/customer_match.py`
Expected: sem erro.

- [ ] **Step 7: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add src/google_ads/customer_match.py tests/unit/test_customer_match_nao_afirma_lote_limpo.py
git commit -m "fix(google_ads): lote de PII nao medido para de ser reportado como 100% aceito"
```

---

## Task 4: `mutations` e `conversions` param de inventar o motivo

**Por que juntas:** as duas têm exatamente a mesma forma — a **contagem** de falhas sobrevive por outro caminho (`WhichOneof` numa, heurística em `results` na outra), e o que degrada é a **mensagem**. Hoje as duas escrevem uma string que afirma ter lido o motivo: `"Unknown partial failure"` e `"no detail"`. Um reviewer não rejeitaria uma sem rejeitar a outra.

**Files:**
- Modify: `src/google_ads/mutations.py:93-104`
- Modify: `src/google_ads/conversions.py:295-308`
- Test: `tests/unit/test_motivo_nao_lido_nao_vira_motivo.py` (criar)

**Interfaces:**
- Consumes: `LeituraDeFalhas` da Task 2.
- Produces: em `_parse_partial_failures`, a chave `error` de uma linha falha vira `None` quando `leitura.medido` é `False`. `_parse_upload_response` idem, em `error_code`/`error_message`.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_motivo_nao_lido_nao_vira_motivo.py`:

```python
"""Nao ler o motivo e diferente de o motivo ser desconhecido."""

from typing import Any
from unittest.mock import MagicMock

from src.google_ads.mutations import _parse_partial_failures


def _resposta_com_uma_falha() -> Any:
    ok = MagicMock()
    ok._pb.WhichOneof.return_value = "ad_group_criterion_result"
    falhou = MagicMock()
    falhou._pb.WhichOneof.return_value = None

    resp = MagicMock()
    resp.mutate_operation_responses = [ok, falhou]
    resp.partial_failure_error.code = 1
    # Nenhum detail desempacotavel -> LeituraDeFalhas.medido = False
    resp.partial_failure_error.details = []
    return resp


def test_sem_medicao_o_erro_da_linha_e_none() -> None:
    linhas = _parse_partial_failures(
        _resposta_com_uma_falha(),
        MagicMock(),
        operation_type="add_keywords",
        customer_id="1234567890",
        target_count=2,
    )
    falha = [linha for linha in linhas if linha["status"] == "failed"]
    assert len(falha) == 1, "a CONTAGEM sobrevive: ela vem do WhichOneof, nao do mapa de erros"
    assert falha[0]["error"] is None, (
        "'Unknown partial failure' afirma que se leu o motivo e ele era desconhecido; "
        "a verdade e que nao se leu"
    )
```

> **Nota ao implementador:** confira a assinatura real de `_parse_partial_failures` em `src/google_ads/mutations.py:44` antes de escrever a chamada do teste — os nomes dos parâmetros acima vêm da leitura de 21/09 (`operation_type`, `customer_id`, `target_count`), e se divergirem, o teste é que se adapta, não a produção.

- [ ] **Step 2: Rode e veja FALHAR**

Run: `python -m pytest tests/unit/test_motivo_nao_lido_nao_vira_motivo.py -v`
Expected: FAIL — `error` vem `'Unknown partial failure'`.

- [ ] **Step 3: `mutations.py` — o motivo ausente vira `None`**

No laço de classificação, troque o ramo de falha por:

```python
        else:
            per_op_results.append(
                {
                    "index": idx,
                    "status": "failed",
                    # `None` quando a leitura nao foi confiavel: a linha FALHOU
                    # (o `WhichOneof` diz isso, e essa contagem e medida), mas o
                    # motivo nao foi lido. A string antiga afirmava o contrario.
                    "error": error_by_index.get(idx)
                    if leitura.medido
                    else None,
                }
            )
```

E, quando `leitura.medido` é `True` e o índice não está no mapa, preserve o texto antigo:

```python
                    "error": (
                        error_by_index.get(idx, "Unknown partial failure")
                        if leitura.medido
                        else None
                    ),
```

Use **esta segunda forma** — ela mantém o comportamento de hoje no caminho medido e só muda o não-medido.

- [ ] **Step 4: `conversions.py` — idem**

Troque o `err` do laço:

```python
    for idx, result in enumerate(response.results):
        if not getattr(result, "conversion_action", None):
            # Sob leitura nao-confiavel o motivo e `None`, nao "no detail": a
            # linha falhou (a heuristica do `conversion_action` vazio diz isso),
            # mas o porque nao foi lido.
            padrao: dict[str, Any] = (
                {"error_code": "UNKNOWN", "error_message": "no detail"}
                if leitura.medido
                else {"error_code": None, "error_message": None}
            )
            err = row_errors.get(idx, padrao)
```

- [ ] **Step 5: Rode**

Run: `python -m pytest tests/unit/test_motivo_nao_lido_nao_vira_motivo.py tests/unit/test_mutations_partial_failure.py -v`
Expected: PASS

- [ ] **Step 6: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add src/google_ads/mutations.py src/google_ads/conversions.py tests/unit/test_motivo_nao_lido_nao_vira_motivo.py
git commit -m "fix(google_ads): motivo nao lido vira None em vez de 'Unknown partial failure'"
```

---

## Task 5: F179 — o audit para de afirmar cancelamento que não houve

**Files:**
- Create: `src/db/migrations/011_audit_log_had_effect.sql`
- Modify: `src/db/repositories/audit_log.py:27-43` (`record`)
- Modify: `src/web/routes/_shared.py:85-111` (`_audit_admin`)
- Modify: `src/web/routes/admin_invites.py:112-118`
- Test: `tests/unit/test_f179_audit_so_afirma_o_que_ocorreu.py` (criar)

**Interfaces:**
- Consumes: nada das tasks anteriores.
- Produces: coluna `audit_log.had_effect boolean` (nullable); `audit_log.record(..., had_effect: bool | None = None)`; `_audit_admin(..., had_effect: bool | None = None)`.

- [ ] **Step 1: Escreva a migration**

Crie `src/db/migrations/011_audit_log_had_effect.sql`:

```sql
-- 011_audit_log_had_effect.sql — F179.
-- `admin_invites_cancel` descartava o retorno de `delete_invite` (que e `bool`
-- e existe exatamente para isto) e chamava `_audit_admin` INCONDICIONALMENTE.
-- Convidado que loga entre o SELECT e o DELETE vira `status='active'`, o DELETE
-- nao afeta linha nenhuma, e o audit afirma que um admin cancelou um convite
-- que virou conta ativa.
--
-- A transacao do F174 tornou o par escrita+audit ATOMICO, nao VERDADEIRO: os
-- dois commitam juntos mesmo quando a escrita nao teve efeito.
--
-- Coluna NOVA e NULLABLE, moldada na 007 (F148, `dry_run`): NULL nao afirma
-- nada sobre as linhas anteriores ao fix. NAO virou valor novo em `status`
-- (success|error|denied) porque aquele enum e filtro publico de
-- `get_my_audit_log` e mexer nele quebraria consumidor — mesma razao escrita
-- na 007.
--
-- Safe DDL: ADD COLUMN nullable sem default nao reescreve a tabela.

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS had_effect boolean;

COMMENT ON COLUMN audit_log.had_effect IS
  'true = a escrita afetou linha; false = passou sem efeito; NULL = nao medido ou anterior ao fix (F179).';
```

- [ ] **Step 2: Escreva o teste que falha**

Crie `tests/unit/test_f179_audit_so_afirma_o_que_ocorreu.py`:

```python
"""O audit de cancelamento de convite diz se o DELETE teve efeito."""

import inspect

from src.db.repositories import audit_log
from src.web.routes import _shared


def test_record_aceita_had_effect() -> None:
    assert "had_effect" in inspect.signature(audit_log.record).parameters


def test_audit_admin_repassa_had_effect() -> None:
    assert "had_effect" in inspect.signature(_shared._audit_admin).parameters


def test_a_rota_le_o_retorno_do_delete_invite() -> None:
    """Guard de forma: o retorno de `delete_invite` nao pode ser descartado.

    Vive aqui, perto do fix, alem de no guard estrutural da Task 9 — este
    afirma a ROTA especifica, aquele afirma a CLASSE. Se um dia divergirem, e
    o estrutural que manda.
    """
    import ast
    from pathlib import Path

    fonte = Path(_shared.__file__).parent / "admin_invites.py"
    arv = ast.parse(fonte.read_text(encoding="utf-8"))
    descartados = [
        no.lineno
        for no in ast.walk(arv)
        if isinstance(no, ast.Expr)
        and isinstance(v := (no.value.value if isinstance(no.value, ast.Await) else no.value), ast.Call)
        and isinstance(v.func, ast.Attribute)
        and v.func.attr == "delete_invite"
    ]
    assert not descartados, (
        f"delete_invite com retorno descartado em admin_invites.py:{descartados}. "
        "Ele devolve bool justamente para dizer se deletou."
    )


def test_o_false_chega_ao_audit_e_ao_admin() -> None:
    """Assinatura certa nao prova fiacao: os tres testes acima passariam com a
    rota ignorando `cancelou`. Este le a rota e exige que o bool VIAJE."""
    import ast
    from pathlib import Path

    fonte = Path(_shared.__file__).parent / "admin_invites.py"
    arv = ast.parse(fonte.read_text(encoding="utf-8"))

    nomes_ligados = {
        alvo.id
        for no in ast.walk(arv)
        if isinstance(no, ast.Assign)
        and isinstance(
            v := (no.value.value if isinstance(no.value, ast.Await) else no.value), ast.Call
        )
        and isinstance(v.func, ast.Attribute)
        and v.func.attr == "delete_invite"
        for alvo in no.targets
        if isinstance(alvo, ast.Name)
    }
    assert nomes_ligados, "o retorno de delete_invite nao foi ligado a nome nenhum"

    kwargs_had_effect = [
        kw.value
        for no in ast.walk(arv)
        if isinstance(no, ast.Call)
        for kw in no.keywords
        if kw.arg == "had_effect"
    ]
    assert any(
        isinstance(v, ast.Name) and v.id in nomes_ligados for v in kwargs_had_effect
    ), "had_effect nao recebe o retorno de delete_invite — o audit voltou a afirmar sem medir"

    usado_em_condicao = any(
        isinstance(no, ast.If)
        and any(isinstance(x, ast.Name) and x.id in nomes_ligados for x in ast.walk(no.test))
        for no in ast.walk(arv)
    )
    assert usado_em_condicao, "nada avisa o admin quando o cancelamento nao teve efeito"
```

- [ ] **Step 3: Rode e veja FALHAR**

Run: `python -m pytest tests/unit/test_f179_audit_so_afirma_o_que_ocorreu.py -v`
Expected: FAIL nos três — parâmetro ausente e retorno descartado na linha 113.

- [ ] **Step 4: `record` e `_audit_admin` aceitam o campo**

Em `src/db/repositories/audit_log.py`, acrescente ao final dos kwargs de `record`:

```python
    had_effect: bool | None = None,
```

Acrescente à docstring:

```
    had_effect: true = a escrita afetou linha; false = passou sem efeito; None
        nos caminhos que nao medem. Nullable pelo mesmo motivo do `dry_run`
        (F148): NULL nao afirma nada sobre as linhas anteriores ao fix.
```

E inclua a coluna no `INSERT` existente — acrescente `had_effect` à lista de colunas e o parâmetro correspondente ao final dos valores, **preservando a numeração posicional do asyncpg** (`$N`). Leia o `INSERT` inteiro antes de editar: errar a ordem dos `$N` é o tipo de defeito que só o teste de integração pega.

Em `src/web/routes/_shared.py`, `_audit_admin` ganha o mesmo parâmetro e o repassa:

```python
async def _audit_admin(
    conn: Any,
    *,
    admin: CurrentUser,
    operation: str,
    customer_id: str | None = None,
    platform: Literal["google", "meta"] = "google",
    had_effect: bool | None = None,
    **summary: Any,
) -> None:
```

```python
        platform=platform,
        had_effect=had_effect,
    )
```

- [ ] **Step 5: A rota lê o retorno e avisa o admin**

Em `src/web/routes/admin_invites.py`, troque o bloco da transação:

```python
        async with conn.transaction():
            # F179: o retorno e `bool` e existe para isto. Descartado, o audit
            # afirmava um cancelamento que podia nao ter ocorrido — convidado
            # que loga entre o SELECT e o DELETE ja nao tem status='invited'.
            cancelou = await managers_repo.delete_invite(conn, manager_id=parsed_invite_id)
            await _audit_admin(
                conn,
                admin=user,
                operation="admin_invite_cancel",
                email=email,
                had_effect=cancelou,
            )
```

E logo depois da transação, antes do retorno HTMX, avise o admin quando não houve efeito:

```python
    if not cancelou:
        # A trilha ja registrou `had_effect=false`; isto e a outra ponta, a que
        # o humano le. Checar ANTES do DELETE nao e possivel: o caso so se
        # revela no resultado dele.
        _flash(request, "Esse convite já foi aceito — nada foi cancelado.")
```

> **Nota ao implementador:** o helper de flash message deste repo está em `src/web/routes/_shared.py`. Leia-o e use o nome e a assinatura reais — `_flash` acima é o nome esperado, não uma suposição a manter se o arquivo disser outro.

- [ ] **Step 6: Rode, incluindo o full sweep**

Run: `python -m pytest tests/unit/test_f179_audit_so_afirma_o_que_ocorreu.py -v`
Expected: PASS (3 testes)

Run: `python scripts/check_pre_push_full.py`
Expected: verde. **Há migration nova e um `INSERT` alterado** — é exatamente o caso que o gate rápido não cobre. Se o Docker não subir, diga isso no relatório e deixe o CI validar; não declare verde o que não rodou.

- [ ] **Step 7: Commit**

```bash
git add src/db/ src/web/routes/ tests/unit/test_f179_audit_so_afirma_o_que_ocorreu.py
git commit -m "fix(web): F179 — audit de cancelamento registra se o DELETE teve efeito"
```

---

## Task 6: O CSV do audit prova que terminou

**Files:**
- Modify: `src/db/repositories/audit_log.py:121-197` (`export_csv_rows`)
- Modify: `src/web/routes/admin_audit.py:123-135`
- Modify: `src/web/routes/audit.py:117-129`
- Test: `tests/unit/test_export_csv_prova_completude.py` (criar)

**Interfaces:**
- Consumes: nada das tasks anteriores.
- Produces: `export_csv_rows` emite, como última linha, `# v4-ads-mcp: export completo, N linhas` no caminho feliz, ou `# v4-ads-mcp: EXPORT INCOMPLETO apos N linhas — <motivo>` sob exceção.

**A escolha, escrita:** o cliente não pode ser avisado depois do `200 OK` que o `StreamingResponse` já enviou. Então a completude tem de ser **provável pelo arquivo**. A ausência da sentinela — exceção, queda de conexão, processo morto — lê como incompleto: fail-closed por construção. Bufferizar o export inteiro para poder falhar antes do `200` foi considerado e **recusado**: o `audit_log` é a tabela que mais cresce, e o cursor server-side existe para não carregá-la na memória.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_export_csv_prova_completude.py`:

```python
"""Um CSV truncado nao pode ser indistinguivel de um CSV curto."""

from typing import Any, AsyncIterator

import pytest

from src.db.repositories import audit_log

MARCA_OK = "# v4-ads-mcp: export completo"
MARCA_RUIM = "# v4-ads-mcp: EXPORT INCOMPLETO"


class _CursorQueExplode:
    def __init__(self, ate: int) -> None:
        self.ate = ate

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._gerar()

    async def _gerar(self) -> AsyncIterator[Any]:
        for i in range(self.ate):
            yield {
                "occurred_at": None, "email": f"a{i}@v4company.com", "operation": "op",
                "customer_id": "1", "action_type": "read", "status": "success",
                "target_count": None, "duration_ms": None,
                "error_message": None, "provider_request_id": None,
            }
        raise ConnectionError("conexao caiu no meio do cursor")


class _ConnFake:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def cursor(self, *_a: Any, **_k: Any) -> Any:
        return self._cursor

    def transaction(self) -> Any:
        class _T:
            async def __aenter__(self_) -> None: return None
            async def __aexit__(self_, *a: Any) -> bool: return False
        return _T()


@pytest.mark.asyncio
async def test_falha_no_meio_marca_o_arquivo() -> None:
    conn = _ConnFake(_CursorQueExplode(ate=3))
    linhas = [linha async for linha in audit_log.export_csv_rows(conn, days=7)]
    texto = "".join(linhas)
    assert MARCA_RUIM in texto, (
        "CSV cortado no meio e sintaticamente valido: sem marca, e "
        "indistinguivel de um export que achou poucas linhas"
    )
    assert MARCA_OK not in texto


@pytest.mark.asyncio
async def test_caminho_feliz_marca_completude() -> None:
    """CONTROLE POSITIVO. Sem ele, uma implementacao que NUNCA emite a marca de
    sucesso passa no teste de cima — e ai a ausencia da marca deixa de
    significar "incompleto", porque ela nunca esta la."""

    class _CursorOk:
        def __aiter__(self) -> AsyncIterator[Any]:
            return self._gerar()

        async def _gerar(self) -> AsyncIterator[Any]:
            for i in range(2):
                yield {
                    "occurred_at": None,
                    "email": f"a{i}@v4company.com",
                    "operation": "op",
                    "customer_id": "1",
                    "action_type": "read",
                    "status": "success",
                    "target_count": None,
                    "duration_ms": None,
                    "error_message": None,
                    "provider_request_id": None,
                }

    conn = _ConnFake(_CursorOk())
    texto = "".join([linha async for linha in audit_log.export_csv_rows(conn, days=7)])
    assert f"{MARCA_OK}, 2 linhas" in texto
    assert MARCA_RUIM not in texto
```

> **Nota ao implementador:** este teste usa um `conn` falso porque o caminho real exige Postgres. O teste de integração que exercita o cursor de verdade já existe na suíte — rode-o também (Step 5) e não o substitua por este.

- [ ] **Step 2: Rode e veja FALHAR**

Run: `python -m pytest tests/unit/test_export_csv_prova_completude.py -v`
Expected: FAIL — a exceção propaga e nenhuma marca é emitida.

- [ ] **Step 3: A sentinela em `export_csv_rows`**

Envolva o laço do cursor. O `yield` do header e a montagem das linhas não mudam:

```python
    lidas = 0
    try:
        # asyncpg server-side cursors MUST run inside an explicit transaction.
        async with conn.transaction():
            async for row in conn.cursor(sql, *params):
                buf = io.StringIO()
                csv.writer(buf).writerow([...])   # corpo existente, inalterado
                lidas += 1
                yield buf.getvalue()
    except Exception as e:
        # O `200 OK` e o `Content-Disposition` ja foram enviados quando a
        # primeira linha saiu — nao ha status a corrigir. A unica honestidade
        # possivel e MARCAR o arquivo, e e por isso que a marca de sucesso
        # tambem existe: a AUSENCIA dela e o sinal.
        buf = io.StringIO()
        csv.writer(buf).writerow([f"# v4-ads-mcp: EXPORT INCOMPLETO apos {lidas} linhas — {e}"])
        yield buf.getvalue()
        raise
    buf = io.StringIO()
    csv.writer(buf).writerow([f"# v4-ads-mcp: export completo, {lidas} linhas"])
    yield buf.getvalue()
```

O `raise` depois do `yield` preserva o log e o traceback do lado do servidor — a marca é para o humano que abre o arquivo, não em lugar do erro.

**Sobre o `#`:** CSV não tem comentário. A sentinela é uma linha CSV de **uma coluna só**, bem-formada, cujo primeiro campo começa com `#`. Planilha abre sem erro e a linha fica visível — que é a intenção.

- [ ] **Step 4: As duas rotas não engolem a exceção**

Nem `admin_audit.py` nem `audit.py` precisam de `try/except` próprio: a sentinela é emitida pelo gerador, que as duas consomem. **Verifique** que nenhuma das duas envolve o `async for` em `try`/`except` que engula — hoje não envolvem. Se a leitura mostrar que envolvem, remova o engolimento e diga isso no relatório.

Acrescente, no docstring de cada rota, a linha:

```
    O arquivo termina com uma linha-sentinela; a AUSENCIA dela significa
    export incompleto (o 200 ja foi enviado quando a primeira linha saiu).
```

- [ ] **Step 5: Rode, incluindo o full sweep**

Run: `python -m pytest tests/unit/test_export_csv_prova_completude.py -v`
Expected: PASS

Run: `python -m pytest tests/ -k "export_csv or audit_export" -v`
Expected: PASS — os testes existentes que leem o CSV agora veem uma linha a mais. **Se algum quebrar por contar linhas, ele é que se ajusta**, e o ajuste vai no relatório.

Run: `python scripts/check_pre_push_full.py`
Expected: verde (query com cursor).

- [ ] **Step 6: Commit**

```bash
git add src/db/repositories/audit_log.py src/web/routes/ tests/unit/test_export_csv_prova_completude.py
git commit -m "fix(db): export CSV do audit marca completude em vez de falhar aberto"
```

---

## Task 7: `filters_applied` passa a ser derivado da query

**Files:**
- Modify: `src/google_ads/queries/audit_zombie_keywords.py:17-55`
- Modify: `src/google_ads/queries/audit_quality_score.py:9-45`
- Modify: `src/google_ads/queries/audit_orphan_smart_actions.py:17-48`
- Modify: `src/mcp/tools/audit_zombie_keywords.py:101-136`
- Modify: `src/mcp/tools/audit_quality_score.py:~150-156`
- Modify: `src/mcp/tools/audit_orphan_smart_actions.py:~152-158`
- Test: `tests/unit/test_filters_applied_e_derivado.py` (criar)

**Interfaces:**
- Consumes: nada das tasks anteriores.
- Produces: cada builder passa a devolver `tuple[str, dict[str, Any]]` — `(gaql, filtros_aplicados)`. Os três tools montam `filters_applied` a partir do segundo elemento, mesclado com os filtros client-side que eles mesmos aplicam.

**Medido em 21/09 — 7 declarados, 5 escondidos:**

| tool | declara | corta e **não** declara |
|---|---|---|
| `audit_zombie_keywords` | `ad_group_ids`, `limit` | `ad_group_criterion.status='ENABLED'`, `ad_group_criterion.negative=FALSE` |
| `audit_quality_score` | `ad_group_ids`, `min_impressions`, `limit` | `ad_group_criterion.status='ENABLED'`, `quality_info.quality_score IS NOT NULL` |
| `audit_orphan_smart_actions` | `category`, `limit` | `conversion_action.status='ENABLED'` |

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_filters_applied_e_derivado.py`:

```python
"""Nomear ALGUNS filtros faz a lista ler como A lista."""

from src.google_ads.queries.audit_orphan_smart_actions import (
    build_audit_orphan_smart_actions_query,
)
from src.google_ads.queries.audit_quality_score import build_audit_quality_score_query
from src.google_ads.queries.audit_zombie_keywords import build_audit_zombie_keywords_query


def test_zombie_declara_os_cortes_server_side() -> None:
    _gaql, filtros = build_audit_zombie_keywords_query(
        start_date="2026-09-01", end_date="2026-09-30", ad_group_ids=None
    )
    assert filtros["criterion_status"] == "ENABLED"
    assert filtros["negative"] is False


def test_quality_score_declara_o_corte_de_qs_nulo() -> None:
    _gaql, filtros = build_audit_quality_score_query(
        start_date="2026-09-01", end_date="2026-09-30"
    )
    assert filtros["criterion_status"] == "ENABLED"
    assert filtros["quality_score_nao_nulo"] is True


def test_orphan_declara_o_corte_de_status() -> None:
    _gaql, filtros = build_audit_orphan_smart_actions_query(
        start_date="2026-09-01", end_date="2026-09-30", category=None
    )
    assert filtros["conversion_action_status"] == "ENABLED"


# Mapa campo-do-WHERE -> chave em `filters_applied`. Existe para que um filtro
# NOVO numa query QUEBRE este teste: campo fora do mapa falha com instrucao, nao
# com silencio. Asserir chaves nomeadas uma a uma nao faria isso — passaria
# feliz com um sexto filtro escondido, que e o defeito de origem.
CAMPO_PARA_CHAVE = {
    "ad_group_criterion.status": "criterion_status",
    "ad_group_criterion.negative": "negative",
    "ad_group.id": "ad_group_ids",
    "segments.date": "date_range",
    "ad_group_criterion.quality_info.quality_score": "quality_score_nao_nulo",
    "conversion_action.status": "conversion_action_status",
    "conversion_action.category": "category",
}


def _campos_do_where(gaql: str) -> set[str]:
    import re

    where = gaql.split("WHERE", 1)[1]
    return set(re.findall(r"([a-z_]+(?:\.[a-z_]+)+)\s*(?:=|!=|IN|BETWEEN|IS)", where))


def test_todo_campo_cortado_aparece_em_filters_applied() -> None:
    """A assercao DERIVADA: nao confere uma lista, confere a propriedade."""
    construidos = [
        build_audit_zombie_keywords_query(
            start_date="2026-09-01", end_date="2026-09-30", ad_group_ids=["1"]
        ),
        build_audit_quality_score_query(
            start_date="2026-09-01", end_date="2026-09-30", ad_group_ids=["1"]
        ),
        build_audit_orphan_smart_actions_query(
            start_date="2026-09-01", end_date="2026-09-30", category="PURCHASE"
        ),
    ]
    assert len(construidos) == 3, "piso: as tres tools que publicam filters_applied"
    for gaql, filtros in construidos:
        campos = _campos_do_where(gaql)
        assert campos, f"nenhum campo lido do WHERE — o parser quebrou:\n{gaql}"
        for campo in campos:
            chave = CAMPO_PARA_CHAVE.get(campo)
            assert chave is not None, (
                f"`{campo}` corta no WHERE e este teste nao o conhece. Filtro novo: "
                "decida a chave em `filters_applied`, declare-a no builder, e "
                "acrescente o mapeamento aqui."
            )
            assert chave in filtros, f"`{campo}` corta e nao aparece em filters_applied"
```

- [ ] **Step 2: Rode e veja FALHAR**

Run: `python -m pytest tests/unit/test_filters_applied_e_derivado.py -v`
Expected: FAIL — os builders devolvem `str`, não tupla.

- [ ] **Step 3: Cada builder devolve o que aplicou**

`audit_zombie_keywords.py` — troque o tipo de retorno e o `return`:

```python
def build_audit_zombie_keywords_query(
    *,
    start_date: str,
    end_date: str,
    ad_group_ids: list[str] | None,
) -> tuple[str, dict[str, Any]]:
    """GAQL pra keyword_view, MAIS os filtros que ela aplica.

    A tupla existe porque `filters_applied` era escrito a mao ao lado da
    chamada e divergiu: declarava 2 filtros e a query cortava 4. Derivar fecha
    a classe — filtro novo aqui aparece na resposta sem ninguem lembrar.
    """
```

No fim da função, no lugar do `return f"""..."""`:

```python
    gaql = f"""
        SELECT
          ...
    """.strip()
    filtros: dict[str, Any] = {
        "ad_group_ids": ad_group_ids,
        "criterion_status": "ENABLED",
        "negative": False,
        "date_range": {"start": start_date, "end": end_date},
    }
    return gaql, filtros
```

Faça o equivalente nos outros dois:

```python
    # audit_quality_score.py
    filtros: dict[str, Any] = {
        "ad_group_ids": ad_group_ids,
        "criterion_status": "ENABLED",
        "quality_score_nao_nulo": True,
        "date_range": {"start": start_date, "end": end_date},
    }
    return query, filtros
```

```python
    # audit_orphan_smart_actions.py
    filtros: dict[str, Any] = {
        "category": category,
        "conversion_action_status": "ENABLED",
        "date_range": {"start": start_date, "end": end_date},
    }
    return gaql, filtros
```

Acrescente `from typing import Any` onde faltar.

- [ ] **Step 4: Os três tools consomem a tupla**

Em `src/mcp/tools/audit_zombie_keywords.py`:

```python
    query, filtros_da_query = build_audit_zombie_keywords_query(
        start_date=start_date,
        end_date=end_date,
        ad_group_ids=ad_group_ids,
    )
```

E o bloco de resposta:

```python
        "filters_applied": {
            **filtros_da_query,
            # Aplicados AQUI, depois da query: o `limit` corta o resultado e a
            # definicao de zumbi e um filtro client-side em `flag_zombie_keywords`.
            "limit": limit,
            "definicao_de_zumbi": "impressions == 0 AND clicks == 0",
        },
```

Em `audit_quality_score.py` e `audit_orphan_smart_actions.py`, o mesmo padrão: espalhe `**filtros_da_query` e acrescente os client-side daquela tool (`limit` nas duas, `min_impressions` na de quality score se ele for aplicado depois da query — **leia o código antes** para saber se `min_impressions` é server-side ou client-side, e declare-o no lugar certo).

- [ ] **Step 5: Rode**

Run: `python -m pytest tests/unit/test_filters_applied_e_derivado.py -v`
Expected: PASS (3 testes)

Run: `python -m pytest tests/ -k "zombie or quality_score or orphan" -v`
Expected: PASS — testes que assertam `filters_applied` vão ver chaves novas. **Se algum quebrar por igualdade exata de dict, ele é que se ajusta.**

- [ ] **Step 6: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add src/google_ads/queries/ src/mcp/tools/ tests/unit/test_filters_applied_e_derivado.py
git commit -m "fix(mcp): filters_applied derivado da query em vez de escrito a mao"
```

---

## Task 8: `get_ad_schedule` — o gêmeo do filtro `status`

**Files:**
- Modify: `src/mcp/tools/get_ad_schedule.py:135-145` (assinatura), `:180-250` (chamada e resumo)
- Test: `tests/unit/test_ad_schedule_filtro_nao_vira_24x7.py` (criar)

**Interfaces:**
- Consumes: nada das tasks anteriores.
- Produces: `campanhas_com_grade_incerta(rows, *, truncated: bool, campanhas: Collection[str], status: str) -> set[str]` — parâmetro `status` novo e **obrigatório**.

**O defeito.** `summarize_current([])` devolve `{"has_schedule": False, "windows": 0, "hours_per_week": 168.0}` — uma afirmação sobre **entrega**. O F147 já tratou dois jeitos de a lista ficar vazia (campanha ausente do corte, campanha da borda). Existe um terceiro que não está na enumeração: `ad_schedule_query` recebe `status=status`, e `_STATUS_FILTER = {"enabled": "ENABLED", "paused": "PAUSED", "removed": "REMOVED"}`. Pedir `status='paused'` faz campanha de janelas ENABLED voltar vazia — e o resumo responde *"serve 24x7"* sobre uma campanha restrita.

**A regra, e ela é deliberadamente pessimista:** entrega é determinada pelos critérios **ENABLED**. Só `status='enabled'` entrega exatamente esse conjunto. Em `paused`, `removed` **e `all`** o conjunto lido não é o conjunto de entrega — em `all` porque critérios pausados e removidos entrariam na contagem de janelas como se restringissem. Derivar o subconjunto enabled em `all` seria possível, e foi **recusado**: exigiria um segundo argumento de corretude que nada testa. `status != 'enabled'` ⇒ incerta.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_ad_schedule_filtro_nao_vira_24x7.py`:

```python
"""Filtro de status nao pode virar afirmacao sobre entrega."""

from src.mcp.tools.get_ad_schedule import campanhas_com_grade_incerta


def test_filtro_paused_torna_toda_campanha_incerta() -> None:
    """Campanha com janelas ENABLED volta VAZIA sob `status='paused'`, e
    `summarize_current([])` a chamaria de 24x7 — o oposto da verdade."""
    incertas = campanhas_com_grade_incerta(
        [], truncated=False, campanhas=["111", "222"], status="paused"
    )
    assert incertas == {"111", "222"}


def test_filtro_all_tambem_e_incerto() -> None:
    """Sob `all` as linhas incluem criterios pausados e removidos, que NAO
    restringem entrega — contar todos como janela infla `hours_per_week`."""
    incertas = campanhas_com_grade_incerta(
        [], truncated=False, campanhas=["111"], status="all"
    )
    assert incertas == {"111"}


def test_enabled_sem_truncamento_nao_torna_nada_incerto() -> None:
    """CONTROLE POSITIVO: sem ele, uma implementacao que marca TUDO como
    incerto passaria nos dois testes de cima, e a tool nao responderia mais
    nada. `enabled` e o default — o caminho comum nao pode mudar."""
    incertas = campanhas_com_grade_incerta(
        [], truncated=False, campanhas=["111", "222"], status="enabled"
    )
    assert incertas == set()


def test_o_resumo_da_tool_nao_diz_24x7_sob_filtro() -> None:
    """O helper certo nao prova a RESPOSTA certa: o laco que anula os tres
    campos e outro codigo. Sem este teste, `campanhas_com_grade_incerta`
    poderia devolver o conjunto certo e o resumo sair com `false`/`168` assim
    mesmo — o defeito de origem, intacto."""
    from src.mcp.tools.get_ad_schedule import anular_resumos_incertos

    summary = {
        "111": {
            "campaign_name": "A",
            "has_schedule": False,
            "windows": 0,
            "hours_per_week": 168.0,
        }
    }
    anular_resumos_incertos(summary, grade_rows=[], truncated=False, status="paused")

    assert summary["111"]["has_schedule"] is None
    assert summary["111"]["hours_per_week"] is None
    assert summary["111"]["windows"] is None
    assert summary["111"]["schedule_desconhecida_por_filtro"] is True
```

> **Nota ao implementador:** este teste chama `anular_resumos_incertos`, que
> **ainda não existe** — o Step 4 a cria extraindo o laço que hoje vive solto
> dentro da tool. A extração é o ponto: copiar o laço para dentro do teste
> seria duplicar lógica, e cópia diverge no dia em que um dos lados muda.

- [ ] **Step 2: Rode e veja FALHAR**

Run: `python -m pytest tests/unit/test_ad_schedule_filtro_nao_vira_24x7.py -v`
Expected: FAIL — `campanhas_com_grade_incerta() got an unexpected keyword argument 'status'`.

- [ ] **Step 3: A terceira família entra NA função, não num `if` paralelo**

Acrescente o parâmetro e a cláusula em `campanhas_com_grade_incerta`:

```python
def campanhas_com_grade_incerta(
    rows: list[dict[str, Any]],
    *,
    truncated: bool,
    campanhas: Collection[str],
    status: str,
) -> set[str]:
```

No início do corpo, antes das duas famílias existentes:

```python
    # TERCEIRA familia (2026-09-21). As duas de baixo tratam o vazio por CORTE;
    # esta trata o vazio por FILTRO. Entrega e determinada pelos criterios
    # ENABLED, e so `status='enabled'` devolve exatamente esse conjunto:
    # `paused`/`removed` excluem as janelas que restringem, e `all` inclui
    # criterios que nao restringem. Nos tres casos o resumo deixa de ser uma
    # afirmacao sobre entrega.
    #
    # Deliberadamente pessimista em `all`: daria para derivar o subconjunto
    # enabled client-side, e isso exigiria um segundo argumento de corretude
    # que nada testa. A clausula entra AQUI, junto das outras duas — separar
    # as familias de novo e como o F128 nasceu.
    if status != "enabled":
        return set(campanhas)
```

Acrescente à docstring da função, na lista de famílias:

```
    - a **filtrada**: `status` diferente de `enabled` faz a query devolver um
      conjunto que nao e o de entrega. Vale mesmo sem truncamento.
```

- [ ] **Step 4: Extraia o laço e acrescente o marcador do motivo**

O laço que anula os campos vive solto dentro da tool, que faz I/O — então ele não é testável sem subir a tool inteira. **Extraia-o** para uma função pura em `src/mcp/tools/get_ad_schedule.py`, logo depois de `campanhas_com_grade_incerta`:

```python
def anular_resumos_incertos(
    summary: dict[str, dict[str, Any]],
    *,
    grade_rows: list[dict[str, Any]],
    truncated: bool,
    status: str,
) -> None:
    """Poe `null` nos tres campos de entrega das campanhas incertas, IN PLACE.

    Extraida da tool para ser testavel sem I/O. Os tres campos dizem
    desconhecido JUNTOS: `has_schedule: null` ao lado de `windows: 0` le como
    "zero janelas", que e justamente a afirmacao que este bloco existe para
    nao fazer.

    Os dois marcadores de motivo podem aparecer ao mesmo tempo — uma leitura
    pode estar cortada E filtrada, e esconder um dos motivos seria a mesma
    doenca de origem.
    """
    incertas = campanhas_com_grade_incerta(
        grade_rows, truncated=truncated, campanhas=summary, status=status
    )
    for cid, resumo in summary.items():
        if cid not in incertas:
            continue
        resumo["has_schedule"] = None
        resumo["hours_per_week"] = None
        resumo["windows"] = None
        if truncated:
            resumo["schedule_desconhecida_por_truncamento"] = True
        if status != "enabled":
            resumo["schedule_desconhecida_por_filtro"] = True
```

No corpo da tool, troque a chamada a `campanhas_com_grade_incerta` **e** o laço que vinha depois dela por uma linha só:

```python
    anular_resumos_incertos(summary, grade_rows=grade_rows, truncated=truncated, status=status)
```

⚠️ Confira que o `for cid, resumo in summary.items():` antigo saiu — deixar os dois é duplicar a invariante, e duas cópias divergem no dia em que uma é atualizada.

- [ ] **Step 5: Atualize a description da tool**

A description em `src/mcp/tools/get_ad_schedule.py:76-82` afirma hoje que `has_schedule: null` acontece *"sob `truncated: true`"*. Isso passa a ser incompleto. Acrescente, na mesma frase:

```
…e tambem quando `status` e diferente de `enabled`, caso em que o conjunto
lido nao e o de entrega e vem `schedule_desconhecida_por_filtro: true`.
```

Descrição que descreve um mundo antigo é a mesma classe do F182 — o texto é superfície de decisão do LLM.

- [ ] **Step 6: Rode**

Run: `python -m pytest tests/unit/test_ad_schedule_filtro_nao_vira_24x7.py tests/unit/test_ad_schedule_guards.py -v`
Expected: PASS

Run: `python -m pytest tests/ -k "ad_schedule" -v`
Expected: PASS — testes que chamam `campanhas_com_grade_incerta` sem `status` vão quebrar por parâmetro obrigatório faltando. **Isso é desejado**: cada call-site tem de declarar o status que leu. Ajuste-os.

- [ ] **Step 7: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add src/mcp/tools/get_ad_schedule.py tests/unit/test_ad_schedule_filtro_nao_vira_24x7.py tests/
git commit -m "fix(mcp): filtro de status em get_ad_schedule nao vira afirmacao de 24x7"
```

---

## Task 9: O guard que fecha a classe

**Files:**
- Create: `tests/unit/test_terceiro_estado_guard.py`

**Interfaces:**
- Consumes: o estado final das Tasks 2-8.
- Produces: nada que outra task consuma.

**O que este guard afirma, e o que ele deliberadamente NÃO afirma.** Ele acusa **retorno descartado** de `Unpack` e `delete_invite`. Ele **não** tenta reafirmar o contrato de `erros_por_indice`: ali o mecanismo é o mypy (o tipo `LeituraDeFalhas` não tem `.items()`, então todo consumidor quebra em type-check), e duplicar invariante é pior que duplicar código — duas asserções da mesma regra divergem no dia em que uma é atualizada. O papel de `erros_por_indice` aqui é **controle anti-vacuidade**: se ele parar de ser chamado, o guard perdeu o sujeito e tem de gritar.

**Medido em 2026-09-21, sobre 201 arquivos de `src/`:** `erros_por_indice` 3 chamadas, `delete_invite` 1, `Unpack` 1 — **5 no total**. É daí que sai o piso, não de estimativa.

- [ ] **Step 1: Escreva o guard**

Crie `tests/unit/test_terceiro_estado_guard.py`:

```python
"""Retorno que responde "teve efeito?" nao pode ser descartado.

A classe: uma ausencia lida como medicao. `Unpack` devolve `bool` e o retorno
era jogado fora, entao `failure_pb` zerado virava "nenhuma linha falhou";
`delete_invite` devolve `bool` e o retorno era jogado fora, entao o audit
afirmava um cancelamento que podia nao ter ocorrido.

## Por que AST e nao grep

Os arquivos envolvidos CITAM o padrao proibido em prosa para explicar o fix —
grep casaria a propria docstring (modo de falha 1 de guards-que-nao-cobrem).

## Por que `ast.Await` e desembrulhado

Medido em 21/09: `await repo.delete_invite(...)` e
`ast.Expr -> ast.Await -> ast.Call`. Um casador que so olha
`isinstance(no.value, ast.Call)` perde TODO `await` descartado — num codebase
async, quase todos. O desenho original deste guard tinha esse furo e pegava 1
dos 3 alvos.

## O que este guard NAO faz

Nao reafirma o contrato de `erros_por_indice`. Ali o mecanismo e o mypy: o
tipo `LeituraDeFalhas` nao tem `.items()`, entao consumidor que o trate como
dict quebra em type-check. Duas assercoes da mesma regra divergem no dia em
que uma e atualizada. Aqui ele entra so como CONTROLE: se sumir, o guard
perdeu o sujeito.
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _guard_harness as h  # noqa: E402

# Retorno destes responde "teve efeito?" — descartar e ler ausencia como zero.
ALVOS_QUE_NAO_PODEM_SER_DESCARTADOS = {"Unpack", "delete_invite"}

# Controle anti-vacuidade. Medido em 2026-09-21 sobre 201 arquivos de src/:
# erros_por_indice 3, delete_invite 1, Unpack 1. Piso vem da CONTAGEM — um
# piso chutado (200 contra populacao de 161) ja disparou por engano neste repo.
PISO_DE_CHAMADAS = {"erros_por_indice": 3, "delete_invite": 1, "Unpack": 1}


def _chamada(no: ast.AST) -> ast.Call | None:
    """A `Call` de um statement-expression, desembrulhando `await`.

    Recebe `ast.AST` e nao `ast.stmt` de proposito: `ast.walk` devolve `AST`,
    e anotar `stmt` faria o mypy strict recusar o call-site.
    """
    if not isinstance(no, ast.Expr):
        return None
    valor: ast.expr = no.value
    if isinstance(valor, ast.Await):
        valor = valor.value
    return valor if isinstance(valor, ast.Call) else None


def _nome_chamado(chamada: ast.Call, origens: dict[str, str]) -> str | None:
    caminho = h.caminho_canonico(chamada.func, origens)
    return caminho.split(".")[-1] if caminho else None


def _varrer() -> tuple[list[str], dict[str, int]]:
    descartados: list[str] = []
    contagem = dict.fromkeys(PISO_DE_CHAMADAS, 0)
    for arq in h.fontes_py():
        arv = h.arvore(arq)
        origens = h.origens_de_import(arv)
        for no in ast.walk(arv):
            if isinstance(no, ast.Call):
                nome = _nome_chamado(no, origens)
                if nome in contagem:
                    contagem[nome] += 1
            chamada = _chamada(no)
            if chamada is None:
                continue
            nome = _nome_chamado(chamada, origens)
            if nome in ALVOS_QUE_NAO_PODEM_SER_DESCARTADOS:
                descartados.append(f"{h.rel(arq)}:{no.lineno} ({nome})")
    return descartados, contagem


def test_o_guard_tem_sujeito() -> None:
    """CONTROLE. Sem isto, renomear um alvo deixa a varredura vazia e VERDE."""
    _descartados, contagem = _varrer()
    magros = {k: v for k, v in contagem.items() if v < PISO_DE_CHAMADAS[k]}
    if magros:
        raise h.EscopoVazioError(
            f"alvos abaixo do piso medido: {magros} (esperado >= {PISO_DE_CHAMADAS}). "
            "Foram renomeados ou removidos — este guard parou de olhar para eles."
        )


def test_nenhum_retorno_de_efeito_e_descartado() -> None:
    descartados, _contagem = _varrer()
    assert not descartados, (
        "retorno que responde 'teve efeito?' descartado em:\n  "
        + "\n  ".join(descartados)
        + "\nLer a ausencia como zero e a classe inteira deste guard."
    )
```

- [ ] **Step 2: Verifique VERDE contra o código atual**

Run: `python -m pytest tests/unit/test_terceiro_estado_guard.py -v`
Expected: PASS (2 testes) — as Tasks 2-8 já fecharam os dois ofensores.

- [ ] **Step 3: Verifique VERMELHO por sabotagem — o passo que não pode ser pulado**

Um guard que passou de primeira não está verificado. Sabote **por cópia**, nunca com `git checkout`:

```bash
cp src/google_ads/partial_failure.py /tmp/pf-backup.py
```

Edite `src/google_ads/partial_failure.py` e troque a linha `if not raw.Unpack(failure_pb):` (mais o bloco dela) de volta pela forma antiga:

```python
            raw.Unpack(failure_pb)
```

Run: `python -m pytest tests/unit/test_terceiro_estado_guard.py::test_nenhum_retorno_de_efeito_e_descartado -v`
Expected: **FAIL**, nomeando `src/google_ads/partial_failure.py:<linha> (Unpack)`.

Restaure:

```bash
cp /tmp/pf-backup.py src/google_ads/partial_failure.py
rm /tmp/pf-backup.py
```

Repita para `delete_invite`: volte `cancelou = await ...` para `await ...` em `admin_invites.py`, confirme o FAIL, restaure por cópia.

Run: `python -m pytest tests/unit/test_terceiro_estado_guard.py -v`
Expected: PASS de novo. **Se não voltar a passar, a restauração falhou — pare e verifique antes de commitar.**

- [ ] **Step 4: Verifique o controle anti-vacuidade**

Sabote o piso em vez do código: mude temporariamente `PISO_DE_CHAMADAS` para `{"erros_por_indice": 99, "delete_invite": 1, "Unpack": 1}`.

Run: `python -m pytest tests/unit/test_terceiro_estado_guard.py::test_o_guard_tem_sujeito -v`
Expected: **FAIL** com `EscopoVazioError`.

Desfaça a mudança. Sem este passo, o controle é uma asserção que nunca foi vista falhar.

- [ ] **Step 5: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add tests/unit/test_terceiro_estado_guard.py
git commit -m "test(google_ads): guard estrutural — retorno de efeito nao pode ser descartado"
```

---

## Task 10: Catálogo e estado

**Files:**
- Modify: `docs/operacao/findings-catalog.md` (acrescentar ao fim)
- Modify: `docs/operacao/estado-atual.md`
- Modify: `CLAUDE.md` (a linha do catálogo e a data)

**Interfaces:**
- Consumes: o resultado das Tasks 1-9.
- Produces: nada.

- [ ] **Step 1: A entrada no catálogo**

Acrescente `## F191 (HIGH, CORRIGIDO em 2026-09-21) — uma ausência lida como medição, em seis superfícies`, cobrindo:

- os dois gatilhos do `Unpack` (o `except`, realista; a divergência de versão, **latente e não observada** — escreva assim, não arredonde);
- o gradiente medido das três leitoras, e por que só `customer_match` é ALTO;
- a sonda do `Unpack` (`True`/`False`/nome completo);
- F179 e a migration 011, com o precedente da 007;
- a sentinela do CSV e a alternativa recusada (bufferizar) **com o motivo**;
- `filters_applied`: 7 declarados, 5 escondidos, e o fix por derivação;
- `get_ad_schedule`: o terceiro jeito de a lista ficar vazia, e o pessimismo deliberado em `status='all'`;
- **o que ficou de fora**: F154, o resto da Classe B, `migrate.py` sem lock, os ~4 achados não recuperados;
- **a correção ao próprio spec**: o guard desenhado pegava 1 de 3 alvos, porque não desembrulhava `ast.Await` e porque `erros_por_indice` nunca tem retorno descartado.

- [ ] **Step 2: `estado-atual.md`**

Na tabela "Varredura de 21/09", marque o sub-projeto **2** como fechado e diga o que dele **não** foi feito (F154 saiu para spec próprio). Atualize a contagem de sub-projetos fechados de 1 para 2.

- [ ] **Step 3: `CLAUDE.md`**

Atualize `**F1–F190, ~4690 linhas, 512 KB**` para a medição real depois da entrada nova:

```bash
python - <<'PY'
from pathlib import Path
p = Path("docs/operacao/findings-catalog.md")
t = p.read_text(encoding="utf-8")
print("linhas:", t.count("\n") + 1, "| KB:", round(len(t.encode()) / 1024))
PY
```

⚠️ **O `CLAUDE.md` tem teto de 24000 bytes com guard**, e a folga medida em 21/09 era de **56 bytes**. Meça depois de editar:

```bash
python -c "print(len(open('CLAUDE.md',encoding='utf-8').read().replace(chr(13),'').encode()))"
```

Se passar de 24000, corte de outro lugar — não aumente o teto.

- [ ] **Step 4: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add docs/ CLAUDE.md
git commit -m "docs(operacao): F191 no catalogo, com o latente declarado como latente"
```

---

## Verificação final, antes de abrir o PR

- [ ] `python scripts/check_pre_push.py` → 6/6, EXIT=0
- [ ] `python scripts/check_pre_push_full.py` → verde (ou o motivo escrito, se o Docker não subir)
- [ ] `python -m pytest tests/unit/test_terceiro_estado_guard.py -v` → PASS, **e visto vermelho por sabotagem** nos dois alvos
- [ ] `git log --oneline` mostra 10 commits, um por task
- [ ] Nenhuma ocorrência de `.items()` aplicado direto ao retorno de `erros_por_indice`:

```bash
grep -rn "erros_por_indice(" -A 6 src/ | grep -c "\.items()"
```
Esperado: `0` — o consumo agora é `leitura.erros.items()`, que este grep não casa por estar em outra linha. Se der diferente de zero, leia o call-site.

**A verificação em produção não vai neste plano.** Ela depende de deploy e do gestor presente; o smoke correspondente é assunto do PR, não das tasks.
