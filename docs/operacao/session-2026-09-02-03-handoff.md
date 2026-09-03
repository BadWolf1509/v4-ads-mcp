# Sessão 2026-09-02/03 — Handoff (16 findings de campo → todos fechados)

> Dois dias, quatro PRs (#27–#30), dezesseis IDs (F131–F146), tudo em produção e cada deploy
> verificado em conta real. Este é o **mapa**; a enciclopédia é o
> [`findings-catalog.md`](findings-catalog.md), e o estado vivo é o
> [`estado-atual.md`](estado-atual.md). A origem foi uma sessão de campo (gestor de tráfego da
> MO-JP, outra sessão Claude) que trouxe cinco gaps com evidência de produção — e depois seguiu
> medindo: varredura de 23 contas, remoção real de campanha pela UI, confirmações independentes.

## TL;DR

| IDs | O quê | Onde fechou |
|---|---|---|
| **F131–F135** | `freshness` com duas fronteiras; `_RESOURCE_TYPES` com 13 divergências do enum; `audit_competitor_keywords` lê conversão | PR #27 (`38d890c`) |
| **F136** | `CONVERSION_ACTION` não existe no enum → membro morto removido, limite declarado | PR #27 — **e a description que escreveu passou a mentir; ver F145** |
| **F137 / F138** | 4 CVEs invisíveis por `continue-on-error`; commit só de docs deployava | PR #27 (`84c8720`, gate `code_changed`) |
| **F139 / F140** | `applied_count` conta o tentado → `changed_count`; tool nova só para sessão nova | PR #27 (`d359c69`) |
| **F142** | whitelist de `client_type` com plural inexistente e sem `_SUBSCRIPTION`; auto-apply invisível | `4ef50ee` direto na `main` |
| **F141 + F143 + F144** | `hoje` em UTC (25 contas UTC−3/−4); `atrasado` afirmava causa; `confiavel` afirmava cobertura | PR #28 (`c0f8e8a`) |
| **F145** | `structural_change` procurava `REMOVE`; remover campanha é `UPDATE` de status | PR #29 (`e5e1ac1`) |
| **F146** | `-03:00` fixo no import offline; 2 contas UTC−4 | PR #30 (`bcbb27c`) |

Também no #27: as tools **`get_assets`** e **`remove_asset_link`** (spec em
[`2026-09-02-ad-schedule-e-assets-design.md`](../superpowers/specs/2026-09-02-ad-schedule-e-assets-design.md)),
que fecharam o incidente originador — os 6 vínculos que ninguém enxergava aparecem numa chamada.

## O que mudou de contrato (para quem consome as tools)

- **`freshness.status`** (`get_change_history`, `detect_drift`): `confiavel | ambiguo | nao_coberto | em_curso | indeterminado`. `atrasado` **não existe mais**. Janela que alcança o dia corrente **da conta** nunca sai `confiavel`; janela além de hoje é `em_curso` antes de tudo; fronteira de ontem vence dia corrente (`nao_coberto`).
- **`old_status` / `new_status`** em cada change (CAMPAIGN/AD_GROUP; `None` nos demais). **`status_change_detected`** (medium) para `ENABLED↔PAUSED` por não-autorizado; `structural_change` (high) cobre `REMOVE` **ou** `status → REMOVED`.
- **`hoje` é o da conta** (`google_ads_accounts.time_zone`) em 24 tools Google: os 22 com preset + `get_budget_pacing` + `get_negative_keywords_audit`. `tzdata` virou dep de prod.
- **`import_offline_conversions`**: fuso da conta, resolvido no dry-run e guardado no token; preview traz `summary.time_zone` e `utc_offset`; conta sem fuso **recusa**; token sem fuso **recusa**.
- **`auto_applied_count` / `auto_apply_detected`** enxergam `GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION`; `GOOGLE_ADS_AUTOMATED_RULES` (plural) saiu do schema (a API o rejeita).
- ⚠️ **F140 vale para tudo acima:** schema e description novos só chegam a sessão MCP **reconectada**. O comportamento é do servidor.

## Como cada fix foi verificado — e vale repetir

1. **RED observado** antes de qualquer linha de produção (14, 13, 6 falhas nos três blocos). Em dois casos o RED **corrigiu o desenho**: uma janela futura sairia rotulada como "lag ou silêncio" (F144), e um controle no sentido errado revelou que eu tinha invertido a direção do bug de fuso (F146).
2. **Sabotagem por cópia** (nunca `git checkout`): 7/7, 7/7, 6/6 variantes — incluindo as que preservam o invariante *fácil* (`len == 15`) e quebram o *difícil*, e as que um guard de contagem ou um `pytest.raises(TypeError)` deixariam passar.
3. **Teste de integração com DB** para o caminho real do fuso (Docker estava de pé; `pytest -m integration` local ~30 s).
4. **Prova viva por PR**, em conta real, com o mesmo evento antes/depois: Camaçari (`auto_applied_count` 0→1; `atrasado`→`nao_coberto`), campanha `23861545627` (`flags: []`→`structural_change PAUSED->REMOVED`), dry-run offline na `1163862076` (`America/Recife`, `-03:00`, token não aplicado).
5. **Gate do F138 confirmado 4×** ao vivo: docs → `deploy: skipped`; código → `success`.

## O que eu errei, e o que pegou

- **Guard aplicado à instância, não à classe** (F142): o F136 cruzou uma whitelist com o enum do SDK e não estendeu ao enum ao lado, no mesmo arquivo. Modo 9 da memória do agente sobre guards que não cobrem.
- **Assere o adjacente à invariante, quarta vez**: `pytest.raises(TypeError)` satisfeito por um `None - timedelta`. A invariante "sem default" se assere pela **assinatura**.
- **Direção de bug de fuso afirmada sem probe** (F146): o `-03:00` fixo *adiantava* o carimbo, não atrasava. O teste com controle falhou — e a falha era o meu registro.
- **Recomendar sem ler o vizinho**: sugeri derivar a whitelist do SDK; o guard irmão documentava por que produção **não** deriva (contrato público).
- **A ausência era o achado** (F145): "zero `REMOVE` de CAMPAIGN em 23 contas" foi lido como raridade; era impossibilidade — o par (tipo, operação) não ocorre.

## Regras que entraram no `CLAUDE.md`

Relógio do servidor em tool Google (F141); `REMOVE` em entidade com `status` (F145); fuso hardcoded em mutate (F146); pipe entre o gate e o `&&`; guard que assere o adjacente. Cada uma com o finding que a motivou.

## Onde olhar

- Fuso e `hoje`: [`account_clock.py`](../../src/google_ads/account_clock.py), [`queries/_common.py`](../../src/google_ads/queries/_common.py) (`account_today`), guard AST [`test_no_server_clock_in_google_tools.py`](../../tests/unit/test_no_server_clock_in_google_tools.py).
- Freshness: [`change_freshness.py`](../../src/google_ads/change_freshness.py) — a **ordem** dos status é contrato e está na docstring.
- Drift: [`drift_detection.py`](../../src/google_ads/drift_detection.py) (`AUTO_APPLY_CLIENT_TYPES`, predicado estrutural, `_transicoes`), [`get_change_history.py`](../../src/mcp/tools/get_change_history.py) (`_status_transition`, keyed por tipo).
- Upload offline: [`conversions.py`](../../src/google_ads/conversions.py) (`_utc_offset`, recusa sem `__time_zone__`), [`import_offline_conversions.py`](../../src/mcp/tools/import_offline_conversions.py).
- Guards de enum: `test_change_event_enum_guards.py` e `test_change_client_type_guards.py` — **produção não deriva do SDK de propósito**; o CI reconcilia.
- Stub do relógio para testes sem pool: `tests/conftest.py` (`_relogio_da_conta_stubado`).

## O que ficou de fora, com motivo

- **Generalizar `old_status`/`new_status`** a todo tipo com `status` (keyword, anúncio): útil, outra pergunta.
- **Probe real de upload offline**: mesma forma de string que já funciona; um upload real empurraria conversão falsa em conta de cliente.
- **`change_status` como desambiguador de lag vs. silêncio**: única saída real para o F143 além do rótulo honesto; custa segunda consulta e dependência nova. Não entra sem necessidade demonstrada.
- **Tools Meta e `rate_limit._today()`** ficaram em UTC de propósito (fuso próprio no inventário Meta; bucket de quota).
- **Nota sem ID:** o classificador de blast radius não conhece `import_offline_conversions` e cai no *default seguro: confirmar* — correto, texto feio. Entra com o F112.

## Próximo

Operacional, do Wellington: **1c** (virar `META_RECONCILE_APPLY` — o contador avançou durante o soak; a revogação vem na primeira execução após a chave) e **11** (system user com `MANAGE` em 24 contas; testar em uma). Produto: **`ad_schedule`** (spec pronta; a §4.2 manda levantar a conjunta dia × hora na implementação, e a inversão de CPA do fim de semana derrubou a premissa original) ou **M.5**. Pendente pequeno: **T2** do runbook 3b.41 (o único ramo `filter_active=True` sem execução real).
