# Smoke — backlog de tráfego (M1, N1+N2, N3, G1, G2, M2, M3)

**Conta:** MO-JP `7862230676` · **Quem executa:** a sessão "Gestor de Tráfego JP", **reconectada** ·
**Quem autoriza:** o Wellington, nominalmente, em cada passo marcado 🔴.

Este roteiro prova o que os testes não provam: que o cliente aceita o catálogo novo, e que as
releituras pós-escrita (M1, G2, N3) trazem o estado **novo**. O segundo ponto é o Important 2 da
revisão final: **o frescor da releitura nunca foi medido**.

## 0. Pré-requisitos (não pule)

- [ ] O PR #255 está **mergeado e deployado**: `gh run view <id> --json conclusion` = `success`
  e `/health?deep=1` = ok. Antes do #255, a produção ainda rebaixa `efeito` em vez de
  preencher `conferencia`, e este roteiro descreve o comportamento **depois** do #255.
- [ ] **Sessão nova.** O catálogo vem do handshake (F140). Feche e reabra a conexão MCP, ou abra
  uma conversa nova.
- [ ] **O catálogo carregou.** Se a sessão abrir sem tools ou com erro 400, **pare**: é o risco do
  schema do item de texto do RSA (sem `type`, G2). Registre o cliente (Claude, Codex ou Cursor)
  e a mensagem, e avise o Wellington.
- [ ] Ao chamar `list_my_accounts`, a lista inclui a MO. As tools `get_experiments` e
  `update_recommendation_subscription` aparecem no catálogo.

Registre cada resultado na tabela do fim. **Prove chamando, não lendo o schema.**

---

## 1. Leituras (sem risco, sem aval)

### 1.1 G1 — `get_experiments`
```
get_experiments(customer_id="7862230676")
```
Esperado:
- dois experimentos: `10061805617` ENABLED (2026-10-15 → 2027-01-07) e `10061636855` REMOVED;
- `atribuicao: "inferida_por_eliminacao"`;
- 5 grupos (MARTELETE, BETONEIRA, COMPACTADOR, ANDAIME, GERADORES), cada um com 2
  `base_ad_ids` e 2 `variacao_ad_ids`;
- `janela.inicio = 2026-10-15` e `janela.fim =` ontem;
- `como_aplicar` e `aviso` presentes.

Para conferir os números, MARTELETE e BETONEIRA de 15/10 a 13/11 devem bater com a GAQL que o
controlador mediu em 14/11:
- MARTELETE: base 558 imp, 33 cliques, 8 conv; variação 504 imp, 31 cliques, 8 conv;
- BETONEIRA: base 480 imp, 19 cliques, 6 conv; variação 695 imp, 58 cliques, 10 conv.

A janela da chamada vai até ontem, então ela vai ter **mais** dias que a medição de 14/11. Por
isso os números da tool devem ser **maiores ou iguais** a esses, nunca menores.

### 1.2 M3 — `list_gaql_resources`
```
list_gaql_resources(resource="ad_group_ad", customer_id="7862230676")
```
Esperado:
- `compativel.segments` não contém `segments.hour` (medido em 19/09);
- `fonte: "GoogleAdsFieldService v25"`.

Controles:
- sem `customer_id` → recusa pedindo `customer_id`;
- sem `resource` → resposta igual à antiga, sem `compativel`.

### 1.3 N1+N2 — já provado em 14/11 (controlador). Só repita se algo mudou.

---

## 2. 🔴 G2 + M1 — RSA de teste PAUSADO com pino

**Grupo:** `204135195030` ([GPA][09][CONTAINER], campanha JPA, **fora** do experimento). **Não
use** os grupos 171330816462, 174186730259, 175065786658, 175472286913 nem 196329838059, porque
estão no teste de URL. O anúncio nasce **PAUSED** e não entra em leilão.

### 2.1 Criar (dry-run → aval → apply)
```
create_rsa(customer_id="7862230676", rsas=[{
  "ad_group_id": "204135195030",
  "status": "PAUSED",
  "final_urls": ["https://lp.mestredaobralocacoes.com.br/joao-pessoa#container"],
  "headlines": [
    {"text": "Aluguel de Container JP", "pinned_field": "HEADLINE_1"},
    "Container para Obra", "Locação de Container", "Container Escritório",
    "Mestre da Obra - JP"
  ],
  "descriptions": [
    "Container para obra e escritório em João Pessoa. Entrega na obra.",
    "Locação por diária, semana ou mês. Solicite orçamento."
  ]
}])
```
- **Dry-run:** o preview mostra o pino em `HEADLINE_1` e o aviso de força do anúncio.
- **Peça o aval nominal** ("pode aplicar o create_rsa de teste no CONTAINER") e só então rode
  `apply_change(token)`.

No apply, registre:
- `efeito: "mudou"` e `changed_count: 1`;
- `estado_revisao[0]`: `approval_status`/`review_status` (o esperado é REVIEW_IN_PROGRESS ou
  UNDER_REVIEW, que é foto, não veredito), `lido_em` preenchido, `assets_reprovados: []`;
- `releitura.query` presente;
- **`conferencia` da linha (pinos):** `confere` ou divergência. ⚠️ **Este é o dado de frescor.**
  Se vier divergente, a releitura imediata está defasada.

**Anote o `ad_id` criado.**

### 2.2 Frescor da releitura (medição)
Rode a `releitura.query` da resposta no `run_gaql` três vezes: logo depois, depois de 2 min e
depois de 10 min. Registre em cada uma o `review_status` e se o pino `HEADLINE_1` aparece. A
diferença entre a 1ª leitura e as seguintes é o que o Important 2 pede para medir.

### 2.3 Recusa de perda de pino (só dry-run, sem apply)
```
update_rsa(customer_id="7862230676", updates=[{
  "ad_id": "<ad_id de 2.1>",
  "headlines": ["Container para Obra", "Locação de Container", "Container Escritório"]
}])
```
- Esperado: **recusa** citando `HEADLINE_1` e `remover_pinos`, **sem token**.
- Controle: repita com `"remover_pinos": true`. Deve sair o preview com token. **Não aplique.**

### 2.4 ad_id repetido (só dry-run)
Monte um `update_rsa` com dois itens para o **mesmo** `ad_id`. Esperado: recusa citando o
`ad_id`, sem token.

### 2.5 🔴 Limpeza
O anúncio de teste fica PAUSED. Para removê-lo, o Wellington decide e dá o aval nominal do
`update_ad_status` REMOVED. Se não houver aval, ele fica pausado e anotado aqui.

---

## 3. M2 — lote grande (só dry-run)

Sem aval, só preview e **sem apply**. Isso mede o tamanho do preview compacto, que ficou NÃO
MEDIDO na revisão. Monte um `update_rsa` só de `final_urls` com os RSAs ENABLED da conta, até
50. Use os `ad_id` reais de um `run_gaql` FROM `ad_group_ad`, com RSA ENABLED e **excluindo**
`AD_VARIATIONS`. Repita o `final_urls` atual de cada anúncio, para que nada mude mesmo se alguém
aplicar por engano.

Registre:
- se o preview veio compacto (mais de 5 itens);
- o número de itens;
- o tamanho aproximado da resposta;
- se o cliente aceitou a resposta sem truncar.

🔴 Um lote **real** de troca de URL só acontece se o gestor quiser trocar a URL de verdade, com
aval nominal.

---

## 4. 🔴 N3 — pausar a assinatura `RESPONSIVE_SEARCH_AD`

Estado medido em 14/11: ENABLED desde 06/06/2024, com `modify_date_time` igual à criação (nunca
foi tocada). A UI não lista esse tipo (F185).

```
update_recommendation_subscription(customer_id="7862230676",
                                   type="RESPONSIVE_SEARCH_AD", status="PAUSED")
```
- **Dry-run:** o preview mostra ENABLED → PAUSED.
- **Peça o aval nominal** ("pode pausar a assinatura RESPONSIVE_SEARCH_AD da MO").
- **Apply:** registre `efeito`, `status_resultante` e `conferencia` (campo `status`):
  `confere` ou divergência, que é a medição de frescor do N3.

Confirmação independente com `run_gaql`:
```
SELECT recommendation_subscription.type, recommendation_subscription.status,
recommendation_subscription.modify_date_time FROM recommendation_subscription
WHERE recommendation_subscription.type = 'RESPONSIVE_SEARCH_AD'
```
Esperado: PAUSED, com `modify_date_time` de hoje.

Controles:
- repetir o pedido PAUSED → "ja esta PAUSED", sem token;
- `type="UNKNOWN"` → recusa no schema.

Reversível pelo mesmo caminho, com `status="ENABLED"`, que também exige aval.

---

## 5. Resultados

| Passo | Resultado | Medido em | Observação |
|---|---|---|---|
| 0 catálogo carregou (cliente: ___) | | | |
| 1.1 G1 | | | |
| 1.2 M3 | | | |
| 2.1 G2+M1 apply (`ad_id` ___) | | | conferencia: |
| 2.2 frescor 0 / 2 / 10 min | | | |
| 2.3 recusa de pino | | | |
| 2.4 ad_id repetido | | | |
| 2.5 limpeza | | | |
| 3 M2 preview (itens ___, tamanho ___) | | | |
| 4 N3 apply | | | conferencia: |

Quando terminar, devolva a tabela à sessão do repo. Ela atualiza o
`docs/operacao/estado-atual.md` e fecha (ou reabre) o Important 2.
