# Sessão 2026-10-03 a 10-06 — Handoff (fecho de conversões, remedição, negativas e gaql compacto)

> Mapa da sessão. Estado vivo no [`estado-atual`](estado-atual.md); defeitos no
> [catálogo](findings-catalog.md). Anterior: [`session-2026-10-02-handoff.md`](session-2026-10-02-handoff.md).

## O que entrou

| PR | o quê | produção |
|---|---|---|
| #144, #145 | fecho da frente conversões e parcela; o F140 com o schema velho no cliente | docs |
| #151 | buckets de 05/10: 9 tools sem uso de gestor descem para defer (always 22 → 13) | `00144` |
| #152 | os 5 bumps de patch do Dependabot num commit (fecharam os #146–#150) | `00145` |
| #153 | revisão servindo no `estado-atual` | docs |
| #154 | negativas com acento e cobertura, `run_gaql` compacto | `00146-qv5` |

## O que foi medido

- **Remedição de 30 dias (05/10)**, por gestor, com o uso do Wellington à parte, porque ele mistura
  desenvolvimento e gestão. A Fase 2B não andou: o breakdown teve 1 chamada de gestor contra 190
  dos dois reports antigos. Detalhe em [`tool-buckets-2026-10-05.md`](tool-buckets-2026-10-05.md).
- **Apontamentos de campo da sessão "Gestor de Tráfego JP" (MO-JP):**
  - o Google não aplica variante próxima em negativa (acento é negativa distinta);
  - recomendação aceita à mão pelo app de celular sai no `change_event` como
    `GOOGLE_ADS_MOBILE_APP` com o e-mail do gestor, sem campo de origem. A aceitação pela web não
    foi medida.
- **O `run_gaql` devolve o `resource_name` de cada objeto da linha mesmo fora do SELECT.** O
  `compact` mediu −39% numa amostra de linhas de `campaign_criterion`.
- **Smoke do #154:**
  - repetida → `no_changes` (MO-JP, nada gravado);
  - acentuada nova gravada com o aviso e a sugestão, conferida no Google;
  - `compact` numa sessão nova.

## Método

- Código antes do plano, uma task por commit, plano gerado dos commits e reaplicado (árvore idêntica).
- Revisão final (Opus) e re-revisão (Sonnet), com 26 sabotagens de cópia ao final.
- Full sweep (Docker) duas vezes, porque o #154 mexe no pré-flight de um mutate.

## Pendente

- **Negativa de teste** `consulta nutricional grátis` (PHRASE) na campanha pausada
  `[3b.24.4] T5.3 - manual_cpc` da conta Rayane Ribeiro (critério `2385165706260`): remover ou
  deixar, a critério do Wellington.
- **Decisões abertas, sem dado que as peça agora:**
  - chamada `no_changes` do `add_negative_keywords` não deixa linha no `audit_log` (igual ao
    `update_ad_schedule`);
  - leitura prévia no `add_negatives_from_search_terms`;
  - `remove_negative_keywords` não confere se o critério é negativo.
- **~15/10:** remedir a Fase 2B com o plugin 0.5.0 (aplicado em 05/10).

## Lições operacionais

- **O vigia de PR confundia o CI com os runs "Dependabot Updates"**, que usam o mesmo commit do
  merge. Agora olha só o workflow `CI`.
- **Sessão MCP que continua depois de uma reconexão pode seguir com o catálogo antigo.** O
  parâmetro novo vai como texto e o servidor o recusa (`'true' is not of type 'boolean'`). Só a
  conversa nova destravou.
