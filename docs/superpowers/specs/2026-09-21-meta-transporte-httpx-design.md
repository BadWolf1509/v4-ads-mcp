# Transporte Meta no httpx — design

**Data:** 2026-09-21
**Origem:** varredura ampla de 5 agentes paralelos sobre o repositório (2026-09-21),
sub-projeto 1 de 4. O achado que a motiva foi **verificado elo a elo** antes de virar
trabalho; os outros sub-projetos esperam verificação própria.
**Decisões do Wellington (2026-09-21):** abordagem B (consolidar no httpx) sobre A
(redigir na borda) e C (híbrido); **consertar para frente** — sem rotação de token e sem
expurgo do log, com o passado registrado como débito declarado.

---

## 1. O defeito, e por que ele não é "um bug de log"

O SDK `facebook_business` assa o token na **query string** de toda requisição.
`FacebookSession.__init__`, na fonte instalada:

```python
params = {'access_token': self.access_token}
if app_secret:
    params['appsecret_proof'] = self._gen_appsecret_proof()
self.requests.params.update(params)
```

Não há opt-out: `FacebookAdsApi.call` nunca remove esses params, e o argumento `headers=`
é aditivo.

`src/meta_ads/errors.py:63` é o fallback para tudo que não é `FacebookRequestError` — ou
seja, **toda falha de transporte** — e interpola a exceção crua:

```python
return MetaAdsFriendlyError(f"Erro inesperado: {e}", retryable=False)
```

O `str()` dessas exceções carrega a URL inteira. `src/meta_ads/reports.py:191` entrega essa
string a `audit_log.record(error_message=...)`.

**Um soluço de rede no Cloud Run manda o token para três destinos ao mesmo tempo:** coluna
`TEXT` do Postgres, Cloud Logging, e o envelope de erro da tool — que vai para o contexto
do LLM e para a transcrição do chat. É o token **que não expira** e alcança ~24 contas de
anúncio. Quem lê qualquer um dos três contorna `can_manager_access`, a matriz que a
documentação chama de *o único freio* do Modelo B.

### Por que passou

A invariante já estava escrita no repo, em `src/meta_ads/graph.py:36`:

> `# F82 — token no HEADER, nunca na query: quem lê a URL num log contorna tudo.`

**O F82 foi fechado numa das duas implementações de chamada Meta e não na outra** — e a
outra é a que as cinco tools de performance usam. `tests/unit/test_meta_secret_leak.py`
assere a invariante exclusivamente contra `src/auth/meta_oauth.py` e `graph.py`, os dois
caminhos httpx. O caminho do SDK nunca entrou no escopo do guard.

É o terceiro caso do mesmo padrão **no mesmo dia**: F189 (paginação certa ao lado da
errada), F161 (fechado num caminho do `ad_schedule` e não no que produz o resumo), e este.
O `CLAUDE.md` já nomeia a classe no F57. A regra existe; o mecanismo que a aplica, não.

---

## 2. Escopo, medido

| | |
|---|---|
| Arquivos que usam o SDK | **2** — `src/meta_ads/client.py` (monta) e `src/meta_ads/reports.py` (uma call site) |
| Caminhos Meta já em httpx | **3** — `graph.py`, `partnership.py`, `auth/meta_oauth.py` |
| Mutações Meta (`POST`) | **0** — a superfície Meta inteira é leitura |
| `appsecret_proof` referenciado em `src/` | **0** — é injeção do SDK; nada nosso depende dele |

A consolidação não é refatoração: é **trocar o transporte de uma função**. Foi essa medição
que decidiu B sobre A — eu havia assumido custo alto sem medir.

---

## 3. Desenho

### 3.1 Transporte

`run_meta_graph_get` troca `api.call` por `httpx`, seguindo o padrão de
`graph.py::fetch_paginated`: `Authorization: Bearer <token>` no header, `timeout`
explícito, status conferido antes de qualquer leitura de corpo.

**Consequência não-óbvia, e é ganho:** o SDK usa `requests` (síncrono), por isso a chamada
hoje é offloadada com `run_blocking`. Com httpx async ela vira um `await` de verdade. O
risco de esgotar o pool de threads do `anyio` — **compartilhado com os cinco executores
Google** — deixa de existir por construção, em vez de ser mitigado por um timeout. A
ausência de timeout era achado próprio da varredura; ele é absorvido aqui.

O cliente é construído com timeout explícito, espelhando `auth/meta_oauth.py:256`
(`httpx.AsyncClient(timeout=30.0)`).

### 3.2 Tratamento de erro

1. **Nunca interpolar `str(e)` cru.** A redação vive **dentro de
   `errors.py::to_friendly_meta_error`**, não nos call sites: é o único ponto por onde
   toda exceção Meta já passa antes de virar mensagem, então nenhum chamador futuro
   precisa lembrar de aplicá-la. Mecanismo no lugar de disciplina — a regra que o
   `CLAUDE.md` chama de "processo humano é dívida com juros".

   Com header auth o token já não entra na URL; a redação é **defesa em profundidade**.
   Uma camada só é a que falha, e este finding é a prova: a invariante existia escrita e
   mesmo assim o vazamento ficou aberto num dos dois caminhos.
2. **Status real.** Não-200 vira erro nomeado com `retryable` correto: 5xx e timeout
   retryable, 4xx não. Hoje um 502 de intermediário chega ao gestor como
   `'str' object has no attribute 'get'` e **marcado como permanente**, porque
   `FacebookResponse.json()` devolve o corpo cru quando ele não é JSON e `is_success()`
   cai num teste de substring.
3. **Validar a forma na borda:** `isinstance(body, dict)` com o status HTTP no texto, no
   lugar de `cast(dict, ...)` — que satisfaz o mypy e não existe em tempo de execução.
4. **Amarrar o gate à URL.** O hard-gate roda contra o kwarg `ad_account_id`; a requisição
   vai para `edge`; nada liga os dois. O F72 tornou o kwarg **obrigatório**, não
   **autoritativo sobre a URL**. Entra aqui porque a função está sendo reescrita, custa
   duas linhas e um teste, e sem isso uma tool futura cujo edge seja `/{campaign_id}/...`
   gatearia a conta A e leria a conta B.

### 3.3 BUC e rate counter

`response.headers()` (método, no SDK) passa a `resp.headers` (mapping, no httpx). A parsing
de `x-business-use-case-usage` não muda.

### 3.4 Testes — guard antes do fix

O guard central aciona uma **falha de transporte com token-sentinela** e assere que o
sentinela não aparece em **nenhum dos três sinks**:

- a mensagem do `MetaAdsFriendlyError`,
- os kwargs de `audit_log.record`,
- o evento de `structlog`.

Asserir só a mensagem não basta — a escrita de auditoria é sink separado, e foi exatamente
por cobrir um lado só que o F82 ficou meio fechado. **O guard tem de sair VERMELHO contra o
código de hoje**, verificado antes de qualquer alteração de produção.

Mais três:

- o cliente httpx é construído **com** timeout (falha contra `timeout=None`);
- corpo não-JSON levanta erro nomeado, não `AttributeError`;
- `edge` divergente do `ad_account_id` gateado levanta, em vez de seguir.

**`test_meta_secret_leak.py` tem o escopo ampliado para ser estrutural**, cobrindo todo
caminho que fala com a Graph API em vez de dois arquivos nomeados. Enquanto ele enumerar
arquivos, um transporte novo escapa de novo — é o modo "enumerar em vez de afirmar a
propriedade" que a varredura encontrou em outros guards do repo.

O guard do F189 (`test_meta_paginacao_usa_url_completa.py`) tem de continuar verde sobre o
transporte novo. Se ficar vermelho, a paginação regrediu.

### 3.5 Verificação em produção

Depois do deploy, na conta `act_4051924171730156` (17 anúncios), a probe de fronteira do
F189: `limit: 16` devolve 16 linhas e `truncated: true`; `limit: 17`, 17 linhas e
`truncated: false`. Mais uma leitura Meta ponta a ponta em outra conta.

Se o app exigir `appsecret_proof`, é aqui que aparece — como 4xx. A evidência contrária já
existe e é empírica, não suposição: **`graph.py` chama a Graph API com header auth, sem
`appsecret_proof`, e roda em produção** no caminho de reconciliação.

---

## 4. Fora de escopo, nomeado

Cada item abaixo foi considerado e **deliberadamente deixado de fora**, com motivo:

- **Rotação do token e expurgo do `audit_log`.** Decisão do Wellington em 21/09: consertar
  para frente. **Débito declarado:** não foi medido se o token já vazou para o log. A
  contagem que responderia é um `COUNT(*)` em `audit_log` por `error_message` contendo o
  nome do parâmetro de token, e ela **não foi executada**. Fica registrado aqui para que
  "ninguém mediu" não vire "nunca aconteceu".
- **Unificar as duas paginações num código só.** `fetch_paginated` serve o caminho de
  reconciliação; mudar seu contrato para carregar headers e o `paging` da última página
  arriscaria algo que funciona em troca de elegância. **A gemelaridade de segurança morre
  aqui** — as duas passam a autenticar por header. A duplicação estrutural fica como débito.
- **`_parse_buc_header_pct` devolvendo `0` em três caminhos de "desconhecido".** É da
  família "afirma mais do que mediu" e pertence ao sub-projeto 2. Misturar tornaria o PR
  não-revisável.
- **`spend_brl`/`cpc_brl` fixos num inventário multi-moeda**, divergência de `ctr` entre
  tools, taxonomia de `actions`, janelas de atribuição. Todos do sub-projeto 2, e todos
  **ainda não verificados** — passam por verificação antes de virar código.

---

## 5. Critério de pronto

1. O guard dos três sinks visto **vermelho** contra o código pré-fix, verde depois.
2. `python scripts/check_pre_push.py` 6/6, exit 0.
3. Nenhuma ocorrência de `api.call` no caminho de request. **`build_meta_api` é removido**
   junto com seus testes (`test_meta_client.py`), porque depois desta mudança ele fica com
   zero consumidores — código morto com teste verde é pior que código morto. **`client.py`
   permanece:** ele também exporta `MetaAccessDeniedError` (usado por `src/mcp/server.py`)
   e `META_GRAPH_API_VERSION`, que o `partnership.py` já usa e que o transporte novo vai
   precisar para montar a URL.
4. O guard do F189 verde sobre o transporte novo.
5. Probe de fronteira em produção reproduzindo 16/17 com `truncated` correto.
6. Entrada no `findings-catalog.md` com o débito da seção 4 escrito, não subentendido.
