# Sessão de 15–17/11 — Handoff (faxina P0–P6, revogação na desativação, F212–F215)

> Desenho: [`2026-11-15-revogacao-na-desativacao-design.md`](../superpowers/specs/2026-11-15-revogacao-na-desativacao-design.md) ·
> Plano: [`2026-11-15-revogacao-na-desativacao.md`](../superpowers/plans/2026-11-15-revogacao-na-desativacao.md).
> Anterior: [`session-2026-11-15-handoff.md`](session-2026-11-15-handoff.md).

## Origem

A sessão começou com a faxina de 15/11 (P0–P6). Depois veio "analise e liste a melhor sequência", e o
Wellington mandou executar os 7 itens com aval nominal por menu em cada passo que escreve:

1. dry-run de mutação depois do P5/P6;
2. renovar o `SMOKE_MCP_BEARER`;
3. `/findings-add`;
4. gestores desativados com grants vivos;
5. minors da faxina;
6. medir o uso das tools em 02/12;
7. as decisões abertas dele.

## O que entrou em produção

| PR | o quê |
|---|---|
| [#264](https://github.com/BadWolf1509/v4-ads-mcp/pull/264)–[#270](https://github.com/BadWolf1509/v4-ads-mcp/pull/270) | faxina P0–P6 (lista no `estado-atual`) |
| [#271](https://github.com/BadWolf1509/v4-ads-mcp/pull/271) | `estado-atual` da faxina |
| [#272](https://github.com/BadWolf1509/v4-ads-mcp/pull/272) | minors da faxina: guard do P6 por executor (controle de total = 6), 2 testes de cancelamento, `ctx_mcp` e `fake_google_client` num lugar comum a unit e integração |
| [#273](https://github.com/BadWolf1509/v4-ads-mcp/pull/273) | F212–F215 no catálogo |
| [#274](https://github.com/BadWolf1509/v4-ads-mcp/pull/274) | **revogação na desativação** (F213), revisão `v4-ads-mcp-00226-5p4` |
| [#280](https://github.com/BadWolf1509/v4-ads-mcp/pull/280) | F213 fechado no catálogo com o ciclo medido |
| este PR | trava `MANAGER_OFFBOARDING_APPLY=true` no `deploy.yml`; este handoff |

## Revogação na desativação: contrato

- **Padrão:** deprovisionamento JML com revogação soft e motivo (`manager_deactivated`), em dois caminhos
  sobre a mesma função do repositório: a rota `toggle-active`, na hora, e a etapa `_etapa_gestores` do
  `account_resync`, por estado.
- **Regra dos motivos:** o motivo nomeia o que bloqueia agora. Com dois bloqueios (conta fora e gestor
  desativado), vale o da conta.
- **Reativar** devolve só `manager_deactivated`. Revogação de admin e churn não voltam por esse caminho.
- **Volta de conta** ao MCC ou à parceria não reabre grant de gestor desativado; as filas do painel
  contam só o que o Restaurar devolve.
- **Job:** Google → Meta → gestores → purge, também no caminho sem OAuth. `FOR SHARE` em `managers`
  fecha a corrida com o `FOR UPDATE` da rota. Com a trava desligada, só audita
  (`manager_offboarding_reconcile`, com contagens e ids).

## Medido nesta sessão

- **Dry-run de mutação depois do P5/P6:** `update_ad_status`, 6 anúncios ENABLED→ENABLED, token não
  aplicado (audit 11270). A `update_campaign_status` não serviu: aplica direto até 5 itens.
- **Ciclo no painel (15/11, `00226-5p4`):** Desativar → Reativar no luizfelipe, 29 s sem acesso. 24
  Google + 26 Meta revogados e devolvidos; o 1 `left_mcc` e os 3 `partnership_ended` ficaram revogados
  (audits 11272/11273). `tests/browser` verde (4), mas com rota falsa: prova o botão, não a revogação.
- **Plano do job (15/11, transação só de leitura) e as 2 rodadas com `apply: false`** (16 e 17/11,
  audits 11377/11378 e 11522/11523): 48 Google + 47 Meta, só de lucassoares e pedro.vytor, 0 a
  restaurar ou remarcar. Bateram entre si.

**Não medido:**
- o texto do toast em produção;
- se algum caminho fora das três entradas lê grant de gestor desativado (com a trava ligada, a pergunta
  perde o objeto).

## Próximo

1. ~~Ler o `manager_offboarding_reconcile` com `apply: true`~~ **feito em 17/11:** revisão `00227-7th`
   com a trava no job; execução manual `v4-ads-mcp-resync-sk5h7` (sucesso, aval nominal) revogou 48
   Google + 47 Meta (audits 11628/11629), os 2 desativados ficaram com 0 grants vivos e nenhum ativo foi
   tocado. Google e Meta reconcile na mesma execução: 0 revogados. Exit code das rodadas de 15–17/11:
   sucesso (`gcloud`).
2. **Item 2, bearer do smoke (F186):** só nasce em `/sessions` pela UI; fica com o Wellington.
3. **Item 6:** em 02/12, `scripts/medir_uso_tools.py --dias 90` para a decisão do teste de 30 dias.
4. **Decisões do Wellington:**
   - SQL de conversão repetido nos dois `restore_for_account`: estender `test_rotas_usam_run_with_reconnect`
     para levar ao núcleo, ou comparar os gêmeos por AST;
   - `restaurar_churn_da_conta` está em `_GEMEOS_EXCLUIDOS` em vez de comparada por bind registrado.

## Minors adiados (dos ledgers SDD, que foram apagados)

**Revogação na desativação:**
- `restore_for_account` não trava `managers`: a corrida residual deixa grant vivo de desativado, que só
  a trava converge.
- `CASE a.is_active` em revogar pode gravar churn numa conta que acabou de voltar (a fila e um clique
  resolvem); a linha de churn de desativado em conta que voltou fica até um clique depois da reativação.
- Toast "Gestor reativado" para gestor com `status='inactive'`, que segue desativado.
- Audit da rota grava `platform='google'` numa ação que mexe nas duas plataformas.
- `FOR SHARE` em todos os gestores roda também com a trava desligada.
- `contagens` como `dict[str, Any]` (por causa do `**summary`).
- A coluna "revogados" da fila `saiu_da_parceria` deixa de contar churn de desativado nas contas inativas.
- Atomicidade da rota só testada no sentido desativar; falta teste de idempotência do
  `restore_for_account`; o núcleo aceita qualquer `motivo_churn` sem conferir o lado.
- Cosméticos: parênteses sobrando no teste, docstring de `planejar_convergencia`, `revoked_at` herdado
  no restore.

**Minors da faxina (#272):**
- `_executores_sem_encerramento` aceita um `def` declarado dentro do `finally`
  (`test_structural_guards.py`), e falta o caso sintético "finally de closure irmã não conta".
- `falha_audit`/`falha_record_actual` anotados `Exception | None` recebem `CancelledError`: o mypy de
  `tests` acusa 2 `[assignment]` (o gate só roda mypy em `src`).

**Observado, não investigado:** `update_*_status` ainda emite token para pedido igual ao status atual
(o `update_rsa` tira do token desde o #260).
