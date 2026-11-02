# Sonda Meta da Onda 1 (01/11/2026)

Graph v25, token do system user, só GET. Script: `scripts/probe_meta_onda1.py`. Conta: conta interna.
Uma chamada de prévia saiu na segunda conta (de cliente),
fora do aval de "uma conta interna": usou um criativo da conta interna, e só a forma foi registrada.

## O que mudou o desenho

1. **Na edge de coleção, campo inexistente NÃO dá erro.** `fields=id,campo_que_nao_existe_v4` em
   `/{act}/campaigns` devolve 200 sem o campo. No objeto (`/{id}?fields=...`) o mesmo campo dá
   `(#100) Tried accessing nonexisting field` em campanha, conjunto e anúncio. Logo, 200 na edge não
   valida campo, e a validação foi feita campo a campo no objeto. `metadata=1` devolveu lista vazia.
   No objeto de criativo o campo inválido não deu erro, então ali a validação é fraca: vale a
   presença da chave, medida em `adcreatives`.
2. **`/{act}/generatepreviews` aceita criativo de outra conta.** Com o criativo da conta A, a edge
   da conta B devolveu 200 com prévia. O amarramento do F190 não protege aqui: sem prova de posse,
   um gestor veria criativo de conta sem grant. A Task 4 presumia o contrário.
3. **`activities` sem `since` e `until` devolve vazio, sem erro.** `time_range` também é ignorado e
   devolve vazio. Com `since`/`until` veio dado, e `paging.next` funciona.
4. **`lifetime_budget: "0"` significa "não tem".** Conjunto com orçamento diário traz vitalício `"0"`.
   Campanha sem orçamento próprio omite `daily_budget` e traz `budget_remaining: "0"`. Orçamento é
   string em centavos (`"1000"` = R$ 10,00, a conferir no Gerenciador no smoke).
5. **`filtering` por `id` em `adcreatives` não é suportado** (`(#100) ... operation 'in' is not
   supported`). `filtering` por `effective_status` em `campaigns` funciona.

## Uma linha por edge

| Edge | Resultado | Observação |
|---|---|---|
| `/{act}/campaigns` | 200, 1 linha | Todos os campos válidos no objeto |
| `/{act}/adsets` | 200, 1 linha | Idem, inclusive `learning_stage_info`, `promoted_object`, `targeting` |
| `/{act}/ads` | 200, 1 linha | `creative{id}`, `ad_review_feedback`, `issues_info` válidos |
| `/{act}/activities` | 200, 25 linhas com período | Todos os valores são string; `extra_data` é JSON em string; `application_name` às vezes falta |
| `/{act}/adcreatives` | 200, 5 linhas | `title`, `body`, `image_url` e `call_to_action_type` podem faltar |
| `/{act}/generatepreviews` | 200 | `data[0].body` é `<iframe ...>` com `src` em `business.facebook.com`; `ad_format` inválido lista os valores aceitos |
| `/{act}/customaudiences` | 200, 0 linhas | **Forma não medida** |
| `/{act}/delivery_estimate` | 200, 1 linha | Inteiros `estimate_mau_lower_bound`, `estimate_mau_upper_bound`, `estimate_dau`, bool `estimate_ready`, lista `daily_outcomes_curve`; JSON inválido dá 400 |
| `/{act}/reachestimate` | 200, vazio | Não serve; a tool usa só `delivery_estimate` |
| `/{act}/targetingsearch` | 200, 4 linhas | `id`, `name`, `type`, `path`, `audience_size_lower_bound/upper_bound`, `description` opcional; sem `q` dá 400 |
| `/{act}/promote_pages` | 200, 1 linha | `id`, `name`, `instagram_business_account{id}`, `connected_instagram_account{id}`: **a Task 8 fica** |
| `/{act}/instagram_accounts`, `connected_instagram_accounts` | 200, vazio | Sem uso |
| `/{act}/adspixels` | 200, 0 linhas | **Forma, stats e qualidade não medidos** |

Em `activities`, `object_type` usa os nomes antigos: `CAMPAIGN_GROUP` = campanha, `CAMPAIGN` =
conjunto, `ADGROUP` = anúncio, `ACCOUNT` = conta.

## O que o smoke real e a medição de `until` provaram (02/11/2026)

- `activities`: `since` e `until` valem por data UTC, não pelo fuso da conta. A base é um evento só.
- `until` é exclusivo: com um evento de 23/10, `since=22/10 until=23/10` trouxe 0 linhas e
  `since=23/10 until=24/10` trouxe 4. `since` é inclusivo.
- `until` no futuro é aceito sem erro em +1 dia. **+2 dias, que é o que a tool envia, não foi medido.**
- `targetingsearch`: o conjunto muda conforme `limit`. Com um termo só, `limit` 72 trouxe 54 linhas e
  100 trouxe 72, sem `paging.next`, então a ausência de próxima página não prova lista completa.
- `delivery_estimate`: `estimate_dau` saiu 0 em 4 estimativas válidas com alcance mensal positivo. O
  valor cru não foi medido.

## Não medido

- `customaudiences` e `adspixels` com linhas: a conta interna devolveu 0 linhas, sem distinguir ausência de falta de acesso.
- A segunda conta (autorizada pelo Wellington, somente GET) também devolveu 0 linhas em
  `customaudiences` e `adspixels`. Isso não distingue ausência de falta de acesso (o token pode não enxergar), então as duas
  tools (`meta_get_custom_audiences`, `meta_get_signal_health`) saíram da onda, conforme a spec.
- `ads_get_field_context`: o MCP oficial da Meta não está nesta sessão, então não rodou.
