# Saldo da conta (Google e Meta) — design

**Data:** 2026-10-28. **Aprovado por:** Wellington, em 28/10.

**Origem:** análise de 28/10 sobre necessidade e viabilidade. Hoje a equipe descobre que uma conta
parou por falta de saldo pelo aviso da Meta (às vezes) ou por checagem manual. Nenhuma das 68 tools
responde "quanto falta até os anúncios pararem": o `get_budget_pacing` olha o orçamento das
campanhas, não o teto da conta.

## 1. Fatos medidos (premissas do desenho)

Todos sondados em 28/10, só leitura.

**Google (`account_budget`, via `run_gaql`)**

1. **O restante da tela é `adjusted_spending_limit_micros − amount_served_micros`, ao centavo.**
   Hosp Ocular (`2935187268`): ajustado R$ 34.782,19 − gasto R$ 34.468,97 = **R$ 313,22**, igual
   ao "Fundos disponíveis" do Faturamento (print do Wellington, 28/10). O campo
   `approved_spending_limit_micros` daria R$ 152,03 (errado): a diferença são os
   `total_adjustments_micros` (R$ 161,19).
2. **No pré-pago manual, o limite é a soma dos pagamentos mais os ajustes.** A mesma tela mostra
   "Último pagamento: R$ 1.500,00, pagamento manual" e um histórico de pagamentos mensais.
3. **Conta sem teto vem com `approved_spending_limit_type: INFINITE`** e sem
   `*_spending_limit_micros`. Foram 4 das 6 contas sondadas: MDO JP, 3 Lagoas, Colenci e SedLoc.
   **Não medido:** se `INFINITE` equivale sempre a pagamento automático. A API não traz a forma de
   pagamento.
4. **Conta esgotada continua gerando impressões soltas e gasto zero.** Cantina (`9432514654`):
   limite R$ 500,00, gasto R$ 499,15, restante **R$ 0,85**. Custo diário zero desde 19/10, com 1 ou
   2 impressões por dia. A média de 7 dias corridos é ≈ 0, porque a conta já parou.
5. Nas 6 contas sondadas, `account_budget` devolveu **uma linha** `APPROVED`. **Não medido:** conta
   com orçamento novo pendente (`pending_*`) ou com orçamentos antigos encerrados na mesma consulta.

**Meta (`GET /act_<id>`, Graph v22.0, token do system user)**

6. **O token lê todos os campos sem erro de permissão.** Foram 8 contas: `name`, `account_status`,
   `disable_reason`, `is_prepay_account`, `spend_cap`, `amount_spent`, `balance`, `currency` e
   `funding_source_details`.
7. **O saldo pré-pago só existe como texto:** `funding_source_details.display_string` =
   `"Saldo disponível (R$633,45 BRL)"`, com `type: 20`. Não há campo numérico.
8. **Há dois freios independentes no pré-pago:** o saldo e o `spend_cap` (limite de gastos da conta,
   definido pelo anunciante). Cantina (`act_3709029949237406`) tem saldo R$ 633,45 e limite
   R$ 800,01 − gasto R$ 243,52 = R$ 556,49. **O limite trava antes do saldo.**
9. **`spend_cap: "0"` significa sem limite.** Os valores vêm em centavos (string): `"80001"` =
   R$ 800,01. 3 Lagoas e [Cotia] MDO têm `spend_cap == amount_spent`, ou seja, estão paradas pelo
   limite.
10. **No cartão (`is_prepay_account: false`, `type: 1`), `balance` é o valor a faturar, não saldo.**
    Mi importss Resv: `balance` R$ 1.218,58 com `account_status: 3` (pagamento pendente).
    `display_string` é a bandeira (`"VISA *6522"`).
11. **Cupons vêm em `funding_source_details.coupons`** com `amount: 0` mesmo dentro da validade
    (Dr. Dérick). O valor não é confiável como crédito.

## 2. Escopo

| Item | O quê |
|---|---|
| `get_account_balance` (Google) | Uma conta (`customer_id`): restante até parar, dias restantes, situação, data de fim. |
| `meta_get_account_balance` (Meta) | Uma conta (`ad_account_id`): os dois freios, o que trava primeiro, dias restantes, status e forma de pagamento. |

O catálogo passa de 68 para **70 tools**. As duas são só leitura.

**Fora de escopo (decidido pelo Wellington):**
- **Alerta automático** (job diário que avisa quando faltam menos de N dias). Vai como pendência no
  `estado-atual.md`. Sem ele, ainda depende de alguém consultar. O desenho não impede o job: o
  cálculo vive em módulo puro, reaproveitável.
- **Varredura de todas as contas** ("quais acabam logo"). A pergunta escolhida foi a de uma conta.

**Fora de escopo (minha decisão):**
- Cupons no restante (fato 11). Aparecem só como informação.
- Faturas e documentos (`invoice_service`, `payments_account_service`).

## 3. Desenho

### 3.1 Módulo puro `src/google_ads/saldo.py` e `src/meta_ads/saldo.py`

Sem I/O. Recebem o que as chamadas devolveram e montam a resposta. É o que os testes exercitam e o
que um job futuro reaproveita.

**Situação (`situacao`), vocabulário comum às duas plataformas:**

| valor | quando |
|---|---|
| `sem_teto` | Google `INFINITE`; Meta pós-paga sem `spend_cap`. A conta não para por saldo. |
| `esgotada` | restante efetivo ≤ 0, **ou** restante menor que um dia de gasto (regra abaixo). |
| `acabando` | dias restantes ≤ 7. |
| `com_saldo` | dias restantes > 7. |
| `sem_gasto` | há restante, mas a média dos últimos 7 dias é zero (conta pausada, por exemplo) e a regra de `esgotada` não disparou. `dias_restantes: null`. Decisão do Wellington: não é alarme. |
| `indeterminada` | não deu para calcular. Exemplos: saldo pré-pago ilegível (3.3); gestor sem permissão para ler o `account_budget`. Traz `motivo`. |

Ordem de avaliação: `sem_teto` → `indeterminada` → `esgotada` → `sem_gasto` → `acabando`/`com_saldo`.
Conta **sem nenhum dia com gasto em 30 dias** não tem régua de "um dia de gasto": com restante > 0
ela é `sem_gasto`; com restante ≤ 0, `esgotada`.

Na Meta, `account_status ≠ 1` não muda a `situacao` (que fala de dinheiro). Vai em campo próprio
(`status_conta`) e gera aviso. Pagamento pendente para a conta mesmo com `situacao: sem_teto`.

**Dias restantes:** `restante / média diária dos últimos 7 dias completos` (decisão do Wellington),
no fuso da conta (`resolve_account_today` / `resolve_meta_account_today`), sem o dia corrente.
Média zero → `dias_restantes: null`, com motivo "sem gasto nos últimos 7 dias".

**"Menos de um dia de gasto" (minha decisão):** compara o restante com a **média dos dias com gasto
nos últimos 30 dias**, não com a de 7 dias corridos. A conta esgotada (fato 4) tem média de 7 dias
≈ 0, e a regra de 7 dias nunca a chamaria de esgotada. Cantina Google: R$ 0,85 < ~R$ 55 → `esgotada`.

**O restante é sempre aproximado:** o gasto acumulado atrasa algumas horas. Todo payload traz
`aproximado: true` e a frase na description.

### 3.2 `get_account_balance` (Google)

Entrada: `customer_id` (obrigatório). Duas consultas pelo executor `run_report` de sempre (gate de
acesso, quota com `reserved`, audit, `run_blocking`):

1. `account_budget` com `status = APPROVED`, vigente agora (`approved_start_date_time ≤ agora` e fim
   ausente ou futuro). Campos: `adjusted_spending_limit_micros`, `approved_spending_limit_type`,
   `amount_served_micros`, `total_adjustments_micros`, `approved_end_date_time`,
   `approved_end_time_type`, e os `pending_*` para informar proposta pendente.
2. Custo diário da conta (`FROM customer`, `segments.date`) nos últimos 30 dias completos.

Saída (forma, nomes finais com o builder):
- `situacao`
- `restante_brl` (ajustado − gasto; `null` em `sem_teto`)
- `limite_ajustado_brl`, `gasto_acumulado_brl`, `ajustes_brl`
- `dias_restantes`, `media_diaria_7d_brl`
- `data_fim` (ou `null` se `FOREVER`)
- `orcamento_pendente` (se houver proposta pendente)
- `aproximado: true`
- `avisos[]`

**Data de fim é freio (decisão do Wellington):** com `approved_end_date_time` definido,
`dias_ate_fim` = dias corridos de hoje (fuso da conta) até a data. `dias_restantes` = o menor entre
`dias_ate_fim` e os dias pelo saldo, e `trava_primeiro` diz qual: `saldo` ou `data_fim`, igual à
Meta. Data de fim já passada → `esgotada` com motivo "orçamento da conta encerrado". Sem gasto
recente, mas com data de fim: `sem_gasto`, e `dias_ate_fim` aparece mesmo assim.

**Nenhuma linha vigente** (conta sem `account_budget`): `situacao: indeterminada`, motivo "conta
sem orçamento de conta vigente", sem erro. **Mais de uma linha vigente:** usa a de início mais
recente e avisa. Não medido (fato 5), e a resposta diz isso.

**Permissão (minha decisão):** a sondagem usou o OAuth do Wellington. Se o OAuth de um gestor
comum não ler `account_budget` (erro de autorização do Google nessa consulta), a tool devolve
`indeterminada`, motivo "sem permissão de faturamento nesta conta", e não um erro genérico. O smoke
inclui uma conta lida por gestor comum, se houver um ativo; se não houver, isso fica registrado como
não medido.

**Audit (minha decisão):** as duas tools passam `audit_this_call=True` em todas as chamadas, por ser
dado financeiro.

**Forma de pagamento:** a API não informa (fato 3). A resposta diz `tipo_de_teto: "finito"` ou
`"sem_teto"`, nunca "cartão"/"boleto".

### 3.3 `meta_get_account_balance` (Meta)

Entrada: `ad_account_id` (`act_<n>`). Duas chamadas por `run_meta_graph_get` (gate incondicional,
edge amarrada à conta):

1. `GET /act_<id>` com os campos do fato 6. A edge `/act_<id>` passa no check do F190.
2. Gasto diário dos últimos 30 dias completos, em `/insights` com `time_increment=1`, montado por
   `insights.build_insights_call` e lido por `metricas_da_linha` (contrato F194). **Minha decisão:**
   hoje o `build_insights_call` não aceita `time_increment` e sempre manda `sort=spend_descending`.
   Estender a assinatura com um parâmetro opcional (default igual ao atual, para as tools de
   performance não mudarem; isso é testado). **Pré-requisito do plano:** sondar a combinação nova
   com um controle inválido, como no `probe_meta_combinacoes.py`, porque o 200 sozinho não prova
   nada (F53/F54/F55).

**Antes de shippar:** passar os campos novos por `ads_get_field_context` (regra F53/F54/F55 do
`nucleo.md`). A sondagem prova que a Graph os devolve, mas não substitui a regra.

**Extração do saldo pré-pago (decisão do Wellington: extrair com fallback):**
- Função pura `saldo_do_texto(display_string) -> Decimal | None` para o formato medido
  (`Saldo disponível (R$633,45 BRL)`: milhar com ponto, decimal com vírgula).
- Formato não reconhecido → `null`, mais `saldo_prepago_texto` cru, mais aviso
  `saldo_prepago_ilegivel`. **Nunca um número chutado.**
- Só para `is_prepay_account: true`. No cartão, o `display_string` vai como `forma_de_pagamento`.

**Os dois freios (decisão do Wellington: destacar o que trava primeiro):**
- `freio_saldo` = saldo extraído (só pré-pago).
- `freio_limite` = `spend_cap − amount_spent`, só se `spend_cap > 0`.
- `restante_brl` = o menor dos freios presentes; `trava_primeiro` diz qual é: `saldo_prepago` ou
  `limite_de_gastos`. Os dois aparecem na resposta.
- Nenhum freio presente no pós-pago → `sem_teto`.
- **Pré-pago com saldo ilegível → sempre `indeterminada` (decisão do Wellington)**, mesmo com
  limite de gastos: o saldo ilegível pode ser o freio menor. Com limite, a resposta mostra
  `teto_pelo_limite_brl` ("no máximo R$ X") e o texto cru, sem `restante_brl` nem `dias_restantes`.
- Valores em centavos da moeda da conta. Todas as contas hoje são BRL. Conta em outra moeda: o
  builder converte pelo offset da moeda ou recusa com mensagem clara (escolha do builder; não há
  caso hoje).

**Também na saída:**
- `status_conta` + rótulo (`META_ACCOUNT_STATUS_LABELS`), `disable_reason` + rótulo
- `forma_de_pagamento` (`pre_pago` / `pos_pago` e o `display_string`)
- `a_faturar_brl` (o `balance`, só no pós-pago, com esse nome; nunca "saldo")
- `cupons` informativos
- `dias_restantes`, `media_diaria_7d_brl`, `aproximado: true`, `avisos[]`

## 4. Testes e guards

- **Módulos puros:** cada `situacao`, com os casos medidos como fixtures:
  - Hosp Ocular → R$ 313,22, e **o teste falha se trocar ajustado por aprovado**
  - Cantina Google → `esgotada` com média de 7d zero
  - Cantina Meta → limite trava antes do saldo
  - 3 Lagoas → `esgotada` pelo limite
  - Mi importss → `sem_teto` + aviso de pagamento pendente
  - MDO JP Meta → pré-pago, saldo 0, sem limite → `esgotada`
  - conta com restante e média de 7d zero → `sem_gasto`
  - Google com data de fim antes do saldo → `trava_primeiro: data_fim`; data passada → `esgotada`
  - Meta pré-paga com texto ilegível e com limite → `indeterminada` + `teto_pelo_limite_brl`
  - `build_insights_call` sem o parâmetro novo devolve exatamente a chamada de antes
- **`saldo_do_texto`:** formato medido, milhar (`R$1.234,56`), zero, formato desconhecido → `None`
  (nunca exceção, nunca número parcial).
- **Builders:** `make_capture_client`, nunca `MagicMock` (guard da Onda 0).
- Sabotagem dos guards contra o código pré-fix, como manda o `testes.md`.
- Guards estruturais existentes (F57, F57-Meta, `run_blocking`, sem segredo em query) cobrem as
  tools novas sem mudança; o builder confirma rodando.

## 5. Smoke (depois do deploy, em sessão nova — F140)

| Conta | Esperado |
|---|---|
| Hosp Ocular (Google) | `restante_brl` = "Fundos disponíveis" da tela no dia |
| Cantina (Google) | `esgotada` |
| MDO JP (Google) | `sem_teto` |
| Cantina (Meta) | `trava_primeiro: limite_de_gastos`; saldo = texto do Gerenciador |
| 3 Lagoas (Meta) | `esgotada` |
| Mi importss Resv (Meta) | `sem_teto` + aviso de pagamento pendente, `a_faturar_brl` preenchido |

## 6. Deixado ao builder

- Nomes finais dos campos de saída, mantendo os conceitos acima.
- Reaproveitar ou não a consulta de custo diário existente.
- Paginação/forma de chamada do `/insights` diário dentro do contrato F194.
- Moeda não-BRL (3.3).
