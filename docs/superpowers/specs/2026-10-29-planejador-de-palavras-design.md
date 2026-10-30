# Planejador de palavras-chave (Google) — design

**Data:** 2026-10-29. **Aprovado por:** Wellington, em 29/10.

**Origem:** análise de 28/10 (necessidade e viabilidade) e brainstorming de 29/10. Quando a equipe
monta a estrutura de uma **conta nova**, as palavras saem do briefing e do conhecimento do modelo,
sem volume nem CPC reais. A skill `estrutura-campanha-google-ads` gera lista sem dado do Google, e o
`add_keywords` já existe do outro lado.

## 1. Fatos medidos (premissas do desenho)

Sondagem só de leitura em 29/10: script local com o OAuth do Wellington, conta **Conta Interna - 02
(`6728568947`)**, `KeywordPlanIdeaService` do SDK instalado (a chamada saiu em `v25`).

1. **O developer token tem acesso ao serviço.** `generate_keyword_ideas` e
   `generate_keyword_historical_metrics` responderam, em 0,5 a 4 s por chamada.
2. **O volume vem em degraus do Google, não exato.** Valores distintos observados: 10, 20, 30, 40, 50,
   70, 90, 110, 170, 210, 260, 390, 480, 880, 1600, 4400, 8100. É o mesmo arredondamento do
   Planejador na interface.
3. **Só com termos-semente** (`keyword_seed`), "aluguel de andaime" + "locação de equipamentos"
   devolveram **1.923 ideias**. **Com uma URL junto** (`keyword_and_url_seed`), **40**: a combinação
   estreita a busca. **Só a URL** (`url_seed`, mestredaobra.com.br) deu **964 ideias** (JP e Brasil),
   **sem "aluguel de andaime"**, e as primeiras são de **financiamento imobiliário**: a URL puxa o
   conteúdo da página, não o negócio (medido na sonda versionada da Task 1, 29/10). Por isso cada ideia
   diz a origem, para o gestor ou a skill filtrarem as que vieram do site.
4. **O recorte por cidade funciona e muda muito o número.** Mesmo termo: 8.100 no Brasil
   (`geoTargetConstants/2076`), 40 em João Pessoa. A lista de ideias para as mesmas sementes teve o
   mesmo tamanho (1.923) nos dois recortes.
5. **A busca de cidade por nome devolve homônimos.** `suggest_geo_target_constants` para
   "João Pessoa" (locale `pt`, país `BR`) trouxe primeiro `1001622` (João Pessoa, **City**, Paraíba),
   depois um **Neighborhood** em Santa Catarina, o estado da Paraíba, outro estado, CEPs e Santa Rita.
   O nome sem acento ("Joao Pessoa") devolve o mesmo. "Campina Grande" trouxe também
   "Campina Grande do Sul" (PR) e "Campinas" (SP).
6. **"Sem dado" é distinguível de zero.** Termo inexistente no `generate_keyword_historical_metrics`
   volta **sem** o bloco `keyword_metrics` (presença falsa); o lido com `"x" in proto` separa os
   casos. Lido como valor, sem presença, sairia `vol=0`, `competition=UNSPECIFIED`, `bid=0`.
7. **CPC vem como faixa de topo de página** (`low_top_of_page_bid_micros`,
   `high_top_of_page_bid_micros`), em micros da moeda da conta-base. Exemplo: "aluguel de andaime" no
   Brasil, R$ 3,00 a R$ 12,50. Cada ideia traz 12 meses de `monthly_search_volumes`.
8. **A sondagem usou o caminho de produção:** o script montou o cliente com `build_client` e os
   **mesmos secrets do serviço** (`google-ads-developer-token`, `google-ads-login-customer-id` = MCC
   `6436352492`, client id/secret do OAuth), só lendo o refresh token do banco em vez do executor. A
   Conta Interna - 02 é filha desse MCC (`list_my_accounts` a lista com `mcc_id: 6436352492`).
9. **A conta usada na chamada não muda o resultado.** As mesmas sementes em João Pessoa, na Conta
   Interna - 02 e na conta de cliente MDO JP (`7862230676`): as mesmas 1.923 ideias, com volume e
   faixa de CPC idênticos em todos os termos (29/10).
   **Ajuste do smoke de 30/10:** termos, ordem e volumes iguais; o CPC variou em centavos em 28 de 689
   ideias entre duas chamadas — variação do Google entre chamadas, não da conta.
10. **Várias cidades numa chamada dão um volume que não fecha com nenhuma delas.** "aluguel de
    andaime": João Pessoa 40, Campina Grande 20, as duas numa chamada **50** (não 60). O degrau é
    aplicado depois da soma.
11. **Não medido:** o limite de requisições do serviço (uma chamada não mede teto) e o comportamento com
   várias cidades na mesma chamada.

## 2. Para que serve, e para quem

- **Momento principal:** estrutura de conta nova (decisão do Wellington). Entradas que o gestor tem:
  **site do cliente, termos-semente, cidade(s) e sites de concorrentes** (todas, decisão do Wellington).
- **Quem usa:** **o gestor direto no chat e a skill de estrutura** (decisão do Wellington). A resposta
  precisa ser estruturada o bastante para a skill montar grupos e correspondências.
- **O que faria a lista ser descartada** (decisão do Wellington): volume em faixa apresentado como
  exato; termos fora do negócio ou de outra cidade; CPC irreal; lista gigante sem ordem útil.

## 3. Escopo

| Item | O quê |
|---|---|
| `plan_keyword_ideas` | Ideias a partir de sementes, site do cliente e sites de concorrentes, recortadas por cidade(s), com volume, concorrência, faixa de CPC e sazonalidade compacta. |
| `get_keyword_metrics` | Volume, concorrência, faixa de CPC e sazonalidade de uma lista pronta (a da skill ou a do cliente), no mesmo recorte. |

Nomes finais com o builder. O catálogo passa de 70 para **72 tools**. As duas são só leitura.

**Fora de escopo:**
- **Previsão de orçamento** (`generate_keyword_forecast_metrics`, cliques e custo para um
  investimento). Decisão do Wellington: próxima frente. Exige campanha hipotética na requisição.
- **Agrupamento por tema** (minha decisão). O `generate_ad_group_themes` distribui palavras entre
  grupos de anúncio **existentes**; numa conta nova não há nenhum. Quem agrupa é a skill, com a lista.
- **Marcar termos que já estão na conta** (minha decisão). Na conta nova a base é a interna da V4.
  Volta junto do uso "expandir conta existente".

## 4. Desenho

### 4.1 Conta-base

Decisão do Wellington (29/10, confirmada pelo fato 9): **a busca roda numa conta que o gestor já
alcança**, a do cliente ou a interna da V4. `customer_id` é **obrigatório** e passa pelo
`ensure_account_access` como qualquer conta, **sem exceção no gate e sem default**. A description diz
que o resultado não depende da conta escolhida (fato 9), para o gestor de conta nova usar qualquer conta
dele. A Conta Interna - 02 (`6728568947`) aparece na description só como exemplo.

### 4.2 Recorte geográfico

Decisão do Wellington: **cidade(s) por nome**.

- Entrada: lista de nomes (`cidades`), com estado opcional por item (ex.: `"João Pessoa, PB"`).
- Resolução por `suggest_geo_target_constants` (locale `pt`, país `BR`). Fica o primeiro com
  `target_type == "City"`; com estado informado, o primeiro City **daquele estado** (`canonical_name`).
- Nome sem City correspondente → erro claro com os candidatos encontrados. **Nunca cair em bairro, CEP
  ou estado em silêncio** (fato 5).
- A resposta ecoa a resolução: nome pedido → `geo_target_constant`, nome canônico e tipo.
- Sem cidade → **Brasil inteiro** (`2076`), dito na resposta.
- **Várias cidades → volume por cidade** (decisão do Wellington; fato 10 mostra que a soma numa chamada
  não fecha). Uma chamada por cidade por origem. Cada ideia traz `volume_por_cidade`
  (`{cidade_resolvida: volume | null}`) e a ordem usa o **maior** volume entre as cidades. Não há soma
  entre cidades na resposta: somar degraus não dá o degrau da soma.
- Teto de cidades por pedido (minha decisão): **5**, para a quota não explodir (cidades × origens
  chamadas).
- Idioma fixo em português (`languageConstants/1014`); rede `GOOGLE_SEARCH`.

### 4.3 `plan_keyword_ideas`

Entradas: `sementes` (lista de termos), `site` (URL do cliente), `concorrentes` (lista de URLs),
`cidades`, `customer_id` (obrigatório, 4.1), `limit` (default 200, teto 1000). Pelo menos uma entre `sementes`,
`site` e `concorrentes`. Com uma cidade (ou nenhuma), `volume_mensal` é o número dela; com várias,
vale `volume_por_cidade` (4.2), e as métricas de CPC e concorrência vêm por cidade também.

**Chamadas separadas por origem (minha decisão, fato 3):** uma chamada só com as sementes
(`keyword_seed`), uma por URL (`url_seed`: o site e cada concorrente). Os resultados são unidos por
texto normalizado. Cada ideia traz `origens` (`semente`, `site`, `concorrente:<domínio>`), e a soma
é única por termo. Juntar sementes e URL numa chamada derruba a lista para 40.

Por ideia:
- `termo`
- `volume_mensal`: o número do Google; **`null` se o bloco de métricas não veio**
- `concorrencia` (`LOW`/`MEDIUM`/`HIGH`, `null` sem dado) e `indice_concorrencia`
- `cpc_topo_min_brl` / `cpc_topo_max_brl` (`null` sem dado)
- `sazonalidade`: `{mes_pico, mes_vale, variacao_12m_pct}` calculada dos 12 meses (minha decisão:
  resumo em vez de 12 números, para a lista não inflar; `null` sem os 12 meses)
- `origens`

Ordem: `volume_mensal` desc, `null` por último. `limit` corta a cauda; `truncated` e
`total_devolvido_pelo_google` declaram o corte (padrão do `nucleo.md`, "teto em read novo").

A resposta sempre traz, além da lista: `recorte` (cidades resolvidas ou Brasil, idioma, rede),
`conta_base`, `volume_em_degraus: true` com a frase da description, e `avisos`.

### 4.4 `get_keyword_metrics`

Entradas: `termos` (lista, teto a definir pelo builder dentro do limite da API), `cidades`,
`customer_id` obrigatório. Saída por termo no mesmo formato da 4.3, sem `origens`. Termo sem dado →
métricas `null` e o termo listado em `sem_dado`. Ecoa `close_variants` quando o Google agrupa
variantes.

### 4.5 Descriptions (o que o LLM precisa ler certo)

- Volume em **degraus do Google**, não exato; `null` = o Google não tem dado, não zero.
- CPC é **estimativa de topo de página** do Google, numa faixa, não o que a conta paga.
- O recorte (cidade resolvida, Brasil, idioma) muda o volume em ordens de grandeza (fato 4): sempre
  dizer qual foi usado.
- Site e concorrentes ampliam a lista por origem; a ordem é por volume.

## 5. Execução e governança

- **Executor novo** (não é GAQL). Segue o padrão dos executores Google do `nucleo.md`:
  `ensure_account_access` no topo, `before_call` com `reserved` na transação externa e
  `record_actual` gated, audit **sempre** (`audit_this_call=True`, dado de planejamento para cliente),
  `run_blocking` em toda chamada do SDK (inclusive o `suggest_geo_target_constants`), `to_friendly`
  nos erros. Os guards estruturais (F57, `run_blocking`) têm de cobri-lo sem allowlist nova.
- **Quota (minha decisão):** **uma reserva por requisição da tool**, com `estimated_ops` = total de
  chamadas previstas ao SDK (resolução de cidades + origens × cidades), no padrão do
  `customer_match.py::run_offline_user_data_job` (reserva única, `record_actual` com o realizado).
- **Versão do SDK (minha decisão):** a mesma dos outros executores — `client.get_service(...)` /
  `client.get_type(...)` sem versão explícita, que é o que a sondagem usou (`v25` no `google-ads`
  31.4.0). Os testes usam os tipos do mesmo caminho. Observação fora de escopo: o CLAUDE.md diz v24 e
  só `queries/recommendations.py` importa `v24` explicitamente.
- **Falha parcial entre origens (minha decisão):** erro de uma URL (inválida, bloqueada) não derruba
  as outras: a resposta traz o que voltou e lista a origem que falhou em `origens_com_falha`, com a
  mensagem do `to_friendly`. Erro de **quota, autorização ou acesso** derruba a requisição inteira,
  porque a próxima chamada falharia igual.
- **Estado na cidade (minha decisão):** aceita sigla (`PB`) ou nome (`Paraíba`), via tabela fixa das
  27 UFs para casar com o `canonical_name`.
- **Limite de requisições do serviço (fato 8, não medido):** o erro de quota/rate do Google sobe pelo
  `to_friendly` com mensagem clara; sem retry automático nesta entrega.

## 6. Testes e guards

- Módulo puro (união por origem, ordenação, corte, sazonalidade, leitura com presença) testado com
  **mensagens reais do SDK** (`KeywordPlanIdeaService` types), não `MagicMock`, e com os casos
  medidos: termo sem bloco de métricas → `null` (o teste falha se ler 0); degraus; ideia vinda de duas
  origens.
- Resolução de cidade: homônimos do fato 5 como fixture **copiada do `repr` da resposta crua**, não da
  saída impressa (lição do U+00A0, 29/10). Bairro/CEP nunca vencem; estado informado desempata.
- Sabotagem dos guards contra o código pré-fix (`testes.md`).
- Sondagem versionada em `scripts/` com os fatos 2–6, como as outras `probe_*`.

## 7. Smoke (depois do deploy, em sessão nova — F140)

| Caso | Esperado |
|---|---|
| sementes "aluguel de andaime", "locação de equipamentos", João Pessoa | ~centenas a milhares de ideias antes do corte; "aluguel de andaime" com volume 40 (29/10) |
| mesmo com `site` = mestredaobra.com.br | ideias com `origens` incluindo `site` |
| `get_keyword_metrics` com um termo inexistente | métricas `null`, termo em `sem_dado` |
| cidade "Campina Grande" | resolve para City PB (`1001621`), não "Campina Grande do Sul" |
| cidades João Pessoa + Campina Grande | `volume_por_cidade` de "aluguel de andaime" ≈ {JP: 40, CG: 20}, sem soma |
| mesma consulta em duas contas do gestor | mesmos termos e números (fato 9) |

## 8. Deixado ao builder

- Nomes finais das tools e dos campos, mantendo os conceitos.
  - Nomes escolhidos na implementação: `volume_por_cidade` virou `por_cidade` (métricas completas por cidade, sempre com todas as cidades pedidas, `null` onde não voltou); `volume_maximo` por ideia; `total_ideias` = contagem após a união por termo, antes do `limit`; `customer_id` ecoado; em `get_keyword_metrics`, `sem_dado` (devolvido sem métricas), `sem_resultado` (não devolvido) e `agrupado_em` (termo casado por variante próxima).
- Teto de `termos` em `get_keyword_metrics`.
- `estimated_ops` por requisição.
- Normalização para unir ideias de origens diferentes (caixa, acento, espaços).
