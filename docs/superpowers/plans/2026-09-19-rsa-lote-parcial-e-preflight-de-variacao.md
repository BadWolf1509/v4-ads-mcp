# Lote parcial em RSA + pre-flight de variação de experimento — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `update_rsa` e `create_rsa` param de perder o lote inteiro por causa de uma linha recusada (F180), e o pre-flight do `update_rsa` passa a recusar anúncio system-managed com uma mensagem que diz o que fazer em vez de deixar o dry-run prometer o impossível (F181).

**Architecture:** Nada de mecanismo novo. O `partial_failure` já existe, é genérico e está ligado em 6 operações — as duas tools de RSA só não optaram por ele, e optar é uma linha de payload mais o custo declarado (o lote deixa de ser atômico). A detecção de variação é **um campo a mais na GAQL que o pre-flight já roda**, sem round-trip novo; só a mensagem que nomeia o anúncio base custa uma query extra, e ela só acontece no caminho de falha.

**Tech Stack:** Python 3.13 · `google-ads` v24 (proto-plus) · GAQL · pytest + testcontainers · ruff + mypy strict.

**Spec:** [`findings-catalog.md`](../../operacao/findings-catalog.md) — **F180** (lote atômico, erro sem a linha culpada), **F181** (pre-flight cego a `system_managed_resource_source`). Evidência de campo: `D:\Gestor de Tráfego de Ads\mcp-v4-ads-backlog-melhorias.md`, itens B1 e B2, medidos em 19/09/2026 na conta MO-JP `7862230676`.

**Fora de escopo, deliberadamente:**
- **F182** (a descrição do `apply_change` promete `partial_failures` pras 22 operações e vale pra 6) — o fix tem duas opções com custos diferentes e a decisão é do Wellington. Este plano conserta o `update_rsa`, e a frase continua falsa para as outras 15 tools. Está escrito assim no F182 de propósito.
- **F183** (dois mutates de lote sem teto) — família dos tetos, não desta correção.
- **Subir o teto de lote de 5** (item M2 do backlog) — depende da Task 1, mas é sprint separado: mexer no teto e na atomicidade no mesmo commit tira a capacidade de atribuir uma regressão a um dos dois.
- **Nomear o experimento** na mensagem de recusa. Custaria uma 3ª query e **não é confiável**: medido em 19/09, `experiment_arm` não expõe os anúncios que materializa, então ligar uma variação a um experimento específico só seria correto quando houvesse exatamente um experimento `AD_VARIATION` `ENABLED` na conta. Preferimos nomear o **anúncio base** (Task 3), que é verificável.
- **Tool `get_experiments`** (item G1 do backlog) — gap real, sprint próprio.

## Global Constraints

- **Gate antes de todo commit:** `python scripts/check_pre_push.py` rodado **mudo**, lendo `$?`. **Nunca** pipe entre o gate e o `&&` — `check_pre_push.py | tail && git commit` não é gate e já deixou passar commit vermelho.
- **Full sweep OBRIGATÓRIO neste sprint:** `python scripts/check_pre_push_full.py` (Docker). O `CLAUDE.md` nomeia "pré-flight de mutate" como um dos três casos em que o sweep completo não é opcional — e este plano mexe exatamente nisso. Se o Docker não subir (serviço `com.docker.service` `Stopped` exige elevação), o CI é o validador e o fix é forward, confirmando por `gh run view <id> --json conclusion` — **nunca** pelo exit code de `gh run watch`.
- **Todo teste deste plano tem que falhar contra o código PRÉ-fix.** Verifique por sabotagem ou cópia — **nunca `git checkout`**, que descarta trabalho não commitado. Um teste que passa antes e depois não é guard.
- **Enum proto-plus compara-se por VALOR, nunca por presença de atributo** (F145): em proto-plus o atributo existe sempre. `hasattr(...)` e `is not None` passam tudo.
- **Envelope de erro vem do `_mutate_common`** (`error_envelope`), nunca montado à mão.
- **Id numérico em cláusula `IN` do GAQL** usa coerção `int()`, como o pre-flight já faz (`", ".join(str(int(x)) for x in ids)`). **Não** use `gaql_in_list` aqui — ele emite strings entre aspas, e é para valor textual (F87/F163).
- **Mensagens de erro desta função são ASCII sem acento**, acompanhando as quatro que já existem ali ("nao encontrado", "Nao e possivel atualizar"). Não introduza acento em metade das mensagens da mesma função.
- **Mover função exige `grep` de todos os patch-sites em `tests/`** — mock target em namespace antigo dá `AttributeError` só no CI com Docker.
- **Commits:** `fix(mcp): …`, com o trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File Structure

| Arquivo | Responsabilidade nesta mudança |
|---|---|
| `src/mcp/tools/update_rsa.py` | payload ganha `__partial_failure__`; description passa a dizer que o lote é parcial e que variação é recusada |
| `src/mcp/tools/create_rsa.py` | payload ganha `__partial_failure__`; description idem (só a parte do lote) |
| `src/google_ads/queries/_common.py` | `_format` do pre-flight sai de função aninhada para módulo (fica testável); a query ganha o campo; a rejeição entra na ordem certa; a busca do anúncio base entra como helper do caminho de falha |
| `tests/integration/test_update_rsa.py` | guard de propriedade do F180 (o que chega em `run_mutation`) + conserto do comentário que codifica o comportamento antigo |
| `tests/integration/test_create_rsa.py` | mesmo guard para `create_rsa` |
| `tests/unit/test_validate_existing_rsas.py` | rejeição de variação, ordem das rejeições, e leitura do campo sob row proto-like |
| `docs/operacao/phase-rsa-f180-f181-bootstrap.md` | runbook de smoke (Task 5) |

---

### Task 1: F180 — as duas tools de RSA pedem aplicação parcial ao Google

**Files:**
- Modify: `src/mcp/tools/update_rsa.py:157-161` (payload) e `:110-120` (description)
- Modify: `src/mcp/tools/create_rsa.py:142-146` (payload) e a description
- Test: `tests/integration/test_update_rsa.py`, `tests/integration/test_create_rsa.py`

**Interfaces:**
- Consumes: `run_mutation(..., partial_failure: bool)` de `src/google_ads/mutations.py` — já existe desde `f156d99`, nada a criar.
- Produces: nada que tarefas seguintes consumam. A Task 2 é independente desta.

- [ ] **Step 1: Escreva o teste que falha (guard de propriedade, não de chave)**

Em `tests/integration/test_update_rsa.py`, ao lado do teste de ciclo completo:

```python
@pytest.mark.integration
async def test_update_rsa_pede_partial_failure_ao_google(db, session_ctx) -> None:
    """F180: o lote deixa de ser atomico — `run_mutation` recebe partial_failure=True.

    Guard de PROPRIEDADE, nao de chave. Assertar `"__partial_failure__" in payload`
    passaria mesmo se `apply_change` parasse de repassar a flag — o que importa e o
    que chega em `run_mutation`, que e quem fala com o Google.
    """
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.update_rsa import update_rsa

    capturado: dict[str, object] = {}

    async def fake_run_mutation(**kwargs: object) -> dict[str, object]:
        capturado.update(kwargs)
        return {
            "provider_request_id": "req-f180",
            "applied_count": 1,
            "changed_count": 1,
            "partial_failures": [],
            "resource_names": ["customers/1234567890/ads/100"],
        }

    with (
        patch(
            "src.mcp.tools.update_rsa.validate_existing_rsas_for_update",
            AsyncMock(return_value=None),
        ),
        patch("src.mcp.tools.apply_change.run_mutation", fake_run_mutation),
    ):
        dry_run = await update_rsa(
            {
                "customer_id": "1234567890",
                "updates": [{"ad_id": "100", "final_urls": ["https://exemplo.com.br"]}],
            }
        )
        await apply_change({"confirmation_token": dry_run["confirmation_token"]})

    assert capturado["partial_failure"] is True
```

E o gêmeo em `tests/integration/test_create_rsa.py`, com o payload de create:

```python
@pytest.mark.integration
async def test_create_rsa_pede_partial_failure_ao_google(db, session_ctx) -> None:
    """F180: gemeo do guard do update_rsa, no caminho de criacao."""
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.create_rsa import create_rsa

    capturado: dict[str, object] = {}

    async def fake_run_mutation(**kwargs: object) -> dict[str, object]:
        capturado.update(kwargs)
        return {
            "provider_request_id": "req-f180-create",
            "applied_count": 1,
            "changed_count": 1,
            "partial_failures": [],
            "resource_names": ["customers/1234567890/adGroupAds/1~100"],
        }

    with (
        patch(
            "src.mcp.tools.create_rsa.validate_parent_ad_groups_for_rsa_create",
            AsyncMock(return_value=None),
        ),
        patch("src.mcp.tools.apply_change.run_mutation", fake_run_mutation),
    ):
        dry_run = await create_rsa(
            {
                "customer_id": "1234567890",
                "rsas": [
                    {
                        "ad_group_id": "1",
                        "headlines": ["Um titulo", "Outro titulo", "Terceiro"],
                        "descriptions": ["Uma descricao aqui", "Outra descricao aqui"],
                        "final_urls": ["https://exemplo.com.br"],
                    }
                ],
            }
        )
        await apply_change({"confirmation_token": dry_run["confirmation_token"]})

    assert capturado["partial_failure"] is True
```

> Os dois patch targets foram conferidos em 19/09: `create_rsa.py:17-18` importa `validate_parent_ad_groups_for_rsa_create` do `_common`, então o alvo é o nome **no namespace do módulo da tool** (`src.mcp.tools.create_rsa.…`), nunca no `_common` — é a convenção de pre-flight pós-3b.8, e patchar o `_common` deixa o teste verde sem exercitar nada.

- [ ] **Step 2: Rode e confirme que falha**

```bash
python -m pytest tests/integration/test_update_rsa.py::test_update_rsa_pede_partial_failure_ao_google tests/integration/test_create_rsa.py::test_create_rsa_pede_partial_failure_ao_google -v
```

Esperado: **FAIL** — `assert False is True`, porque `apply_change.py:439` lê `__partial_failure__` ausente e passa `partial_failure=False`.

- [ ] **Step 3: Implemente — uma chave em cada payload**

`src/mcp/tools/update_rsa.py`:

```python
    payload = {
        "updates": updates,
        "__target_count__": target_count,
        "__params_summary__": params_summary,
        # F180: o lote deixa de ser atomico. Um ad_id que o Google recusa (variacao
        # de experimento, anuncio removido entre o preview e o apply) para de levar
        # junto os outros — `apply_change` devolve `partial_failures` com o motivo
        # por linha e `failed_count`. O custo e real e esta assumido: nao ha
        # invariante que o lote de RSA preserve (anuncios sao independentes), entao
        # aplicar parte e melhor que perder tudo. Ver F180 no catalogo.
        "__partial_failure__": True,
    }
```

`src/mcp/tools/create_rsa.py`, mesma chave e mesmo comentário reduzido a uma linha (`# F180: lote parcial — ver update_rsa.py e o F180 no catalogo.`):

```python
    payload = {
        "rsas": rsas,
        "__target_count__": target_count,
        "__params_summary__": params_summary,
        # F180: lote parcial — ver update_rsa.py e o F180 no catalogo.
        "__partial_failure__": True,
    }
```

- [ ] **Step 4: Rode e confirme que passa**

```bash
python -m pytest tests/integration/test_update_rsa.py tests/integration/test_create_rsa.py -v
```

Esperado: **PASS**, inclusive os testes que já existiam.

- [ ] **Step 5: Conserte o comentário que codifica o comportamento antigo**

`tests/integration/test_update_rsa.py`, dentro de `_client_with_ad_response`, existe hoje:

```python
    # update_rsa does NOT use partial_failure — always all-or-nothing.
    response.partial_failure_error.code = 0
    response.partial_failure_error.details = []
```

A primeira linha vira falsa com a Task 1. Troque por:

```python
    # F180: update_rsa passou a pedir partial_failure. Este mock representa o caso
    # em que o Google aceitou TUDO (code=0, sem details) — que e o caminho feliz
    # exercitado aqui. O caso de recusa por linha tem teste proprio.
    response.partial_failure_error.code = 0
    response.partial_failure_error.details = []
```

- [ ] **Step 6: Atualize as duas descriptions**

Em `update_rsa`, acrescente ao fim da description (antes da frase sobre re-aprovação):

```
"Lote PARCIAL: se o Google recusar um ad_id, os demais sao aplicados e o "
"apply_change devolve partial_failures com o motivo por linha. "
```

Em `create_rsa`, a mesma frase trocando `ad_id` por `anuncio`.

- [ ] **Step 7: Gate + commit**

```bash
python scripts/check_pre_push_full.py
```

Leia o `$?`. Verde:

```bash
git add src/mcp/tools/update_rsa.py src/mcp/tools/create_rsa.py tests/integration/test_update_rsa.py tests/integration/test_create_rsa.py
git commit -m "fix(mcp): F180 — lote de RSA aplica o que o Google aceita em vez de perder tudo"
```

---

### Task 2: F181 — o pre-flight enxerga anúncio system-managed e recusa com mensagem acionável

**Files:**
- Modify: `src/google_ads/queries/_common.py:461-542` (`validate_existing_rsas_for_update`)
- Modify: `src/mcp/tools/update_rsa.py` — a description lista o que o pre-flight rejeita e a lista fica incompleta
- Test: `tests/unit/test_validate_existing_rsas.py`

**Interfaces:**
- Consumes: nada da Task 1 — as duas tarefas são independentes e podem ser revisadas em separado.
- Produces: `_format_rsa_preflight_row(row) -> dict[str, str]` no nível do módulo `src/google_ads/queries/_common.py` (era função aninhada `_format`), com a chave nova `system_managed_source`. A Task 3 estende esta mesma função e o dicionário.

- [ ] **Step 1: Escreva os testes que falham**

Em `tests/unit/test_validate_existing_rsas.py`:

```python
@pytest.mark.asyncio
async def test_rejeita_variacao_de_ad_variation(monkeypatch) -> None:
    """F181: anuncio system-managed passa em todos os outros filtros e tem que cair aqui.

    A variacao E um RESPONSIVE_SEARCH_AD, num ad_group ENABLED, numa campanha
    SEARCH — por isso ela atravessava o pre-flight inteiro.
    """

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_id": "825281476311",
                "ad_type": "RESPONSIVE_SEARCH_AD",
                "system_managed_source": "AD_VARIATIONS",
                "ad_group_id": "204135195030",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "21359547724",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "825281476311", "final_urls": ["https://exemplo.com.br"]}],
    )
    assert result is not None
    assert "825281476311" in result
    assert "variacao" in result.lower()
    # A mensagem tem que dizer O QUE FAZER, nao so que deu errado.
    assert "base" in result.lower()


@pytest.mark.asyncio
async def test_ad_normal_nao_e_confundido_com_variacao(monkeypatch) -> None:
    """Controle: sem o campo (anuncio comum) o pre-flight continua passando.

    Sem este teste, um predicado que rejeitasse TUDO passaria no teste anterior.
    """

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "ad_id": "825140457725",
                "ad_type": "RESPONSIVE_SEARCH_AD",
                "system_managed_source": "UNSPECIFIED",
                "ad_group_id": "204135195030",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "21359547724",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "825140457725", "path1": "abc"}],
    )
    assert result is None


@pytest.mark.asyncio
async def test_query_do_preflight_pede_o_campo_de_system_managed(monkeypatch) -> None:
    """A rejeicao so funciona se o SELECT trouxer o campo. Guard da query, nao do parser."""
    capturado: dict[str, str] = {}

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        capturado["query"] = kwargs["query"]
        return []

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "100", "path1": "abc"}],
    )
    assert "ad_group_ad.ad.system_managed_resource_source" in capturado["query"]


def test_formatter_le_o_campo_pelo_caminho_certo_do_proto() -> None:
    """O formatter le `.name` do enum, nao o enum cru.

    ATENCAO ao que este teste NAO prova: que o caminho do proto existe no SDK.
    Isso foi provado empiricamente em 19/09 via `run_gaql` na MO-JP (ver F181),
    que e a unica prova possivel de superficie de API externa. Aqui provamos so
    que o formatter le `.name` e nao o objeto enum.
    """
    from types import SimpleNamespace

    from src.google_ads.queries._common import _format_rsa_preflight_row

    row = SimpleNamespace(
        ad_group_ad=SimpleNamespace(
            ad=SimpleNamespace(
                id=825281476311,
                type=SimpleNamespace(name="RESPONSIVE_SEARCH_AD"),
                system_managed_resource_source=SimpleNamespace(name="AD_VARIATIONS"),
            )
        ),
        ad_group=SimpleNamespace(
            id=204135195030, name="AG1", status=SimpleNamespace(name="ENABLED")
        ),
        campaign=SimpleNamespace(
            id=21359547724,
            name="C1",
            advertising_channel_type=SimpleNamespace(name="SEARCH"),
        ),
    )
    assert _format_rsa_preflight_row(row)["system_managed_source"] == "AD_VARIATIONS"
```

- [ ] **Step 2: Rode e confirme que falham**

```bash
python -m pytest tests/unit/test_validate_existing_rsas.py -v
```

Esperado: `test_rejeita_variacao_de_ad_variation` **FAIL** (devolve `None`), `test_query_do_preflight_pede_o_campo_de_system_managed` **FAIL** (campo ausente do SELECT), `test_formatter_le_o_campo...` **FAIL** com `ImportError` (a função ainda é aninhada). O controle já passa — e tem que passar antes e depois; ele existe para provar que a rejeição discrimina.

- [ ] **Step 3: Tire o `_format` de dentro da função**

Antes de `validate_existing_rsas_for_update`, no nível do módulo `src/google_ads/queries/_common.py`:

```python
def _format_rsa_preflight_row(row: Any) -> dict[str, str]:
    """Uma linha de `ad_group_ad` -> dict do pre-flight de RSA.

    Nivel de modulo (nao aninhada) pra ser testavel com row proto-like: o
    caminho `.system_managed_resource_source.name` e o que separa variacao de
    anuncio comum, e caminho de proto so se confere olhando.
    """
    return {
        "ad_id": str(row.ad_group_ad.ad.id),
        "ad_type": row.ad_group_ad.ad.type.name,
        # F181: em proto-plus este atributo EXISTE SEMPRE — o que varia e o valor
        # (UNSPECIFIED no anuncio comum, AD_VARIATIONS na variacao). Por isso a
        # comparacao la embaixo e por valor, nunca por presenca (F145).
        "system_managed_source": row.ad_group_ad.ad.system_managed_resource_source.name,
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "ad_group_status": row.ad_group.status.name,
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
        "channel_type": row.campaign.advertising_channel_type.name,
    }
```

Remova o `def _format(...)` aninhado e troque `row_formatter=_format` por `row_formatter=_format_rsa_preflight_row`.

> Antes de rodar: `grep -rn "_format" tests/ | grep -i rsa` — se algum teste referenciava o nome antigo por patch, o alvo mudou.

- [ ] **Step 4: Acrescente o campo ao SELECT**

Na query da mesma função, logo após `ad_group_ad.ad.type`:

```python
    query = (
        f"SELECT ad_group_ad.ad.id, ad_group_ad.ad.type, "
        f"ad_group_ad.ad.system_managed_resource_source, "
        f"ad_group.id, ad_group.name, ad_group.status, "
        f"campaign.id, campaign.name, campaign.advertising_channel_type "
        f"FROM ad_group_ad WHERE ad_group_ad.ad.id IN ({ids_clause})"
    )
```

Custo: **zero round-trip novo** — é a mesma query que já rodava.

- [ ] **Step 5: Acrescente a rejeição, logo depois de "ad nao encontrado"**

No laço `for u in updates:`, entre o `if ad is None:` e o `if ad["ad_type"] != ...`:

```python
        # F181: variacao de Ad Variation e RESPONSIVE_SEARCH_AD, fica em ad_group
        # ENABLED e em campanha SEARCH — atravessa os tres filtros seguintes. So
        # este campo a separa do anuncio base. Comparacao por VALOR: em proto-plus
        # o atributo existe sempre (F145).
        if ad["system_managed_source"] == "AD_VARIATIONS":
            return (
                f"Ad {aid} e uma variacao de Ad Variation (gerenciada pelo Google) "
                f"e nao aceita mutate. Edite o anuncio BASE do mesmo ad_group "
                f"('{ad['ad_group_name']}', id {ad['ad_group_id']}) — a variacao "
                f"herda a mudanca em minutos. Atencao: reler a variacao logo apos "
                f"editar o base devolve o estado ANTIGO sem erro nenhum."
            )
```

A ordem importa: mais específico primeiro. Um `ad is None` continua ganhando, porque sem linha não há campo a ler.

- [ ] **Step 6: Rode e confirme que passam**

```bash
python -m pytest tests/unit/test_validate_existing_rsas.py -v
```

Esperado: **todos PASS**, inclusive os quatro que já existiam.

- [ ] **Step 7: Atualize a description do `update_rsa`**

A frase atual — *"Pre-flight rejeita ad inexistente, type != RESPONSIVE_SEARCH_AD, ad_group REMOVED, ou campaign non-SEARCH"* — fica incompleta. Passa a:

```
"Pre-flight rejeita ad inexistente, type != RESPONSIVE_SEARCH_AD, ad_group "
"REMOVED, campaign non-SEARCH, ou anuncio que e variacao de Ad Variation "
"(gerenciado pelo Google — edite o anuncio base). "
```

- [ ] **Step 8: Gate + commit**

```bash
python scripts/check_pre_push_full.py
```

Verde:

```bash
git add src/google_ads/queries/_common.py src/mcp/tools/update_rsa.py tests/unit/test_validate_existing_rsas.py
git commit -m "fix(mcp): F181 — pre-flight de RSA recusa variacao de experimento com mensagem acionavel"
```

---

### Task 3: A mensagem nomeia o anúncio base

**Files:**
- Modify: `src/google_ads/queries/_common.py` (helper novo + uso na mensagem da Task 2)
- Test: `tests/unit/test_validate_existing_rsas.py`

**Interfaces:**
- Consumes: `_format_rsa_preflight_row` e a rejeição da Task 2 — **esta tarefa não pode ser executada antes dela**.
- Produces: `_buscar_ad_base_do_grupo(manager_id, session_id, customer_id, ad_group_id) -> str | None` — devolve o `ad_id` do único RSA não-variação do grupo, ou `None` quando há zero ou mais de um (ambíguo).

> **Por que é tarefa separada:** ela acrescenta uma query. Um revisor pode aceitar a Task 2 (recusa correta, mensagem genérica) e rejeitar esta (custo extra), e o resultado continua coerente.

- [ ] **Step 1: Escreva os testes que falham**

```python
@pytest.mark.asyncio
async def test_mensagem_nomeia_o_ad_base_quando_ele_e_unico(monkeypatch) -> None:
    """F181: a mensagem que teria poupado a investigacao nomeia o anuncio a editar."""
    chamadas: list[str] = []

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        chamadas.append(kwargs["query"])
        if len(chamadas) == 1:
            return [
                {
                    "ad_id": "825281476311",
                    "ad_type": "RESPONSIVE_SEARCH_AD",
                    "system_managed_source": "AD_VARIATIONS",
                    "ad_group_id": "204135195030",
                    "ad_group_name": "AG1",
                    "ad_group_status": "ENABLED",
                    "campaign_id": "21359547724",
                    "campaign_name": "C1",
                    "channel_type": "SEARCH",
                }
            ]
        return [
            {"ad_id": "825140457725", "system_managed_source": "UNSPECIFIED"},
            {"ad_id": "825281476311", "system_managed_source": "AD_VARIATIONS"},
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "825281476311", "final_urls": ["https://exemplo.com.br"]}],
    )
    assert result is not None
    assert "825140457725" in result
    # A 2a query so acontece no caminho de falha.
    assert len(chamadas) == 2


@pytest.mark.asyncio
async def test_sem_base_unico_a_mensagem_nao_inventa_id(monkeypatch) -> None:
    """Dois nao-variacao no grupo: a mensagem cai pro generico em vez de chutar.

    Este e o teste que impede a correcao de virar afirmacao falsa: nomear o
    anuncio errado e pior que nao nomear nenhum.
    """

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        if "system_managed_resource_source" in kwargs["query"] and "ad_group.id =" in kwargs["query"]:
            return [
                {"ad_id": "111", "system_managed_source": "UNSPECIFIED"},
                {"ad_id": "222", "system_managed_source": "UNSPECIFIED"},
                {"ad_id": "825281476311", "system_managed_source": "AD_VARIATIONS"},
            ]
        return [
            {
                "ad_id": "825281476311",
                "ad_type": "RESPONSIVE_SEARCH_AD",
                "system_managed_source": "AD_VARIATIONS",
                "ad_group_id": "204135195030",
                "ad_group_name": "AG1",
                "ad_group_status": "ENABLED",
                "campaign_id": "21359547724",
                "campaign_name": "C1",
                "channel_type": "SEARCH",
            }
        ]

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    result = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=[{"ad_id": "825281476311", "final_urls": ["https://exemplo.com.br"]}],
    )
    assert result is not None
    assert "111" not in result
    assert "222" not in result
    assert "base" in result.lower()
```

- [ ] **Step 2: Rode e confirme que falham**

```bash
python -m pytest tests/unit/test_validate_existing_rsas.py -k "base" -v
```

Esperado: **FAIL** — a mensagem da Task 2 não nomeia id nenhum e só uma query é feita.

- [ ] **Step 3: Implemente o helper**

```python
async def _buscar_ad_base_do_grupo(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    ad_group_id: str,
) -> str | None:
    """`ad_id` do unico RSA nao-variacao do grupo, ou None se ambiguo.

    So roda no caminho de falha do pre-flight (anuncio system-managed detectado),
    entao o custo nao entra no caminho feliz. Devolve None — em vez de chutar o
    primeiro — quando ha zero ou mais de um candidato: nomear o anuncio errado e
    pior que nao nomear nenhum.
    """
    query = (
        f"SELECT ad_group_ad.ad.id, "
        f"ad_group_ad.ad.system_managed_resource_source "
        f"FROM ad_group_ad "
        f"WHERE ad_group.id = {int(ad_group_id)} "
        f"AND ad_group_ad.status != 'REMOVED'"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "ad_id": str(row.ad_group_ad.ad.id),
            "system_managed_source": row.ad_group_ad.ad.system_managed_resource_source.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="buscar_ad_base_do_grupo",
    )
    candidatos = [r["ad_id"] for r in rows if r["system_managed_source"] != "AD_VARIATIONS"]
    return candidatos[0] if len(candidatos) == 1 else None
```

- [ ] **Step 4: Use o helper na mensagem da Task 2**

Substitua o bloco de rejeição por:

```python
        if ad["system_managed_source"] == "AD_VARIATIONS":
            base_id = await _buscar_ad_base_do_grupo(
                manager_id=manager_id,
                session_id=session_id,
                customer_id=customer_id,
                ad_group_id=ad["ad_group_id"],
            )
            alvo = (
                f"o anuncio BASE {base_id}"
                if base_id is not None
                else f"o anuncio BASE do ad_group '{ad['ad_group_name']}' (id {ad['ad_group_id']}) — o RSA que nao e variacao"
            )
            return (
                f"Ad {aid} e uma variacao de Ad Variation (gerenciada pelo Google) "
                f"e nao aceita mutate. Edite {alvo}: a variacao herda a mudanca em "
                f"minutos. Atencao: reler a variacao logo apos editar o base "
                f"devolve o estado ANTIGO sem erro nenhum."
            )
```

- [ ] **Step 5: Rode e confirme que passam**

```bash
python -m pytest tests/unit/test_validate_existing_rsas.py -v
```

Esperado: **todos PASS**.

- [ ] **Step 6: Gate + commit**

```bash
python scripts/check_pre_push_full.py
```

Verde:

```bash
git add src/google_ads/queries/_common.py tests/unit/test_validate_existing_rsas.py
git commit -m "fix(mcp): F181 — a recusa de variacao nomeia o anuncio base a editar"
```

---

### Task 4: Smoke em conta real — o passo que não pode ficar pendente

**Files:**
- Create: `docs/operacao/phase-rsa-f180-f181-bootstrap.md`

> 🔴 **Este sprint muda o comportamento de uma tool MUTANTE.** O `CLAUDE.md` é explícito em dois pontos que se cruzam aqui: *"Don't fechar sprint de tool mutante com o APPLY em ⬜ pending"* (foi assim que F150 e F151 chegaram à produção, depois de três revisões) e *"Don't agendar smoke de tool que muta sem o gestor presente"* — o classificador de auto mode recusa a chamada, e **aval relayado por outra sessão não passa**. Nem dry-run nem conta de teste isentam: medido em 04/09, os dois foram recusados identicamente e só passaram após o Wellington autorizar com as próprias palavras.

- [ ] **Step 1: Escreva o runbook com os casos abaixo**

| # | Cenário | Como | Esperado |
|---|---|---|---|
| T1 | Variação recusada no pre-flight | `update_rsa` com o `ad_id` de uma variação viva | Erro nomeando a variação e o anúncio base, **sem token emitido** |
| T2 | Anúncio comum continua passando | `update_rsa` num RSA normal, dry-run | Token emitido, preview correto |
| T3 | Lote misto aplica o que dá | 2 RSAs válidos + 1 variação no mesmo lote | **Deve ser barrado no T1** — se chegar ao apply, o pre-flight falhou |
| T4 | Lote parcial de verdade (F180) | 2 RSAs válidos onde um é removido na UI entre o preview e o apply | `applied_count: 1`, `failed_count: 1`, `partial_failures` com o motivo da linha |
| T5 | Caminho feliz ponta a ponta | 2 RSAs válidos, apply | `applied_count: 2`, `failed_count: 0`, os dois mudados por GAQL |

T4 é o que prova o F180 em produção, e é o único que precisa de coordenação manual (remover na UI entre as duas chamadas). Sem ele, o sprint fecha afirmando aplicação parcial sem nunca ter visto uma.

- [ ] **Step 2: Rode o smoke com o Wellington na sessão**

Conta sugerida: MO-JP `7862230676`, que é onde o F180/F181 foram medidos e onde a variação existe (experimento `10061636855`, ativo até 2026-11-14).

- [ ] **Step 3: Registre o resultado no runbook e commite**

```bash
git add docs/operacao/phase-rsa-f180-f181-bootstrap.md
git commit -m "docs(operacao): smoke do F180+F181 em conta real"
```

---

### Task 5: Fechar os findings

**Files:**
- Modify: `docs/operacao/findings-catalog.md` (F180, F181)
- Modify: `CLAUDE.md` (a linha de findings abertos)
- Modify: `docs/operacao/estado-atual.md`

- [ ] **Step 1: Marque F180 e F181 como CORRIGIDO**

Troque `(MEDIUM, ABERTO)` por `(MEDIUM, CORRIGIDO em 2026-MM-DD)` nos dois títulos e acrescente a cada um o bloco **✅ CORRIGIDO** no padrão da casa: o que foi feito, **e o que ficou deliberadamente de fora**. Para o F180, o que fica de fora é o F182 (a descrição do `apply_change` segue falsa pras outras 15 tools) e o índice da operação em `errors.py`, que continua descartado. Para o F181, ficam de fora o nome do experimento e a tool `get_experiments` (G1).

- [ ] **Step 2: Atualize a linha de abertos no `CLAUDE.md`**

A linha que hoje diz que F180–F183 estão abertos passa a citar só **F182 e F183**.

- [ ] **Step 3: Atualize o `estado-atual.md`** com o sprint e a data do smoke.

- [ ] **Step 4: Commit**

```bash
git add docs/operacao/findings-catalog.md CLAUDE.md docs/operacao/estado-atual.md
git commit -m "docs(operacao): fecha F180 e F181"
```

---

## Self-review

**Cobertura da spec.** F180 → Task 1 (flag nas duas tools, guard de propriedade). F181 detecção → Task 2. F181 mensagem acionável → Task 3. Prova em produção → Task 4. Fecho → Task 5. F182 e F183 estão declarados fora de escopo com motivo, não esquecidos.

**Placeholders.** Nenhum passo diz "adicione tratamento de erro" ou "escreva testes para o acima" — todo passo de código traz o código.

**Consistência de tipos.** `_format_rsa_preflight_row` é criada na Task 2 e usada com o mesmo nome na Task 3. A chave `system_managed_source` é a mesma nos dois formatters e em todos os `fake_run_report`. `_buscar_ad_base_do_grupo` devolve `str | None` e o call-site trata o `None` explicitamente.

**Ordem.** Task 1 é independente. Task 3 depende da Task 2. Task 4 depende de 1 e 2. Tasks 1 e 2 podem ir a implementers paralelos — tocam arquivos disjuntos (`update_rsa.py`/`create_rsa.py` e payload vs `_common.py`), exceto pela description do `update_rsa.py`, que as duas editam. **Se paralelizar, a description do `update_rsa` fica na Task 2 e sai da Task 1** — ou serialize as duas.
