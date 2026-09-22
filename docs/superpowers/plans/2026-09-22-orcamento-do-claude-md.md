# Orçamento do `CLAUDE.md` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Devolver folga ao `CLAUDE.md` movendo para os arquivos roteados as 37 regras do `Don't do` que só disparam dentro de uma área, mantendo as 8 que disparam onde nada roteia.

**Architecture:** Aditivo primeiro, subtrativo por último. As Tasks 2–6 **copiam** cada grupo de regras para o arquivo de convenção da área; a Task 7 **remove** do `CLAUDE.md` só o que já chegou ao destino. Todo estado intermediário tem a regra em pelo menos um lugar, e o scan da Task 1 — escrito antes de qualquer movimento — fica verde do início ao fim, ou uma regra se perdeu.

**Tech Stack:** Markdown · pytest (o scan é um teste) · o guard de orçamento já existente em `tests/unit/test_docs_links.py`

**Spec:** [`2026-09-22-orcamento-do-claude-md-design.md`](../specs/2026-09-22-orcamento-do-claude-md-design.md)

## Global Constraints

- **Nenhuma regra pode se perder.** É a invariante desta mudança, e o scan da Task 1 a verifica. Se ele ficar vermelho, pare e investigue — não ajuste o scan para passar.
- **Aditivo antes de subtrativo.** Nunca remova do `CLAUDE.md` antes de o destino existir e o scan estar verde.
- Gate antes de cada commit: `python scripts/check_pre_push.py`, rodado **mudo**, lendo `$?`. **Nunca** pipe entre o gate e o `&&` — o exit code de um pipeline é o do último comando, e isso já deixou passar commit com gate vermelho neste repo.
- O guard de orçamento mede o `CLAUDE.md` **com CRLF normalizado para LF**, teto 24.000. Meça do mesmo jeito: `python -c "print(len(open('CLAUDE.md',encoding='utf-8').read().replace(chr(13),'').encode()))"`.
- O guard de links relativos (`tests/unit/test_docs_links.py`) **reprova link que não resolve**. Todo ponteiro novo tem de apontar para arquivo existente.
- **Nunca `git checkout`** para desfazer — restaure por cópia.
- Commits `docs(convencoes):` / `docs(claude):` / `test(docs):`, terminando com `Co-Authored-By:` do modelo que você é.
- PT-BR. Ao mover uma regra, **adapte a voz ao arquivo de destino** — mas **não altere o que ela manda fazer**.

---

## Estrutura de arquivos

| arquivo | responsabilidade nesta mudança |
|---|---|
| `tests/unit/test_nenhuma_regra_se_perdeu.py` | **criar** — o scan das 45 âncoras |
| `docs/convencoes/painel.md` | recebe 12 regras de painel/CSS/template/HTMX |
| `docs/convencoes/nucleo.md` | recebe 11 regras de executor/gate/pool/SDK |
| `docs/convencoes/dados.md` | recebe 4 regras de query/janela de data |
| `docs/convencoes/testes.md` | recebe 5 regras + as 3 ilustrações do bullet do guard |
| `docs/convencoes/processo.md` | recebe 5 regras de processo/dependência/deploy |
| `CLAUDE.md` | perde 37 regras, ganha bloco de ponteiros, tabela de roteamento atualizada |

---

## Task 1: O scan, antes de qualquer movimento

**Por que primeiro:** sem ele, mover 37 regras entre seis arquivos é irreversível na prática — ninguém consegue provar depois que nada caiu. O scan é o que torna o resto seguro.

**Files:**
- Create: `tests/unit/test_nenhuma_regra_se_perdeu.py`

**Interfaces:**
- Consumes: nada.
- Produces: `test_nenhuma_regra_se_perdeu` e `test_o_scan_tem_escopo`. As Tasks 2–8 rodam os dois.

**A ideia:** uma regra é identificada por uma **âncora** — um trecho distintivo que sobrevive à reescrita — e não pelo texto, que muda ao mudar de arquivo. As 45 âncoras abaixo foram extraídas do `CLAUDE.md` em 2026-09-22, **antes** da separação, e verificadas como **únicas** (zero duplicatas). Se uma âncora some da união dos seis arquivos, uma regra se perdeu.

- [ ] **Step 1: Escreva o scan**

Crie `tests/unit/test_nenhuma_regra_se_perdeu.py`:

```python
"""Nenhuma regra `Don't` se perdeu ao sair do CLAUDE.md para os arquivos roteados.

A separacao de 2026-09-22 moveu 37 das 45 regras do `Don't do` para
`docs/convencoes/`. Mover texto entre arquivos e uma operacao sem rede: se um
bullet cair no caminho, nada acusa — o CLAUDE.md so fica menor, que e o que se
queria.

Cada regra e identificada por uma ANCORA (um trecho distintivo), nao pelo
texto: o texto e reescrito para caber na voz do arquivo de destino, e comparar
texto daria falso positivo a cada adaptacao legitima. As 45 ancoras foram
extraidas ANTES da separacao e verificadas como unicas.

Se um teste aqui ficar vermelho, uma regra sumiu. NAO ajuste a lista para
passar — ache a regra.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _guard_harness as h  # noqa: E402

# Os seis arquivos onde uma regra pode viver depois da separacao.
_FONTES = ["CLAUDE.md"] + [
    f"docs/convencoes/{n}.md" for n in ("nucleo", "painel", "testes", "dados", "processo")
]

# Uma ancora por regra, na ordem em que apareciam no `Don't do` original.
ANCORAS = (
    "best_effort",                              # 1
    "git checkout",                             # 2
    "run_with_reconnect",                       # 3
    "validate_gaql",                            # 4
    "check_pre_push.py | tail && git commit",   # 5
    "gh run view <id> --json conclusion",       # 6
    "⬜ pending",                                # 7
    "classificador de auto mode",               # 8
    "ci.yml",                                   # 9
    "build_client_for_manager",                 # 10
    "_CSP_POLICY",                              # 11
    "conn.cursor(...)",                         # 12
    "pool.acquire()",                           # 13
    "python scripts/build_tailwind.py",         # 14
    "--v4-gray-300",                            # 15
    "--universal",                              # 16
    "por ordem de criação",                     # 17
    "run_blocking",                             # 18
    "-03:00",                                   # 19
    "change_event",                             # 20
    "datetime.now",                             # 21
    "mgr:<uuid>",                               # 22
    "blast_radius.classify",                    # 23
    "?v={{ asset_version }}",                   # 24
    "_CSRF_EXEMPT_ROUTES",                      # 25
    "hx-post",                                  # 26
    'role="button"',                            # 27
    "onclick=",                                 # 28
    "search_input",                             # 29
    "pyproject.toml",                           # 30
    "error_envelope",                           # 31
    "AttributeError",                           # 32
    "SQL cru sem extremo cuidado",              # 33
    "superpowers:brainstorming",                # 34
    "arquivos OVERLAPPING",                     # 35
    "per-value empirical probe",                # 36
    "make_capture_client",                      # 37
    "oneOf/allOf/anyOf",                        # 38
    "facebook_business",                        # 39
    "is_allowed_email",                         # 40
    "{{ button() }}",                           # 41
    "sessions_revoke",                          # 42
    "request.query_params",                     # 43
    "ads_get_field_context",                    # 44
    "pipe PowerShell",                          # 45
)


def _uniao() -> str:
    """O texto dos seis arquivos, concatenado."""
    return "\n".join(
        (h.RAIZ / nome).read_text(encoding="utf-8") for nome in _FONTES
    )


def test_o_scan_tem_escopo() -> None:
    """CONTROLE ANTI-VACUIDADE. Um scan que le zero arquivos passa por vacuidade.

    Sem isto, renomear `docs/convencoes/` deixaria a uniao quase vazia e o teste
    de baixo acusaria 45 regras sumidas — ou, se a lista tambem esvaziasse,
    passaria verde varrendo nada.
    """
    faltando = [n for n in _FONTES if not (h.RAIZ / n).exists()]
    assert not faltando, f"arquivo de destino nao existe: {faltando}"
    assert len(ANCORAS) == 45, f"a lista tem {len(ANCORAS)} ancoras, esperava 45"
    assert len(set(ANCORAS)) == 45, "ha ancora duplicada — ela deixa de identificar UMA regra"
    assert len(_uniao()) > 40_000, "uniao pequena demais: algum arquivo nao foi lido"


def test_nenhuma_regra_se_perdeu() -> None:
    texto = _uniao()
    sumidas = [(i, a) for i, a in enumerate(ANCORAS, 1) if a not in texto]
    assert not sumidas, (
        "regras que sumiram da uniao CLAUDE.md + docs/convencoes/:\n  "
        + "\n  ".join(f"#{i}: {a!r}" for i, a in sumidas)
        + "\nNAO remova a ancora da lista — ache a regra."
    )
```

- [ ] **Step 2: Confirme VERDE contra o estado atual**

Run: `python -m pytest tests/unit/test_nenhuma_regra_se_perdeu.py -v`
Expected: 2 passed — as 45 âncoras estão todas no `CLAUDE.md` hoje.

Se alguma falhar **agora**, a âncora está errada (o texto mudou desde a extração). Conserte a âncora, não o `CLAUDE.md`.

- [ ] **Step 3: Confirme VERMELHO por sabotagem — o passo que não pode ser pulado**

Um scan que passou de primeira não está verificado. Sabote **por cópia**:

```bash
cp CLAUDE.md /tmp/claude-backup.md
```

Apague do `CLAUDE.md` o bullet inteiro que contém `` `_CSP_POLICY` ``.

Run: `python -m pytest tests/unit/test_nenhuma_regra_se_perdeu.py::test_nenhuma_regra_se_perdeu -v`
Expected: **FAIL**, nomeando `#11: '_CSP_POLICY'`.

Restaure e confirme:

```bash
cp /tmp/claude-backup.md CLAUDE.md
rm /tmp/claude-backup.md
git diff --stat CLAUDE.md
```
Expected: vazio. Se não estiver, a restauração falhou — pare e conserte antes de commitar.

Run: `python -m pytest tests/unit/test_nenhuma_regra_se_perdeu.py -v`
Expected: 2 passed de novo.

- [ ] **Step 4: Sabote o controle anti-vacuidade**

Troque temporariamente `_FONTES` para `["CLAUDE.md"]` só.

Run: `python -m pytest tests/unit/test_nenhuma_regra_se_perdeu.py::test_o_scan_tem_escopo -v`
Expected: **FAIL** no `len(_uniao()) > 40_000` ou no comprimento — o controle acusa escopo encolhido.

Desfaça. Sem este passo, o controle é asserção que nunca foi vista falhar.

- [ ] **Step 5: Gate e commit**

```bash
python scripts/check_pre_push.py
```
Leia `$?`. Só commite com EXIT=0.

```bash
git add tests/unit/test_nenhuma_regra_se_perdeu.py
git commit -m "test(docs): scan que prova que nenhuma regra Don't se perde na separacao"
```

---

## Task 2: As 12 regras de painel vão para `painel.md`

**Files:**
- Modify: `docs/convencoes/painel.md`

**Interfaces:**
- Consumes: o scan da Task 1.
- Produces: as 12 regras vivendo em `painel.md`. A Task 7 as remove do `CLAUDE.md`.

**As 12, por âncora** (localize cada bullet no `Don't do` do `CLAUDE.md` pela âncora, não por número de linha):

| # | âncora | assunto |
|---|---|---|
| 11 | `_CSP_POLICY` | recurso externo exige atualizar a CSP no mesmo commit |
| 14 | `python scripts/build_tailwind.py` | classe utilitária exige rebuild + CSS commitado junto |
| 15 | `--v4-gray-300` | contraste 2,1:1 sobre fundo claro |
| 24 | `?v={{ asset_version }}` | `aria-label` em nó trocado por HTMX + cache de `/static` |
| 25 | `_CSRF_EXEMPT_ROUTES` | isentar rota, nunca prefixo |
| 26 | `hx-post` | POST de mutação sem HTMX devolve 303, não 200 |
| 27 | `role="button"` | `role="button"` num `<tr>` quebra o vínculo com `<th scope>` |
| 28 | `onclick=` | JS e CSS inline morrem calados sob a CSP |
| 29 | `search_input` | macro não pode emitir markup que o consumidor não alcança |
| 41 | `{{ button() }}` | `button()` em `<form>` precisa de `type="submit"` |
| 42 | `sessions_revoke` | handler de `hx-post` não retorna 303 cru |
| 43 | `request.query_params` | XSS na macro `alert` + `<table>` fora de contentor de scroll |

- [ ] **Step 1: Leia o destino antes de escrever**

Leia `docs/convencoes/painel.md` inteiro. Ele já tem seções por assunto (CSP, Tailwind, HTMX, a11y). **Cada regra entra na seção que já trata daquele assunto** — não crie uma seção "Don't do" paralela, que recriaria no destino o amontoado que estamos desfazendo.

Se uma regra não tiver seção óbvia, crie uma com título descritivo do assunto.

- [ ] **Step 2: Mova as 12**

Copie cada regra do `CLAUDE.md` para a seção certa de `painel.md`. **Adapte a voz ao arquivo** (ele é prosa de convenção, não lista de tripwires) mas **preserve a âncora literalmente** e **não altere o que a regra manda fazer**.

Mantenha as referências `(F101)`, `(F125)` etc. — elas são o ponteiro para o catálogo.

**Não remova nada do `CLAUDE.md` nesta task.** A remoção é a Task 7, e só depois de o destino existir.

- [ ] **Step 3: Rode o scan**

Run: `python -m pytest tests/unit/test_nenhuma_regra_se_perdeu.py -v`
Expected: 2 passed. Nesta fase cada regra está em **dois** lugares — o scan só exige **pelo menos um**.

- [ ] **Step 4: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add docs/convencoes/painel.md
git commit -m "docs(convencoes): as 12 regras de painel passam a viver em painel.md"
```

---

## Task 3: As 11 regras de executor vão para `nucleo.md`

**Files:**
- Modify: `docs/convencoes/nucleo.md`

**Interfaces:**
- Consumes: o scan da Task 1.
- Produces: as 11 regras vivendo em `nucleo.md`.

**As 11, por âncora:**

| # | âncora | assunto |
|---|---|---|
| 1 | `best_effort` | I/O de bookkeeping em `finally` tem poder de veto |
| 3 | `run_with_reconnect` | retry re-executa escrita |
| 10 | `build_client_for_manager` | gate "a todos os executores" exige `grep` de todos |
| 13 | `pool.acquire()` | read de disponibilidade usa `run_with_reconnect` |
| 18 | `run_blocking` | SDK de ads fora de closure offloadado |
| 22 | `mgr:<uuid>` | reportar QUAL quota |
| 23 | `blast_radius.classify` | computar e ignorar `.level` |
| 31 | `error_envelope` | montar envelope de mutate à mão |
| 39 | `facebook_business` | não trazer o SDK de volta ao caminho de request |
| 40 | `is_allowed_email` | não aplicar domínio V4 no callback Meta |
| 44 | `ads_get_field_context` | validar fields Meta novos antes de shippar |

- [ ] **Step 1: Leia o destino**

Leia `docs/convencoes/nucleo.md` inteiro (12,7 KB — é o maior dos cinco). Ele já cobre executores, gate de acesso, pool e observabilidade. Encaixe cada regra na seção do assunto.

- [ ] **Step 2: Mova as 11**

Mesmas regras da Task 2: adapte a voz, preserve a âncora literal, não altere o que a regra manda, mantenha as referências `F`.

- [ ] **Step 3: Rode o scan**

Run: `python -m pytest tests/unit/test_nenhuma_regra_se_perdeu.py -v`
Expected: 2 passed.

- [ ] **Step 4: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add docs/convencoes/nucleo.md
git commit -m "docs(convencoes): as 11 regras de executor passam a viver em nucleo.md"
```

---

## Task 4: As 4 regras de query e janela vão para `dados.md`

**Files:**
- Modify: `docs/convencoes/dados.md`

**Interfaces:**
- Consumes: o scan da Task 1.
- Produces: as 4 regras vivendo em `dados.md`.

**As 4, por âncora:**

| # | âncora | assunto |
|---|---|---|
| 12 | `conn.cursor(...)` | cursor exige transação explícita; coluna sem alias em JOIN |
| 19 | `-03:00` | fuso hardcodado em mutate que grava timestamp |
| 20 | `change_event` | remover entidade com `status` é UPDATE, não REMOVE |
| 21 | `datetime.now` | relógio do servidor em tool Google |

**Nota:** as regras 19 e 21 são cobertas por guard (`test_no_server_clock_in_google_tools.py`). Isso é o que torna seguro movê-las: o CI reprova a violação mesmo que ninguém leia o texto. **Diga isso na prosa do destino** — quem lê precisa saber que ali há mecanismo, não só recomendação.

- [ ] **Step 1: Leia o destino**

Leia `docs/convencoes/dados.md` (2,2 KB — é o menor). Ele vai crescer bastante; se ficar sem estrutura, crie seções por assunto (transação/cursor · janela de data e fuso · `change_event`).

- [ ] **Step 2: Mova as 4**

- [ ] **Step 3: Rode o scan**

Run: `python -m pytest tests/unit/test_nenhuma_regra_se_perdeu.py -v`
Expected: 2 passed.

- [ ] **Step 4: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add docs/convencoes/dados.md
git commit -m "docs(convencoes): as 4 regras de query e janela passam a viver em dados.md"
```

---

## Task 5: As 5 regras de teste e as 3 ilustrações do bullet do guard vão para `testes.md`

**Files:**
- Modify: `docs/convencoes/testes.md`

**Interfaces:**
- Consumes: o scan da Task 1.
- Produces: as 5 regras em `testes.md`, **mais** as três ilustrações de 02/09 extraídas do bullet #2 — cuja regra **permanece** no `CLAUDE.md`.

**As 5, por âncora:**

| # | âncora | assunto |
|---|---|---|
| 4 | `validate_gaql` | não assertar superfície de API externa por analogia |
| 32 | `AttributeError` | mover função exige `grep` dos patch-sites em `tests/` |
| 36 | `per-value empirical probe` | enum whitelist exige probe por valor no smoke |
| 37 | `make_capture_client` | não usar MagicMock em builder tests de proto |
| 38 | `oneOf/allOf/anyOf` | Anthropic rejeita em `input_schema` |

- [ ] **Step 1: Mova as 5**

Como nas tasks anteriores: voz do destino, âncora literal, regra intacta.

- [ ] **Step 2: Extraia as ilustrações do bullet #2 — e SÓ as ilustrações**

O bullet da âncora `git checkout` tem 765 bytes e é o maior do `Don't do`. Ele contém duas coisas:

- **a regra** — *"não confie em guard que passou de primeira; verifique contra o código PRÉ-fix, por sabotagem ou cópia, nunca `git checkout`"* e *"não assira o ADJACENTE à invariante"*. **Esta parte FICA no `CLAUDE.md`** (Task 7) porque dispara ao verificar **qualquer** fix, não só ao escrever teste.
- **as três ilustrações de 02/09** — o grep casando a própria docstring, o AST exigindo forma que o codebase não usa, e o AST vendo só dict literal. **Estas vão para `testes.md`.**

Escreva as três em `testes.md` com contexto suficiente para serem compreensíveis fora do bullet original.

⚠️ **A âncora `git checkout` fica no `CLAUDE.md`.** Não a mova junto com as ilustrações — se ela sair, a regra saiu.

- [ ] **Step 3: Rode o scan**

Run: `python -m pytest tests/unit/test_nenhuma_regra_se_perdeu.py -v`
Expected: 2 passed.

- [ ] **Step 4: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add docs/convencoes/testes.md
git commit -m "docs(convencoes): regras de teste e as ilustracoes do guard vao para testes.md"
```

---

## Task 6: As 5 regras de processo, dependência e deploy vão para `processo.md`

**Files:**
- Modify: `docs/convencoes/processo.md`

**Interfaces:**
- Consumes: o scan da Task 1.
- Produces: as 5 regras vivendo em `processo.md`.

**As 5, por âncora:**

| # | âncora | assunto |
|---|---|---|
| 7 | `⬜ pending` | não fechar sprint de tool mutante com APPLY ou RESTAURAÇÃO pendente |
| 16 | `--universal` | `uv pip compile` sem a flag quebra o build Linux |
| 17 | `por ordem de criação` | capturar a revisão servindo ANTES do deploy |
| 30 | `pyproject.toml` | dependência nova exige regenerar o lockfile no mesmo commit |
| 35 | `arquivos OVERLAPPING` | não despachar implementadores em paralelo em arquivos sobrepostos |

**Nota de destino, do spec §5:** as regras 16, 17 e 30 são de dependência e deploy e **não tinham linha própria na tabela de roteamento**. Vão para `processo.md` ("procedimento operacional raro"), e a Task 7 acrescenta a linha que faltava.

- [ ] **Step 1: Mova as 5**

- [ ] **Step 2: Rode o scan**

Run: `python -m pytest tests/unit/test_nenhuma_regra_se_perdeu.py -v`
Expected: 2 passed.

- [ ] **Step 3: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add docs/convencoes/processo.md
git commit -m "docs(convencoes): regras de processo, dependencia e deploy vao para processo.md"
```

---

## Task 7: O `CLAUDE.md` encolhe

**Por que por último:** até aqui cada regra movida existe em **dois** lugares. Esta task remove a cópia do `CLAUDE.md` — e o scan, que ficou verde o caminho inteiro, é o que prova que a remoção não levou nada junto.

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: as Tasks 2–6 (os destinos precisam existir).
- Produces: `CLAUDE.md` com 8 regras, bloco de ponteiros e tabela de roteamento atualizada.

**As 8 que FICAM, por âncora** — e o motivo de cada uma, do spec §5:

| # | âncora | por que não pode ser roteada |
|---|---|---|
| 2 | `git checkout` | dispara ao verificar **qualquer** fix. Fica a regra; as ilustrações já foram (Task 5) |
| 5 | `check_pre_push.py \| tail && git commit` | shell — nada roteia para um pipe |
| 6 | `gh run view <id> --json conclusion` | CI |
| 8 | `classificador de auto mode` | autorização humana; freio de segurança |
| 9 | `ci.yml` | git/CI — PR empilhado sem checks |
| 33 | `SQL cru sem extremo cuidado` | destrutivo |
| 34 | `superpowers:brainstorming` | é a regra que manda **rotear**; não pode viver no destino |
| 45 | `pipe PowerShell` | segredo |

- [ ] **Step 1: Meça o ponto de partida**

```bash
python -c "print(len(open('CLAUDE.md',encoding='utf-8').read().replace(chr(13),'').encode()))"
```
Anote o número (esperado: 23976).

- [ ] **Step 2: Remova os 37 bullets movidos**

Apague do `Don't do` todo bullet cuja âncora **não** está na tabela das 8 acima. Confira um a um pela âncora — não por posição, que muda a cada remoção.

- [ ] **Step 3: Comprima o bullet #2**

O bullet da âncora `git checkout` perdeu as ilustrações (Task 5). Reescreva-o na forma curta, preservando a âncora e apontando para onde as ilustrações foram:

```markdown
- Don't confiar em guard que passou de primeira: verifique contra o código PRÉ-fix (sabotagem ou cópia — **nunca `git checkout`**, que descarta trabalho não commitado). E don't asserir o ADJACENTE à invariante: se a asserção não distingue código bom de quebrado, ela não é guard. Os modos e os exemplos medidos estão em `docs/convencoes/testes.md`.
```

- [ ] **Step 4: Acrescente o bloco de ponteiros**

No fim do `Don't do`, acrescente o bloco abaixo — é a mitigação do spec §6, e o que preserva a propriedade de **saber que a regra existe** sem carregá-la.

⚠️ **No exemplo os caminhos estão em crase; no `CLAUDE.md` eles têm de virar link markdown** — colchete com o rótulo, parênteses com o caminho, como o resto do arquivo. O exemplo não os traz como link porque o guard de links varre linha a linha, sem pular cerca de código, e leria o exemplo como link quebrado deste plano — os caminhos resolvem a partir da raiz, onde o `CLAUDE.md` vive, não de `docs/superpowers/plans/`:

```markdown
**Os tripwires de área saíram daqui em 22/09 e vivem com a convenção da área.**
Acima ficaram só os que disparam onde nada roteia — shell, git, CI, segredo,
autorização, processo. Se você vai mexer numa destas áreas, **as regras dela
estão no arquivo roteado**, não aqui:

| área | arquivo | o que mora lá |
|---|---|---|
| painel, CSS, template, HTMX, CSP, a11y | `docs/convencoes/painel.md` | 12 regras |
| executor, gate, pool, SDK, envelope de mutate | `docs/convencoes/nucleo.md` | 11 regras |
| query, transação, janela de data, fuso | `docs/convencoes/dados.md` | 4 regras |
| teste, mock, probe de API externa | `docs/convencoes/testes.md` | 5 regras |
| dependência, deploy, rollback, sprint | `docs/convencoes/processo.md` | 5 regras |
```

- [ ] **Step 5: Atualize a tabela de roteamento**

Na tabela "Vai mexer em… → Leia" da seção `Context bootstrap`, acrescente à última coluna de cada linha que os **tripwires da área** vivem lá. E acrescente a linha que faltava:

```markdown
| adicionar dependência, mexer em deploy ou rollback | `docs/convencoes/processo.md` |
```

- [ ] **Step 6: Rode o scan — é aqui que ele ganha o dinheiro dele**

Run: `python -m pytest tests/unit/test_nenhuma_regra_se_perdeu.py -v`
Expected: 2 passed.

**Se falhar:** uma regra foi removida do `CLAUDE.md` sem ter chegado ao destino. A mensagem nomeia qual. **Não remova a âncora da lista** — volte e escreva a regra no arquivo de convenção que faltou.

- [ ] **Step 7: Meça o resultado**

```bash
python -c "b=len(open('CLAUDE.md',encoding='utf-8').read().replace(chr(13),'').encode()); print(f'{b} bytes | folga {24000-b}')"
```
Expected: ~14.400 bytes, folga ~9.600. **Se a folga ficar abaixo de 8.000**, o critério de pronto do spec não foi atingido — diga no relatório em vez de arredondar.

- [ ] **Step 8: Gate e commit**

```bash
python scripts/check_pre_push.py
```
O gate inclui o guard de orçamento **e** o de links relativos, que reprova se um ponteiro novo não resolver.

```bash
git add CLAUDE.md
git commit -m "docs(claude): os tripwires de area saem para os arquivos roteados"
```

---

## Task 8: O registro

**Files:**
- Modify: `docs/operacao/findings-catalog.md`
- Modify: `CLAUDE.md` (só a métrica do catálogo, se ela mudar)

**Interfaces:**
- Consumes: o resultado das Tasks 1–7.
- Produces: nada.

- [ ] **Step 1: A entrada no catálogo**

Acrescente uma entrada registrando a separação. Ela precisa conter, porque o spec exige que o que ficou de fora esteja **escrito e não subentendido**:

- os números medidos: 45 bullets, 12.751 B; 8 ficam (2.765 B), 37 saem (9.985 B); `CLAUDE.md` de 23.976 para o valor real medido na Task 7;
- **o racional do teto**, citado do guard: o arquivo chegou a 54.852 B em 08-19, a separação por área o derrubou a 17,7 KB, e o teto existe contra o acúmulo — que o levou de volta a 24,0 KB;
- **o eixo do corte** (dispara onde nada roteia × só importa dentro da área) e o **segundo eixo** (regra com guard é mais segura de mover, porque o mecanismo não depende de atenção);
- **o método que caiu na medição**: "comprime para ponteiro F-N" exigiria escrever 33 entradas antes, porque 74% dos bullets são órfãos;
- **o erro de instrumento**: o catálogo registra findings em duas formas (62 em tabela, 52 em cabeçalho) e o primeiro detector via uma só, produzindo um número que era artefato;
- **o risco assumido**: 78% dos tripwires saíram do arquivo sempre-carregado, e a mitigação são a tabela de roteamento, o bloco de ponteiros e o scan;
- **o que ficou de fora**: comprimir o catálogo, arquivar os 16 planos órfãos (556 KB medidos sem link de entrada), e subir o teto.

- [ ] **Step 2: Remeça a métrica do catálogo**

```bash
python -c "from pathlib import Path; t=Path('docs/operacao/findings-catalog.md').read_text(encoding='utf-8'); print('linhas:', t.count(chr(10))+1, '| KB:', round(len(t.encode())/1024))"
```

Se os números do `CLAUDE.md` divergirem, atualize-os. ⚠️ **E meça o `CLAUDE.md` de novo depois** — agora há folga, mas o guard continua no mesmo teto.

- [ ] **Step 3: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add docs/operacao/findings-catalog.md CLAUDE.md
git commit -m "docs(operacao): a separacao de 22/09 no catalogo, com o risco declarado"
```

---

## Verificação final, antes de abrir o PR

- [ ] `python scripts/check_pre_push.py` → 6/6, EXIT=0
- [ ] `python -m pytest tests/unit/test_nenhuma_regra_se_perdeu.py -v` → 2 passed, **e visto vermelho por sabotagem** na Task 1
- [ ] Folga do `CLAUDE.md` ≥ 8.000 bytes, medida com CRLF normalizado
- [ ] `git log --oneline` mostra 8 commits, um por task
- [ ] As 45 âncoras aparecem na união — e o `CLAUDE.md` sozinho contém exatamente as 8 que ficaram:

```bash
python -c "
from pathlib import Path
c = Path('CLAUDE.md').read_text(encoding='utf-8')
ficam = ['git checkout','check_pre_push.py | tail && git commit','gh run view <id> --json conclusion','classificador de auto mode','ci.yml','SQL cru sem extremo cuidado','superpowers:brainstorming','pipe PowerShell']
print('presentes no CLAUDE.md:', sum(1 for a in ficam if a in c), 'de 8')"
```
Expected: `8 de 8`
