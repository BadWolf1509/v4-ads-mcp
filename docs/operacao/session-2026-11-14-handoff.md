# Sessão de 14/11 — Handoff (backlog de tráfego: M1, N1+N2, N3, G1, G2, M2, M3)

> Desenho: [`2026-11-14-backlog-trafego-design.md`](../superpowers/specs/2026-11-14-backlog-trafego-design.md) ·
> Plano: [`2026-11-14-backlog-trafego.md`](../superpowers/plans/2026-11-14-backlog-trafego.md) ·
> Smoke: [`smoke-2026-11-14-backlog-trafego.md`](smoke-2026-11-14-backlog-trafego.md).
> Ledger da execução (git-ignored, com todos os rulings e os minors adiados):
> `D:/v4-ads-mcp/.superpowers/sdd/2026-11-14-backlog-trafego/progress.md`.
> Anterior: [`session-2026-11-10-handoff.md`](session-2026-11-10-handoff.md).

## Origem

A sessão "Gestor de Tráfego JP", que opera a MO-JP (`7862230676`), pediu uma análise conjunta do
backlog dela (`D:\Gestor de Tráfego de Ads\mcp-v4-ads-backlog-melhorias.md`).

**F154, F178 e F179 já estavam fechados** e saíram do backlog. O Wellington aprovou os 7 itens, e o
desenho foi feito item a item, com os menus da sessão. **`end_experiment` ficou fora:** o teste
`10061805617` termina sozinho em 2027-01-07, e o uso pedido (aplicar o resultado) já é `update_rsa`
no base. Execução por subagentes, um PR por item, com aval em bloco do Wellington para push, PR e
merge.

## O que entrou em produção

Cada deploy foi conferido com `gh run view` = `success` e `/health?deep=1` ok. **A revisão servindo
não foi medida:** `gcloud` sem credencial em 14/11.

| PR | item | o quê | deploy |
|---|---|---|---|
| #249 | M1 | `_RSA` em `confirmadores.py`: releitura numa GAQL → `estado_revisao` (approval/review por anúncio e por asset, `assets_reprovados`, `pinos`), `lido_em`, `releitura` | 43618645954 |
| #250 | N1+N2 | `gaql_lint.avisos_gaql`: `avisos[]` em `run_gaql`/`validate_gaql` quando há `segments.date` no SELECT; hint específico para "must be present in SELECT" em `errors.py` | 43621984022 |
| #251 | N3 | `update_recommendation_subscription` (pausa/reativa assinatura existente; UNKNOWN recusado, F185) | 43624699750 |
| #252 | G1 | `get_experiments`: atribuição por eliminação + comparativo base × variação por grupo | 43627721439 |
| #253 | G2 | `pinned_field` em `create_rsa`/`update_rsa`; recusa de perda de pino **por posição** (`remover_pinos` por update); item de texto **sem `type`** + validação no corpo; guard `test_no_type_array_in_any_schema` | 43631011368 |
| #254 | M3 | `list_gaql_resources(resource, customer_id)` lê `selectable_with` do `GoogleAdsFieldService`; gate de leitura em toda chamada; cota só sem cache | 43633874859 |
| #255 | M2 + revisão final | teto de lote RSA 5 → 50 + preview compacto; **contrato `conferencia`**; `ad_id` repetido recusado; lint avisa SELECT ilegível; G1 nega a eliminação com AD_VARIATION em outro estado | 43639950179 |
| #256, #257 | docs | `estado-atual.md`, roteiro e resultado do smoke | — |

## 🔴 Contrato novo do `apply_change` (#255)

**`efeito` e `changed_count` voltaram a ser só o ACK do Google** e concordam com o `had_effect` do
`audit_log`. O veredito da releitura pós-write vai no campo novo `conferencia`, por linha:
`{campo, pedido, relido, motivo}`.

- **Onde existe:** `_RSA` (campo `pinos`) e `_AssinaturaRecomendacao` (campo `status`).
- **Divergência:** o `motivo` dá as causas como "possível" (F184, leitura defasada ou mudança
  concorrente), e sai o log `conferencia_pos_write_divergiu`.
- **Não lido:** `conferencia` vem `null`.

**Por quê:** entre o #253 e o #255, o G2 rebaixava para `sem_efeito` um RSA que **foi gravado**. Um
modelo que segue o contrato do `apply_change` recriaria o anúncio e o duplicaria. A revisão final do
conjunto achou isso, e o Wellington escolheu "campo próprio" em vez de "manter e documentar".

**Consumidores auditados:**
- **Plugin `v4-trafego-google-ads` 0.5.0:** nenhuma skill lê `efeito`.
- **Reference e pegadinha 23 do workspace de tráfego:** já descreviam a semântica de ACK que o #255
  restaurou.
- **Reference do gestor:** a sessão de tráfego já incorporou a lista das mudanças.

## Medido nesta sessão

- **N1, o que esconde entidade:** é `segments.date` **no SELECT**. Na MO, com as 4 campanhas
  REMOVED e 0 impressão, a query sem data ou com data só no WHERE devolve 4 linhas; com a data no
  SELECT, devolve 0. `segments.week/month/...` não foram medidos.
- **N2:** o `validate_gaql` já pegava o erro, porque o `validate_only` acusa "must be present in
  SELECT". O defeito era só o sufixo genérico.
- **"Null silencioso" de `quality_info` + `segments.date` (19/09):** **não reproduz**. Na MO,
  `keyword_view` com 7 dias deu 404 de 500 linhas com `quality_score`. A sessão de tráfego remediu e
  achou 398 de 493. **A regra não entrou no lint.**
- **N3:** a medição de urgência da sessão de tráfego usou o `client_type` errado: o auto-apply de
  assinatura é `GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION` (F142). A conclusão vale pelo controle sem
  filtro (73 eventos, todos `GOOGLE_ADS_API`).
- **`experiment_arm` segue vazio na v25** (F181). Os 5 grupos do teste de URL têm 2 bases + 2
  variações ENABLED cada.
- **Schemas:** antes do G2, nenhum dos 82 usava `type` em lista. É território não testado, cuja falha
  é um 400 que derruba a sessão inteira do gestor (3b.18/3b.19B).

## Smoke (14/11, 21:25–21:45 UTC) — 7/7

Executado pela sessão de tráfego, reconectada, com aval nominal nos writes. A tabela completa está
no [`estado-atual.md`](estado-atual.md) até a próxima limpeza; aqui fica o essencial:

- **Catálogo:** carregou no **Claude Code**. **Codex e Cursor: não medidos.**
- **`create_rsa` PAUSED com pino (`831715335281`, grupo CONTAINER):** `conferencia` `confere`. O
  frescor da releitura ficou estável em 0, ~1,6 e ~8 min. O frescor da **aprovação** ficou **não
  medido**: o anúncio não saiu de revisão.
- **N3:** a MO tem **0 assinaturas ENABLED**. O repo conferiu por GAQL.
- **M2:** lote de 27 em dry-run, ~7,5 KB. O pior caso com 50 itens não foi medido.
- **Limpeza:** o RSA de teste foi removido pela UI. O repo conferiu `REMOVED` por GAQL.

## Abertos

- **S1:** a lista estática `segments` do `list_gaql_resources` traz `segments.hour` e
  `segments.network_type`, que não existe (o nome é `ad_network_type`).
- **S2:** o preview do `update_rsa` não acusa no-op. Uma `final_urls` igual à atual aparece como
  mudança.
- **S3:** não há tool para remover anúncio. O `update_ad_status` só aceita ENABLED/PAUSED.
- **Minors adiados** (ledger), os de maior valor:
  - a comparação de pinos é por contagem, então uma troca entre posições passa;
  - `remover_pinos` não tem verificação pós-write;
  - o N3 não refaz a checagem otimista entre o preview e o apply;
  - o G1 lê todos os RSAs ENABLED sem teto e não expõe `final_urls`;
  - o M3 devolve `str(e)` cru, e um `AccountAccessDenied` do 2º gate vira "falha do FieldService";
  - `final_urls` não tem `maxItems`.
- **Não medido:** o catálogo no Codex/Cursor; o frescor da aprovação; o preview de 50 no pior caso;
  a revisão servindo.

## Rulings tomados sem consulta (custo se errados)

1. **Spec e plano no PR da Parte 1.** O PR ficou maior.
2. **`lido_em` vira `null` sem leitura**, contra o brief, que pedia `str`. O contrato mudou antes de
   ter consumidor.
3. **A revisão de task valeu como revisão do PR**, e a revisão do conjunto rodou no fim. Defeito
   entre partes só aparece depois do deploy das anteriores, e foi o que aconteceu com o
   `sem_efeito`.
4. **Proibido `type` em lista nos schemas**, com validação no corpo e um guard. O schema fica menos
   descritivo para o modelo.
5. **M3 com `customer_id` obrigatório e gate em toda chamada**, em vez de exceção no guard F57. A
   tool ganhou um parâmetro a mais para um metadado que não depende da conta.
6. **G1:** o `experiment_id` filtra a lista, mas a eliminação vale para a conta inteira; experimento
   não iniciado sai com janela `null`.
7. **G2:** a checagem de pino é por campo (headlines e descriptions independentes).
8. **Rodada única de correção no #255**, com 5 minors entre partes. Isso mexeu em código já em
   produção.
9. **Execução:**
   - branches no checkout principal, mais um worktree para o M2, para não colidir com a revisão do M3;
   - cópia do plano no workspace;
   - minors baratos dentro das rodadas de correção.
