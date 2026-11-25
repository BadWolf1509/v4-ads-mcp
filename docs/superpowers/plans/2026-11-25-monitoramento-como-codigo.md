# Monitoramento como código — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Versionar no repositório os 9 recursos de monitoramento e aplicá-los a qualquer projeto com um comando idempotente que só cria o que falta.

**Architecture:**
- Modelos JSON com marcadores em `scripts/infra/monitoramento_defs/`.
- Módulo `scripts/infra/monitoramento.py` com três camadas:
  - funções puras: carregar, renderizar e comparar;
  - um laço de plano/aplicação sobre uma API injetável;
  - um `main` com cliente REST real.
- O bootstrap imprime o comando pronto.

**Tech Stack:** Python 3.13, `urllib.request`, pytest. Nenhuma dependência nova.

**Spec:** `docs/superpowers/specs/2026-11-25-monitoramento-como-codigo-design.md`

## Global Constraints

- **Dry-run por padrão:** sem `--apply` não há nenhum POST.
- **Nunca** PATCH nem DELETE. Recurso `diferente` sai com código 1.
- **Identidade de cada recurso:**
  - canal: `type` e `labels.email_address`;
  - uptime check: `displayName`;
  - métrica: `name`;
  - policy: `displayName`.
- **Ordem:** canal → uptime → métricas → policies.
- **Marcadores:** `{PROJECT}`, `{HOST}`, `{CHANNEL}`, `{CHECK_ID}`.
- **`gcloud`:**
  - resolvido por `shutil.which`, com `timeout=60` e sem stderr mudo;
  - `x-goog-user-project: <projeto>` em toda chamada;
  - token de `gcloud auth print-access-token`.
- **O que nunca entra no POST:** os campos de saída (`name` de policy ou condição, `creationRecord`, `mutationRecord`). `notificationRateLimit` só pode aparecer em policy `conditionMatchedLog`.
- **Ruling 1 (desvio do spec):** o diretório de modelos é `monitoramento_defs/`, não `monitoramento/`. Um diretório `monitoramento/` colidiria com o módulo `monitoramento.py` no import.
- **Ruling 2 (desvio do spec):**
  - **Problema:** chamar o aplicador no `--apply` do bootstrap criaria o uptime check antes de o serviço existir. O alerta de uptime dispararia no primeiro minuto de um projeto novo.
  - **Decisão:** o bootstrap **imprime o comando exato**, com o host determinístico `v4-ads-mcp-<número>.<região>.run.app`, para rodar depois do primeiro deploy.
  - **Custo, se estiver errado:** um passo manual a mais, que fica registrado na saída do bootstrap.

## Review Focus

1. **Policy de uptime:** a policy referencia o check pelo ID, que só existe depois de criado. No dry-run de projeto vazio isso não pode quebrar: a policy aparece como `criar`. Teste na Task 2.
2. **Campos que o servidor acrescenta** (`verificationStatus`, `selectedRegions`, `name` de condição): não podem virar `diferente`. A comparação é por subconjunto. Teste na Task 1.
3. **Listas na comparação:** a lista do modelo deve casar elemento a elemento com a do servidor, e tamanhos diferentes contam como `diferente`. Teste na Task 1.
4. **Marcador sobrando** depois de renderizar, por erro de digitação no JSON: deve falhar alto, não gerar POST com `{CHANNEL}` literal. Teste na Task 1.
5. **Resposta da API paginada ou sem a chave da lista** (projeto sem nenhuma policy): deve ser tratada como lista vazia. Teste na Task 2.

---

### Task 1: Modelos versionados e funções puras

**Files:**
- Create:
  - `scripts/infra/monitoramento_defs/canal.json`
  - `scripts/infra/monitoramento_defs/uptime.json`
  - `scripts/infra/monitoramento_defs/metricas.json` (lista de 2)
  - `scripts/infra/monitoramento_defs/policies.json` (lista de 5)
  - `scripts/infra/monitoramento.py`
- Test: `tests/unit/test_monitoramento.py`

**Interfaces — Produces:**
- `DEFS: Path`
- `carregar_modelos(defs: Path = DEFS) -> dict[str, list[dict[str, Any]]]`
  - chaves `"canal"`, `"uptime"`, `"metricas"`, `"policies"`, sempre listas.
- `renderizar(obj: Any, valores: Mapping[str, str]) -> Any`
  - troca `{CHAVE}` em toda string, recursivamente;
  - se sobrar um `{MAIUSCULAS}`, levanta `ValueError` citando qual.
- `contem(modelo: Any, real: Any) -> bool`
  - dict: cada chave do modelo existe no real e `contem` recursivo;
  - lista: mesmo tamanho e `contem` elemento a elemento;
  - escalar: igualdade.

**Como gerar os modelos:**
- Fonte: os exports de 25/11 em `scratchpad/old_*.json`, ou um GET do `fluxo-certo-ads`, que já tem o texto com "no inventario".
- Retire os campos de saída.
- Troque os valores concretos pelos marcadores:
  - projeto → `{PROJECT}`;
  - host → `{HOST}`;
  - canal → `{CHANNEL}`;
  - ID do check → `{CHECK_ID}`;
  - `email_address` → `{EMAIL}`.
- Ruling 3: `{EMAIL}` também é marcador.
- **Fonte de verdade = o estado vivo do `fluxo-certo-ads`**, para o aceite dar `igual`.

- [ ] **Step 1: Write the failing tests**

```python
VALORES = {"PROJECT": "proj-x", "HOST": "h.run.app", "CHANNEL": "projects/proj-x/notificationChannels/1",
           "CHECK_ID": "chk-1", "EMAIL": "a@b.c"}

def test_modelos_tem_os_9_recursos():
    m = carregar_modelos()
    assert [len(m[k]) for k in ("canal", "uptime", "metricas", "policies")] == [1, 1, 2, 5]

def test_renderizados_sem_marcador_nem_projeto_antigo():
    texto = json.dumps(renderizar(carregar_modelos(), VALORES))
    assert "{" + "PROJECT}" not in texto and "v4-ads-mcp-299432068772" not in texto
    assert "projects/v4-ads-mcp/" not in texto and "IWQz5PfF6KU" not in texto

def test_modelos_sem_campos_de_saida():
    texto = json.dumps(carregar_modelos())
    assert '"creationRecord"' not in texto and '"mutationRecord"' not in texto

def test_marcador_sobrando_levanta():
    with pytest.raises(ValueError, match="CHANNEL"):
        renderizar({"x": "{CHANNEL}"}, {})

def test_contem_ignora_campos_extras_do_servidor():
    assert contem({"a": 1, "l": [{"b": 2}]}, {"a": 1, "z": 9, "l": [{"b": 2, "name": "n"}]})

def test_contem_detecta_valor_e_tamanho_de_lista_diferentes():
    assert not contem({"a": 1}, {"a": 2})
    assert not contem({"l": [1, 2]}, {"l": [1]})
    assert not contem({"a": 1}, {})
```

- [ ] **Step 2: Run, expect FAIL (ImportError)**

`.venv/Scripts/python.exe -m pytest tests/unit/test_monitoramento.py -q`

- [ ] **Step 3: Generate the 4 JSON files and implement `carregar_modelos`, `renderizar`, `contem`**

- [ ] **Step 4: Run, expect PASS**

- [ ] **Step 5: Commit** — `feat(ci): definições de monitoramento versionadas com marcadores`

---

### Task 2: Plano e aplicação sobre API injetável

**Files:**
- Modify: `scripts/infra/monitoramento.py`
- Test: `tests/unit/test_monitoramento.py`

**Interfaces — Consumes:** Task 1.

**Interfaces — Produces:**
- `class Api(Protocol)`:
  - `listar(recurso: str) -> list[dict]`
  - `criar(recurso: str, corpo: dict) -> dict`
  - `recurso` ∈ `{"notificationChannels", "uptimeCheckConfigs", "metrics", "alertPolicies"}`.
- `Linha = NamedTuple(tipo: str, chave: str, acao: str)`
  - `acao` ∈ `{"criar", "criado", "igual", "diferente"}`.
- `aplicar(api: Api, *, project_id: str, host: str, alert_email: str, apply: bool) -> list[Linha]`
  - resolve `CHANNEL` e `CHECK_ID` do recurso existente ou recém-criado;
  - no dry-run, sem o recurso, usa o sentinela `"<a criar>"`.
- `codigo_de_saida(linhas: list[Linha]) -> int`: 1 se houver algum `diferente`, senão 0.

**Fake para os testes:** `FakeApi` em memória. `criar` grava o corpo acrescido de `name` e de um campo extra (`"verificationStatus": "X"` no canal; `name` em cada condição), imitando o servidor.

- [ ] **Step 1: Write the failing tests**

```python
def test_projeto_vazio_dry_run_planeja_9_criar_e_nao_posta():
    api = FakeApi()
    linhas = aplicar(api, project_id="p", host="h", alert_email="e@x", apply=False)
    assert [l.acao for l in linhas] == ["criar"] * 9 and api.posts == []

def test_apply_cria_9_e_segunda_rodada_e_toda_igual():
    api = FakeApi()
    assert [l.acao for l in aplicar(api, project_id="p", host="h", alert_email="e@x", apply=True)] == ["criado"] * 9
    assert [l.acao for l in aplicar(api, project_id="p", host="h", alert_email="e@x", apply=True)] == ["igual"] * 9
    assert len(api.posts) == 9

def test_policy_de_uptime_referencia_o_check_criado():
    api = FakeApi(); aplicar(api, project_id="p", host="h", alert_email="e@x", apply=True)
    check = api.dados["uptimeCheckConfigs"][0]["name"].rsplit("/", 1)[1]
    up = next(p for p in api.dados["alertPolicies"] if p["displayName"].startswith("Uptime"))
    assert check in up["conditions"][0]["conditionThreshold"]["filter"]

def test_diferente_nao_e_tocado_e_sai_1():
    api = FakeApi(); aplicar(api, project_id="p", host="h", alert_email="e@x", apply=True)
    api.dados["alertPolicies"][0]["enabled"] = False
    linhas = aplicar(api, project_id="p", host="h", alert_email="e@x", apply=True)
    assert [l.acao for l in linhas].count("diferente") == 1 and len(api.posts) == 9
    assert codigo_de_saida(linhas) == 1

def test_lista_ausente_na_resposta_e_vazia():
    # FakeApi(sem_chave=True) faz `listar` devolver [] quando o recurso não existe; a lógica não exige chave
    ...
```

Ruling 4: o último caso fica na Task 3, no cliente real. Ali `listar` lê `.get(<chave>, [])` e segue `nextPageToken`. Na Task 2 a interface já devolve uma lista.

- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement `Api`, `Linha`, `aplicar`, `codigo_de_saida`**
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** — `feat(ci): aplicador de monitoramento só cria o que falta`

---

### Task 3: Cliente REST, CLI, bootstrap e aceite real

**Files:**
- Modify:
  - `scripts/infra/monitoramento.py`
  - `scripts/infra/bootstrap_projeto.py`
  - `docs/operacao/infra-setup.md`
  - `docs/operacao/estado-atual.md`
- Test:
  - `tests/unit/test_monitoramento.py`
  - `tests/unit/test_bootstrap_projeto.py`

**Interfaces — Produces:**
- `class RestApi(project_id: str, token: str)` implementando `Api`:
  - Monitoring v3 para canal, uptime e policies;
  - Logging v2 para métricas;
  - `listar` segue `nextPageToken` e trata a chave ausente como `[]`.
- `main(argv: list[str] | None = None) -> int`
  - argumentos: `--project-id`, `--host`, `--alert-email` e `--apply`;
  - imprime uma linha por recurso (`acao  tipo  chave`);
  - devolve `codigo_de_saida`.
- `comando_monitoramento(*, project_id: str, project_number: str, region: str, alert_email: str) -> str`
  - fica no bootstrap;
  - host = `f"v4-ads-mcp-{project_number}.{region}.run.app"`.

- [ ] **Step 1: Write failing tests**
  - `test_rest_listar_segue_paginacao_e_chave_ausente`: com `urlopen` mockado, a 1ª página traz `nextPageToken`, a 2ª vem sem a chave e o resultado concatena.
  - `test_main_dry_run_nao_posta`: `RestApi` mockada, rc 0 e nenhum POST.
  - `test_bootstrap_imprime_comando_de_monitoramento`: verifica que o comando contém `--host v4-ads-mcp-505452482961.southamerica-east1.run.app` e que **não** contém `--apply`.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement**
  - O bootstrap troca o lembrete "canal de e-mail … 5 policies (runbook REST)" pelo `comando_monitoramento`, com a nota "rode depois do primeiro deploy (o uptime check precisa do serviço no ar)".
  - Docs: `infra-setup.md` aponta o comando como o jeito de recriar. A pendência sai do `estado-atual.md`.
- [ ] **Step 4: Run, expect PASS; then full gate** — `scripts/check_pre_push.py` (exit 0).
- [ ] **Step 5: Aceite real**
  - Comando: `python -m scripts.infra.monitoramento --project-id fluxo-certo-ads --host v4-ads-mcp-505452482961.southamerica-east1.run.app --alert-email wellington.ribeiro.eng@gmail.com`.
  - Esperado: 9 linhas `igual`, rc 0.
  - Qualquer `diferente` volta para os modelos da Task 1: o estado vivo é a fonte.
- [ ] **Step 6: Commit** — `feat(ci): bootstrap aponta o aplicador de monitoramento`
