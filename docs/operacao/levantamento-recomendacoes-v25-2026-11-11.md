# Levantamento K1 (11/11) — tipos de recomendação novos do Google Ads API v25

> Task K1 do [plano de 10/11](../superpowers/plans/2026-11-10-varredura-refatoracao.md). **A decisão da whitelist é do Wellington**; nada foi alterado no código. Origem: agente só de leitura, 11/11.

Somente leitura. Nada no repositório foi alterado. SDK medido: `google-ads 33.0.0` (venv do projeto; `pyproject.toml` exige `>=33.0.0`; `_DEFAULT_VERSION` do client = `v25`).

## 1. Diff do enum v24 -> v25 (medido)

Comando: `.venv/Scripts/python.exe` importando `google.ads.googleads.{v24,v25}.enums.types.recommendation_type.RecommendationTypeEnum` e comparando `{nome: valor}`.

- v24: 56 membros. v25: 59 membros.
- Adicionados (3, a crença do projeto bate): `CAMPAIGN_SPECIFIC_APP_GOAL` (59), `RAISE_TARGET_CPA_PERFORMANCE_BID_TOO_LOW` (61), `LOWER_TARGET_ROAS_PERFORMANCE_BID_TOO_LOW` (62).
- Removidos: nenhum. Renumerados: nenhum. O número 60 não existe no v25 (lacuna; não sei dizer por quê, não confirmado).
- Mensagem `Recommendation` (v24 -> v25): 3 campos novos no oneof, um por tipo (`campaign_specific_app_goal_recommendation`, `raise_target_cpa_performance_bid_too_low_recommendation`, `lower_target_roas_performance_bid_too_low_recommendation`); nenhum removido.
- `ApplyRecommendationOperation` (v24 -> v25): 2 campos novos em `apply_parameters`: `raise_target_cpa_performance_bid_too_low` e `lower_target_roas_performance_bid_too_low`. **`CAMPAIGN_SPECIFIC_APP_GOAL` não tem parâmetro de apply no proto.**

## 2. Por tipo

### RAISE_TARGET_CPA_PERFORMANCE_BID_TOO_LOW (61)
- Payload (SDK): `recommended_target_multiplier` (double, >1.0) e `current_average_target_cpa_micros`.
- Apply: `RaiseTargetCpaPerformanceBidTooLowParameters.target_cpa_multiplier` (obrigatório, >1.0) = fator de aumento do target CPA. Muda o target CPA da campanha de Search (alavanca de lance já existente). Release notes v25.2 (2026-09-23): "raise Target CPA when bids are too low for Search campaigns to enter auctions".
- Pode iniciar/aumentar gasto: **sim, indiretamente** — subir o target CPA deixa o Smart Bidding lançar mais alto e entrar em mais leilões; não mexe no orçamento diário, mas o gasto sobe até o teto do orçamento.
- Risco: **alto** para conta de cliente (mexe em lance/meta de eficiência; o multiplicador vem do Google e o valor final em R$ não está no payload, só o fator + o atual).
- Reversibilidade: o valor volta com `update_campaign_bidding`/edição manual (é um número de target), mas a janela de aprendizado do Smart Bidding e o gasto já feito não voltam. Docs não dizem se a apply é revertível ("não confirmado"); o irmão v24 `RAISE_TARGET_CPA_BID_TOO_LOW` é documentado como assíncrono (minutos) — para este não confirmado.
- Toca bidding: sim. Conversões/assets: não.
- Docs: https://developers.google.com/google-ads/api/docs/release-notes (v25.2) · https://developers.google.com/google-ads/api/reference/rpc/v25/RecommendationTypeEnum.RecommendationType ("raise target CPA when it is too low for Search campaigns") · https://developers.google.com/google-ads/api/reference/rpc/v25/ApplyRecommendationOperation (campo existe; página não detalha os campos — os campos acima vêm do SDK).

### LOWER_TARGET_ROAS_PERFORMANCE_BID_TOO_LOW (62)
- Payload (SDK): `recommended_target_multiplier` (double, <1.0) e `current_average_target_roas`.
- Apply: `LowerTargetRoasPerformanceBidTooLowParameters.target_roas_multiplier` (obrigatório, <1.0). Baixa o target ROAS (afrouxa a meta de retorno) em campanha de Search.
- Pode aumentar gasto: **sim, indiretamente**, mesma lógica (meta mais frouxa -> mais leilões, ROAS realizado tende a cair). Orçamento diário não muda.
- Risco: **alto** (afrouxa a meta de retorno do cliente; efeito direto em ROAS/CPA).
- Reversibilidade: igual ao anterior — número de target, reeditável; efeito já gasto não volta. Revertibilidade da apply: não confirmado.
- Toca bidding: sim. Conversões/assets: não.
- Docs: mesmas URLs acima (v25.2, 2026-09-23).

### CAMPAIGN_SPECIFIC_APP_GOAL (59)
- Payload (SDK): custo/conversões dos últimos 15 dias, projeções, `suggested_conversion_goals` (categorias de conversão), `current_conversion_goals`, `current_custom_conversion_goal`, e campos deprecated (`app_conversion_goals`, `current_auto_goals`...).
- Apply: **não há `apply_parameters` no `ApplyRecommendationOperation` do v25** (medido no SDK e conferido na página da doc, que não o menciona). Pelo que mostra o proto, a apply por API desse tipo não tem parâmetro dedicado; se `ApplyRecommendation` o aceita sem parâmetros ou rejeita: **não medido / não confirmado**.
- Natureza: adicionar meta de conversão de app específica da campanha — mexe em **conversões/metas** da campanha (afeta o que o Smart Bidding otimiza), não em orçamento/lance diretamente. Só faz sentido para campanhas de app; improvável em contas de Search de clientes V4.
- Risco: **médio** (altera objetivo de otimização; baixa probabilidade de aparecer em conta de Search).
- Reversibilidade: não confirmado.
- Docs: https://developers.google.com/google-ads/api/docs/release-notes (v25.1, 2026-08-19: "Suggests adding a campaign-specific app conversion goal") · https://developers.google.com/google-ads/api/reference/rpc/v25/RecommendationTypeEnum.RecommendationType.

Lacuna de linha do tempo (da doc de release notes): o campo de CAMPAIGN_SPECIFIC_APP_GOAL entrou no v25.1 (19/08/2026), os dois de bid-too-low no v25.2 (23/09/2026). A seção do v25 major (22/07/2026) estava truncada na página lida; o v26 (14/10) e v26.1 (28/10) não os mencionam (lido só até ~100k de 171k caracteres).

## 3. Como o código trata hoje e o que muda com um import bump

Arquivos: `src/google_ads/queries/recommendations.py`, `src/governance/blast_radius.py` (~L257-315), `src/mcp/tools/apply_recommendation.py` (~L245, L195-275), `tests/unit/test_whitelist_de_recomendacao_bate_com_o_proto.py`.

Estado atual (import `v24`, L151):
- `get_recommendations`: a query é `WHERE recommendation.dismissed = false` sem filtro de tipo — tipo novo **aparece** na lista (o runtime usa SDK 33/API v25, então o servidor devolve os 3). Os campos de detalhe vêm só de `CAMPOS_DE_DETALHE` (23 tipos); os 3 novos não têm detalhe (sem valores).
- Não existe whitelist "aplicável": existem três conjuntos: `CAMPOS_DE_DETALHE` -> `TIPOS_QUE_CONFIRMAM` (23), `TIPOS_DE_MIGRACAO` (5) e `TIPOS_CONHECIDOS` (todos os membros do enum v24 exceto UNSPECIFIED/UNKNOWN).
- `blast_radius` para `apply_recommendation`: migração -> CONFIRM; em `TIPOS_QUE_CONFIRMAM` -> CONFIRM; **`tipo not in TIPOS_CONHECIDOS` -> CONFIRM** ("tipo que o SDK v24 nao conhece"); resto -> AUTO. Logo, **hoje os 3 novos caem em CONFIRM** (por desconhecidos), e o preview em `apply_recommendation.py` mostra o aviso "tipo que esta versao do SDK (v24) nao conhece ... confira no painel". É comportamento seguro. Medido por leitura de código; não executei a tool.
- Não achei código específico para os 3 tipos (grep por nome: nenhum).

Se o import mudar para v25 sem atualizar tabelas:
- `TIPOS_CONHECIDOS` passa a ter 59 - 2 = 57 membros (os 3 novos entram).
- Os 3 deixam de ser "desconhecidos" e, como não estão em `CAMPOS_DE_DETALHE`/`TIPOS_DE_MIGRACAO`, caem no ramo final: **AUTO, "nao mexe em orcamento nem lance"**. Para os dois `*_BID_TOO_LOW` isso é **falso** (mexem em target CPA/ROAS) — apply sem token de confirmação e sem preview do valor. É exatamente a regressão que o código já descreve (07/09). Também o resumo perde o aviso de "tipo desconhecido".
- O guard `test_whitelist_de_recomendacao_bate_com_o_proto.py` importa `v24` em 4 pontos (L40-44) e tem `assert len(TIPOS_CONHECIDOS) >= 54`; se só o `recommendations.py` migrar e o teste ficar em v24, o guard compara descritor v24 com tipos v25 (`faltando` em L210 acusaria os 3 por falta de `*_recommendation` no proto v24) e falha, o que é o comportamento desejado de alarme; se o teste migrar junto, o eixo 1 derivado do proto deveria pegar os 2 bid-too-low (campos `*target_multiplier`, `*average_target_cpa_micros`/`*average_target_roas`), mas a lista `CAMPOS_DE_DETALHE` precisa entrada escrita à mão (não medido: não rodei o guard com v25).
- Observação: `current_average_target_roas` não casa com o padrão `*target_roas` do critério do eixo 1 (termina em `_roas` precedido de `average_target`); o critério em prosa lista `*average_target_micros`, que não casa com `current_average_target_cpa_micros` por sufixo. Não medido se o guard derivado captura esses dois campos — rever antes de migrar.

## 4. Recomendação (decisão é do dono)

| Tipo | Opção sugerida | Motivo |
|---|---|---|
| RAISE_TARGET_CPA_PERFORMANCE_BID_TOO_LOW | incluir na whitelist (CONFIRM, com detalhe: fator + target atual) | mexe em lance; precisa de preview com o multiplicador e o CPA atual; nunca AUTO |
| LOWER_TARGET_ROAS_PERFORMANCE_BID_TOO_LOW | incluir na whitelist (CONFIRM, com detalhe: fator + ROAS atual) | idem, afrouxa a meta de retorno do cliente |
| CAMPAIGN_SPECIFIC_APP_GOAL | incluir só leitura (listar; apply bloqueado/CONFIRM com aviso) | sem parâmetro de apply no proto, mexe em metas de conversão, irrelevante para contas de Search; custo/benefício baixo |

Qualquer que seja a escolha, o import para v25 só deve entrar junto com as entradas dos 3 tipos (ou com os 2 de lance em `CAMPOS_DE_DETALHE` e o terceiro tratado explicitamente), para que nenhum caia no AUTO.

## 5. O que não medi

- Não chamei a API real: não sei se o servidor já devolve os 3 tipos em contas V4 (nem se aparecem com frequência).
- Não confirmei se a apply de `CAMPAIGN_SPECIFIC_APP_GOAL` é aceita/rejeitada sem parâmetro, nem a revertibilidade de nenhuma das 3 por doc.
- A doc não detalha os campos dos `*Parameters` (os li do SDK) nem diz se a apply dos 2 de lance é assíncrona.
- Não rodei a suíte nem o guard com import v25; o comportamento descrito em 3 vem de leitura do código (sem sabotagem/execução).
- Release notes: li ~100k de 171k caracteres (seção do v25 major truncada); o número 60 ausente no enum não foi explicado.
