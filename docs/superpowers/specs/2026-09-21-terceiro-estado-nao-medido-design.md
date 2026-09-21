# O terceiro estado: "não medido" como valor — design

**Data:** 2026-09-21
**Origem:** varredura ampla de 5 agentes paralelos (2026-09-21), **sub-projeto 2 de 4**.
O sub-projeto 1 fechou como F190. Este recorta a **Classe A** de uma reclassificação feita
em 21/09: os achados não se agrupam bem por sintoma (a divisão original era
"respostas / infra / guards"), e sim por **forma de defeito**. Todos os membros abaixo têm
a mesma: *um retorno que responde "teve efeito?" é descartado, e a ausência que sobra é
lida como zero.*

**Decisões do Wellington (2026-09-21):**

1. **Terceiro estado, uniforme** — em toda superfície, "não medido" vira valor próprio,
   distinto de zero e de sucesso. Estende o padrão que o `efeito` do `apply_change` (F184)
   já usa.
2. **Tipo que obriga, só no `erros_por_indice`** — a única função com três consumidores e
   gradiente de severidade medido. O resto do repo não vira `Result`.
3. **F154 sai deste spec** — mesma classe, outra forma (um sinal que responde uma pergunta
   e é exibido como outra). Toca `jobs/meta_resync` e o painel admin, subsistemas que
   nenhum outro membro toca. Spec próprio depois.
4. **F185, F186 e F180 ficam como estão** — já documentados; nenhum tem código que os feche.

---

## 1. A regra

> **Uma ausência não é uma medição.** Quando o sistema não consegue confirmar um efeito, ele
> diz isso — não devolve zero, não devolve sucesso, e não inventa um motivo genérico.

A regra **já existe escrita neste repo**, e bem. `anotar_efeito_por_operacao`
(`src/google_ads/mutations.py:164`) a aplica corretamente:

> `None` — desconhecido. [...] Nao saber e diferente de nao ter mudado, e afirmar
> `sem_efeito` a partir de uma ausencia seria cometer o F184 do nosso lado.

O `apply_change` documenta o mesmo para `failed_count: null` — *"null significa NAO MEDIDO,
nao 'nenhuma falhou'"*.

**O defeito deste spec não é a falta da regra. É que nada a aplica fora desses dois
pontos.** É a lente de 21/09 (F188/F189/F190): *a regra existe e o mecanismo não* — e a
forma mais frequente dela, o **gêmeo**, aparece literalmente no membro 5.

---

## 2. A sonda

A regra da casa proíbe assertar superfície de API externa por analogia (F87, F89). O
comportamento do `Unpack` foi **medido**, não deduzido, contra o protobuf instalado:

```
Unpack(tipo CERTO)        -> True   | alvo: 'x'
Unpack(tipo ERRADO)       -> False  | alvo: 0      ← sem exceção
Unpack(type_url alterado) -> False  | alvo: ''     ← compara por NOME COMPLETO
```

Três fatos que o desenho usa:

1. `Unpack` devolve **`bool`**.
2. Na divergência ele **não levanta** — devolve `False` e **deixa o alvo intocado**.
3. A comparação é pelo **nome completo** do tipo, então `...v20.errors.GoogleAdsFailure`
   contra um alvo v24 devolve `False`.

---

## 3. O defeito, membro a membro

### 3.1 `erros_por_indice` — o núcleo

`src/google_ads/partial_failure.py:93`:

```python
failure_pb = client.get_type("GoogleAdsFailure")._meta.pb()
raw.Unpack(failure_pb)          # ← retorno descartado
for gae in failure_pb.errors:   # ← vazio se o Unpack falhou
```

`False` ⇒ `failure_pb` fica zerado ⇒ o laço não roda ⇒ a função devolve `{}`. O mesmo `{}`
que significa *"nenhuma linha falhou"*.

**Dois gatilhos, e eles não têm a mesma probabilidade:**

| gatilho | avaliação |
|---|---|
| o `except Exception` do laço (linha 102) — já existe e já loga `partial_failure_detail_unpack_failed` | **realista**: qualquer drift de campo do proto cai aqui |
| `Unpack` devolvendo `False` por divergência de versão no `type_url` | **latente, não observado em produção** |

Não se afirma que o segundo já disparou. **Ninguém mediu** — e é justamente o que este spec
existe para não fazer.

O segundo é latente, mas o módulo é **inconsistente por construção** sobre exatamente ele.
O filtro é deliberadamente agnóstico de versão, com o motivo escrito no comentário
(*"o type_url evita importar a classe versionada do proto"*):

```python
if "GoogleAdsFailure" not in raw.type_url:
    continue
```

…e o alvo entregue ao `Unpack` é **versionado** (`client.get_type(...)`, que segue a versão
configurada do cliente). A defesa contra variação de versão está num lado e a sensibilidade
a ela está no outro.

**A contradição no próprio docstring.** `erros_por_indice` justifica engolir a falha assim:

> Cair para "nao sei quem falhou" e mais seguro que levantar: **quem chama ja tem a contagem
> de falhas por outra via** e monta um erro generico por linha.

E o docstring do módulo, dois parágrafos acima, diz:

> [a contagem de linhas] e diferente em cada API (`mutate_operation_responses` no mutate,
> `results` no upload, e **NADA no Customer Match**, cuja resposta so tem o
> `partial_failure_error`).

A justificativa foi escrita para **duas das três** leitoras. Para a terceira ela é falsa, e
o módulo documenta os dois fatos sem cruzá-los.

### 3.2 O gradiente de severidade, medido nas três leitoras

| leitora | como detecta falha | efeito de `medido=False` |
|---|---|---|
| **`customer_match.py:306`** | **só** por `erros_por_indice` — o comentário do código diz: *"A resposta deste RPC nao tem lista por-op: quem falhou so aparece pelo indice dentro do `partial_failure_error`"* | 🔴 **`membros_recusados` vazio ⇒ lote de PII hasheada reportado como 100% aceito** |
| `mutations.py:93` | `WhichOneof("response")` por op — independente do mapa de erros | 🟡 a contagem sobrevive; a mensagem vira `"Unknown partial failure"`, que **afirma ter lido e não leu** |
| `conversions.py:274` | heurística `result.conversion_action` falsy | 🟡 idem: `failed_count` sobrevive, as mensagens degradam |

A varredura tratou os três como um caso só. São dois níveis, e só um deles envolve PII.

### 3.3 F179 — `delete_invite` (HIGH, já catalogado)

`src/web/routes/admin_invites.py:113`, dentro do `async with conn.transaction()`:

```python
await managers_repo.delete_invite(conn, manager_id=parsed_invite_id)   # devolve bool, descartado
await _audit_admin(conn, admin=user, operation="admin_invite_cancel", email=email)
```

`delete_invite` deleta `WHERE status = 'invited'` e devolve `True` só quando afetou linha
(`src/db/repositories/managers.py:140`). Se o convidado logou entre o `SELECT` e o `DELETE`,
`status` já é `'active'`, o `DELETE` não afeta nada, e o `audit_log` afirma que um admin
cancelou um convite que virou conta ativa.

A transação do F174 tornou o par escrita+audit **atômico**, não **verdadeiro**: os dois
commitam juntos mesmo quando a escrita não teve efeito.

### 3.4 CSV do audit — falha aberto, nas duas rotas

`src/web/routes/admin_audit.py:123` e `src/web/routes/audit.py:117` têm o mesmo `stream()`,
e **nenhuma das duas tem `try/except`**:

```python
async def stream() -> AsyncIterator[bytes]:
    async with pool.acquire() as conn:
        async for line in audit_log.export_csv_rows(...):
            yield line.encode("utf-8")
```

`StreamingResponse` já emitiu `200 OK` e o `Content-Disposition` antes da primeira linha.
Exceção no meio do cursor (queda de conexão, erro de query, timeout do pool) corta o corpo:
o gestor recebe um **CSV sintaticamente válido e truncado**, indistinguível de um export que
simplesmente encontrou poucas linhas. Não há `Content-Length` a conferir — é streaming.

### 3.5 `filters_applied` — declara uma lista e aplica outra

Três tools publicam `filters_applied`. Medido, campo a campo, contra o `WHERE` de cada query:

| tool | declara | **corta e não declara** |
|---|---|---|
| `audit_zombie_keywords:134` | `ad_group_ids`, `limit` | `ad_group_criterion.status='ENABLED'`, `ad_group_criterion.negative=FALSE` |
| `audit_quality_score:153` | `ad_group_ids`, `min_impressions`, `limit` | `ad_group_criterion.status='ENABLED'`, `quality_info.quality_score IS NOT NULL` |
| `audit_orphan_smart_actions:155` | `category`, `limit` | `conversion_action.status='ENABLED'` |

**7 declarados, 5 escondidos**, e os três escondem o mesmo `ENABLED`. A varredura relatou
*"lista 3 e esconde 2"* — a contagem estava errada; é a terceira imprecisão de contagem
daqueles relatórios, e por isso cada item aqui foi remedido antes de virar trabalho.

O campo se chama `filters_applied`. Nomear alguns filtros faz a lista ler como **a** lista.
Um gestor que pergunta *"quais keywords estão desperdiçando?"* recebe uma resposta silenciosamente
escopada a keywords ativas e não-negativas — as pausadas com custo acumulado não aparecem, e
nada na resposta diz isso.

(O `quality_score IS NOT NULL` **está** documentado — na description de outra tool. Fato
certo, no lugar onde a decisão não é tomada: é o F187.)

### 3.6 `get_ad_schedule` — o gêmeo não consertado

`summarize_current` (`src/google_ads/ad_schedule.py:331`):

```python
if not current:
    return {"has_schedule": False, "windows": 0, "hours_per_week": 168.0}
```

`has_schedule: false` + `hours_per_week: 168` é uma **afirmação sobre entrega**: *esta
campanha serve 24x7.*

O F147 já viu isso e consertou — para **um** dos jeitos de a lista ficar vazia. O bloco em
`src/mcp/tools/get_ad_schedule.py:242` troca os três campos por `null` quando a grade caiu
além do corte do `limit`, e o comentário acima dele enumera o caso:

> `atual.get(cid, [])` acima nao distingue "campanha sem nenhuma janela" de "campanha com
> janelas que cairam alem do corte do `limit`".

**Existe um terceiro jeito, e ele não está na enumeração:** o parâmetro `status`, que filtra
os **critérios** e tem default `enabled`. A query recebe `status=status`. Pedir
`status: 'paused'` faz uma campanha cujas janelas estão todas ENABLED voltar com zero linhas
— e o resumo responde *"serve 24x7"* sobre uma campanha restrita.

É a forma mais frequente do defeito de 21/09: **o conserto pegou um dos gêmeos.** O F128
nasceu exatamente assim, e o comentário do F147 chega a citá-lo.

---

## 4. Desenho

### 4.1 O contrato

`erros_por_indice` deixa de devolver `dict[int, ErroDeLinha]` e passa a devolver:

```python
@dataclass(frozen=True, slots=True)
class LeituraDeFalhas:
    """O que se sabe sobre QUEM falhou num lote — e se dá para saber.

    `medido=False` não é "nenhuma falhou": é "não consegui ler quem falhou".
    Quem consome traduz isso para o vocabulário da sua superfície; o que não
    pode é ler `erros` vazio como ausência de falha.
    """
    erros: dict[int, ErroDeLinha]
    medido: bool
```

**É o tipo que faz o trabalho de forçar.** Todo call site hoje faz `.items()` sobre o
retorno; um dataclass sem `.items()` quebra os três **no mypy**, não em produção. Essa é a
razão de ser um dataclass e não `tuple[dict, bool]`: uma tupla é desempacotável por
descuido, e `erros, _ = ...` passaria batido numa revisão.

**Quando cada valor:**

| situação | resultado |
|---|---|
| sem `partial_failure_error`, ou `code == 0` | `LeituraDeFalhas({}, medido=True)` — vazio **medido**: nada falhou |
| `code != 0` e todos os details desempacotaram | `medido=True` |
| `code != 0` e algum `Unpack` devolveu `False` | `medido=False` |
| o `except Exception` disparou | `medido=False` |

A quarta linha muda o comportamento do `except` de "devolve o que acumulou, calado" para
"devolve o que acumulou, **dizendo que está incompleto**". O log que já existe continua.

### 4.2 As três leitoras

- **`customer_match`** — sob `medido=False`, `membros_recusados` vira `null` (não `[]`) e a
  resposta ganha `recusas_medidas: false`. A contagem de submetidos que hoje subtrai os
  recusados passa a `null` também: três campos que descrevem a mesma coisa desconhecida
  dizem desconhecido juntos — é a regra que o `get_ad_schedule` já aplica no bloco do F147,
  e a razão dela é a mesma (`null` ao lado de `0` lê como zero).
- **`mutations`** — a classificação por `WhichOneof` não muda (a contagem é medida). O que
  muda é a mensagem: sob `medido=False`, `error` da linha vira `None` em vez de
  `"Unknown partial failure"`, e o resultado carrega `motivos_medidos: false`. A string atual
  afirma que se leu o motivo e ele era desconhecido; a verdade é que não se leu.
- **`conversions`** — idem. `failed_count` continua vindo da heurística e continua medido.

### 4.3 F179

`delete_invite` já devolve `bool`. O retorno passa a ser lido, e sob `False`:

1. o audit grava `had_effect=false`;
2. o admin vê *"Esse convite já foi aceito — nada foi cancelado."*

Os dois, não um ou outro: (1) é a trilha, (2) é a UX, e o catálogo propunha cada um em
separado. Recusar antes do `DELETE` não é possível — só o resultado dele revela o caso.

**Migration `011_audit_log_had_effect.sql`**, moldada no precedente do F148
(`007_audit_log_dry_run.sql`), que decidiu exatamente esta forma e escreveu o porquê:

```sql
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS had_effect boolean;
COMMENT ON COLUMN audit_log.had_effect IS
  'true = a escrita afetou linha; false = passou sem efeito; NULL = nao medido ou anterior ao fix.';
```

Coluna **nullable** pelo mesmo motivo do `dry_run`: `NULL` não afirma nada sobre as linhas
anteriores ao fix. E **não** vira valor novo em `status` (`success|error|denied`), que é
filtro público de `get_my_audit_log` — mexer no enum quebra consumidor, que foi a razão
escrita na 007.

`_audit_admin` ganha `had_effect: bool | None = None`, repassado a `audit_log.record`. Os
demais chamadores não mudam e seguem gravando `NULL`.

### 4.4 CSV

O cliente não pode ser avisado depois do `200`. Então a completude tem de ser **provável
pelo arquivo**: as duas rotas passam a emitir uma **linha final sentinela** e só ela prova
que o export terminou.

- caminho feliz: última linha `# v4-ads-mcp: export completo, N linhas`
- exceção: `try/except` no gerador emite `# v4-ads-mcp: EXPORT INCOMPLETO apos N linhas — <motivo>` e relança para o log

A ausência da sentinela — queda de conexão, processo morto, qualquer coisa — lê como
incompleto. **Fail-closed por construção:** o arquivo só afirma completude quando ela
aconteceu.

O `#` inicial não é comentário CSV (CSV não tem comentários); é um marcador na primeira
coluna, e por isso a sentinela é uma linha CSV de uma coluna só, bem-formada. O painel que
oferece o download ganha uma nota dizendo o que procurar.

A troca considerada e recusada: bufferizar o export inteiro para poder falhar antes do
`200`. Recusada porque o `audit_log` é a tabela que mais cresce e o cursor server-side em
`export_csv_rows` existe justamente para não carregá-la na memória.

### 4.5 `filters_applied` — derivar, não listar

O construtor de cada query passa a devolver, junto do GAQL, **os filtros que aplicou**, e
`filters_applied` é montado a partir disso. Deixa de ser um dict escrito à mão ao lado da
query e passa a ser **derivado** dela — é o remédio que o F187 propõe, aplicado onde ele é
barato.

Isso fecha a classe em vez da instância: um filtro novo numa query futura aparece na
resposta sem ninguém lembrar de acrescentá-lo. Duplicar a lista à mão é o que produziu as
cinco omissões.

### 4.6 `get_ad_schedule`

`summarize_current` deixa de decidir a partir de uma lista vazia e passa a receber **por que**
ela está vazia. Vazio-por-filtro entra em `campanhas_com_grade_incerta` — a função que os
dois gêmeos do F147 já chamam, e cujo comentário avisa: *"separar as clausulas de novo e como
o F128 nasceu."* O terceiro caso entra **nela**, não num `if` paralelo.

Sob filtro não-default, `has_schedule`, `hours_per_week` e `windows` vão a `null`, com
`schedule_desconhecida_por_filtro: true` ao lado do irmão já existente.

**Nota de escopo:** `status='enabled'` é o default, então o caminho mais comum não muda.

### 4.7 O guard

Um guard AST sobre `fontes_py()` afirmando a **propriedade**: chamada a função cujo retorno
responde *"teve efeito?"* não pode ter o retorno descartado (`ast.Expr` envolvendo a call).

Alvos, resolvidos por `caminho_canonico` para sobreviver a alias de import: `erros_por_indice`,
`delete_invite`, e `.Unpack(`.

**Piso anti-vacuidade obrigatório:** `EscopoVazioError` do `_guard_harness`, com o piso
**derivado de medição** — nunca chutado. Uma varredura que para de casar tem de gritar, não
devolver zero ofensores. (Em 21/09 um piso chutado em 200 contra população medida de 161
disparou por engano; o piso certo vem de contar.)

O guard **enumera alvos, não arquivos** — a distinção que o F190 pagou caro para aprender: o
guard do F82 enumerava dois arquivos e o arquivo do bug não estava na lista.

### 4.8 Os mocks vêm primeiro

```python
def fake_unpack(target_pb: MagicMock) -> None:
    target_pb.errors = fake_errors
```

Devolve `None`. Assim que a produção ler o retorno, `None` é falsy e **todo teste de partial
failure entra no ramo "não medi"** — vermelho, sem que haja bug.

Medido: **6 arquivos** stubam `Unpack`. Dos que declaram `type_url`, **5 dizem `v20`** e 1
diz `v24`, com o SDK instalado em **google-ads 31.1.0**:

```
tests/integration/test_add_keywords.py                    v20
tests/integration/test_add_negatives_from_search_terms.py v20
tests/integration/test_apply_audience.py                  v20
tests/integration/test_remove_audience.py                 v20
tests/unit/test_mutations_partial_failure.py              v20
tests/unit/test_reporta_o_que_aconteceu.py                v24
```

Os testes rodam o cenário de divergência **e anulam o mecanismo que o detectaria**. É o modo
"o mock que bloqueia o conserto" — e a razão de ele ser a **Task 1**: o fake tem de ficar
fiel ao proto (`-> bool`) antes de qualquer mudança em produção, senão o vermelho dos testes
não distingue bug de mock.

O `type_url` v20 fica como está nesta task. Uniformizar versão é mudança de outro escopo, e
misturá-la aqui tornaria o vermelho ambíguo — que é exatamente o erro que esta task evita.

---

## 5. Testes

**O guard central sai VERMELHO contra o código de hoje**, verificado antes de qualquer
alteração de produção — por sabotagem ou cópia, **nunca `git checkout`**.

Contraprovas, uma por membro:

1. `LeituraDeFalhas` com `Unpack` devolvendo `False` ⇒ `medido=False` (e **não** `{}` mudo).
2. `code == 0` ⇒ `medido=True` com `erros` vazio — o **controle positivo**: sem ele o teste
   passaria com uma implementação que devolve `medido=False` sempre.
3. `customer_match` sob `medido=False` ⇒ `membros_recusados is None`, nunca `[]`.
4. `delete_invite` devolvendo `False` ⇒ `had_effect=false` no audit **e** mensagem ao admin.
5. Exceção no meio do cursor ⇒ CSV termina com a sentinela de incompleto; caminho feliz
   termina com a de completo.
6. `filters_applied` de cada uma das 3 tools contém **todo** filtro do `WHERE` daquela query
   — asserção derivada, que falha sozinha quando uma query ganhar filtro novo.
7. `get_ad_schedule` com `status='paused'` numa campanha de janelas ENABLED ⇒ `has_schedule is
   None`, **não** `false`.

O teste 2 existe porque asserir só o caminho de falha aceita uma implementação que nunca
afirma ter medido. Foi o que faltou no guard do F82.

---

## 6. Fora de escopo, nomeado

Cada item foi considerado e **deliberadamente deixado de fora**:

- **F154** — decisão do Wellington em 21/09. Mesma classe, outra forma; toca
  `jobs/meta_resync` e o painel admin, e provavelmente exige uma sonda real de alcance na
  Meta. **Spec próprio.**
- **Classe B (guards que não cobrem)** — `<style>` como elemento não coberto por nenhum
  guard (F178), guard de reconnect varrendo só `src/web/routes` e deixando o caminho de
  login fora, e o remédio geral do F187. O único pedaço de B que entra aqui é o dos mocks,
  porque **bloqueia** a Classe A.
- **Classe C** — `migrate.py` sem lock advisory. Não é a forma deste spec, e este spec
  adiciona uma migration, o que faz do lock um assunto **adjacente, não pré-requisito**:
  a 011 é `ADD COLUMN IF NOT EXISTS`, idempotente por construção.
- **~4 achados dos agentes ainda não recuperados.** Os 5 relatórios da varredura **não foram
  persistidos em disco** — a extração do transcript ficou pendente. O que está aqui foi
  **remedido direto no código**, o que é evidência mais forte que o relatório; o que não
  couber nisso continua não verificado e **não vira trabalho até ser**.
- **Uniformizar o `type_url` dos mocks para v24.** Ver 4.8.
- **F185, F186, F180** — decisão de 21/09: ficam como estão.

---

## 7. Critério de pronto

1. Guard central visto **vermelho** contra o código pré-fix, verde depois.
2. `python scripts/check_pre_push.py` 6/6, exit 0. **Full sweep obrigatório** (Docker) — há
   migration nova, e a regra do `CLAUDE.md` cobra o sweep completo nesse caso.
3. `erros_por_indice` sem nenhum call site lendo o retorno como dict — verificado por mypy
   strict, que é o mecanismo, não por grep.
4. Os 6 mocks devolvendo `bool`, com a suíte verde **antes** de a produção mudar.
5. Migration 011 aplicada pelo Cloud Run Job no deploy, coluna presente com o `COMMENT`.
6. As 3 tools com `filters_applied` derivado, e o teste 6 falhando se uma query ganhar
   filtro não declarado.
7. Entrada no `findings-catalog.md` com o que ficou de fora **escrito, não subentendido** —
   em especial que o gatilho de divergência de versão é **latente e não observado**.
