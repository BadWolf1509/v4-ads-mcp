# Sessão de 30/10, tarde — Handoff (varredura de correções, 6 blocos)

> Mapa da sessão. Estado vivo no [`estado-atual`](estado-atual.md); defeitos no
> [catálogo](findings-catalog.md). Anterior: [`session-2026-10-30-handoff.md`](session-2026-10-30-handoff.md).
> Plano: [`2026-10-30-varredura-correcoes.md`](../superpowers/plans/2026-10-30-varredura-correcoes.md).

## O que entrou

| PR | bloco | o quê | produção |
|---|---|---|---|
| #174 | 1 · OAuth | refresh fora do event loop; OAuth ausente/revogado/transitório com orientação certa; `state` preso ao navegador por nonce em cookie; `verified_email=False` recusado; `/docs` e `/openapi.json` desligados | `00155-flr` |
| #175 | 2 · restore e job bloqueado | restore executável (ordem de FK, uma transação, `setval` do `audit_log`, `--confirmar-host`, destino vazio); COPY do backup sem o `command_timeout` de 30 s; reconciliação bloqueada ou piggyback Meta quebrado saem com exit 1 e acionam o alerta | `00156-2lh` |
| #176 | 3 · governança de mutação | micros sem truncar (helper único, guard por AST); `had_effect` no audit; upload de conversões conta aceitas e recusadas; `primary_for_goal` exige confirmação; `dismiss_recommendation` presa à conta; telefone com DDI sem `+` | `00157-n24` |
| #177 | 4 · Meta v25 | Graph em `v25.0` numa constante; `x-ad-api-version-warning` vira `log.error` e alerta; erro também conta no BUC; código 80000; mensagens do Modelo B | `00158-bxt` |
| #178 | 5 · deps e deploy | `facebook-business` (morto) sai com `aiohttp` e `multidict`; `certifi`, `pyjwt`, `opentelemetry-api` sobem; Actions por SHA; `resync` e `backup` só recebem a imagem após o smoke; deploy pulado em silêncio fechado; rollback sem `|| true`; guard de migration destrutiva | `00159-2zs` |
| #184 | 6 · painel e contratos + este fecho | números do painel; confirmação de desativar/promover; matriz de acesso idempotente; textos, hora de Brasília e contraste; enums e descriptions das tools; achados da revisão final | deploya ao mesclar: **revisão seguinte à `00159-2zs`, conferir** |

Medido: leitura Meta real após o #177 sem aviso de versão; o pipeline novo rodou no #178 (smoke, rollback
pulado, jobs na imagem nova). **Não medido:** login real e convite (primeira pendência abaixo).

## Decisões do Wellington

- **`primary_for_goal` exige confirmação**, qualquer valor, em `update_conversion_action`.
- **`dismiss_recommendation` corrigida sem teste real:** a recusa de recomendação de outra conta tem
  teste unitário, mas nenhuma chamada real ao Google foi feita.
- **As 45 recusas do Pedro ficam fora do plano** (Google `4493906974` e Meta `act_4051924171730156`,
  07/10 a 27/10): decisão no painel, não código.

## Rulings (provisórios, do ledger)

- Plano versionado no bloco 1 (a branch 1 é a primeira) — baixo.
- `RefreshError` transitório não diz "revogada": só `invalid_grant` manda reconectar — baixo custo se errado.
- Revisão ampla da branch só ao fim dos 6 blocos; cada bloco passa por revisão por task e full sweep
  antes do merge, e os blocos deployam em sequência — se errado, defeito cruzado chega à produção e sai por fix forward.
- `account_overview.py:114` ("Reconectar via /admin") corrigido no bloco 6, junto dos textos: mesmo erro do Modelo B.
- Deploy pulado fechado por **reconciliação** no `detectar_mudanca` (só confia no `before` se a run dele
  concluiu com sucesso; senão fail-open e deploya), não por grupo por SHA nem `queue:max` — um deploy a mais é o custo se errado.
- Dropdown do gestor só oferece o toggle quando ele muda o estado real (nada com status inativo, com aviso
  "Inativo por status"): o F84 proíbe sincronizar as colunas.

## Pendente (nesta ordem)

1. **Rodar: login real no painel e convite.** O `state` com nonce em cookie e a recusa de
   `verified_email=False` nunca viram um Google de verdade. Fazer logo após o deploy do #184.
2. **Alertas do Dependabot**: ajuste do repositório, feito por você.
3. **Aplicar as correções do plugin**: [`plugin-correcoes-2026-10-30.md`](plugin-correcoes-2026-10-30.md)
   (a fonte não está no disco). Resta `v4-brand:43` do `null`.
4. **`hd` do login Google sem conferência** (herdado do Task 3, decisão sua): hoje a trava é o e-mail
   verificado + a lista de gestores, não o domínio hospedado.
5. **Conferir a revisão que o #184 gera** e, se a run mostrou o `migrate`/jobs na imagem nova, fechar.
6. Decisão do Pedro: ver acima.

## O que ficou fora

**Fora deste plano** (motivo):
- As 45 recusas do Pedro: decisão no painel.
- Alertas do Dependabot: ajuste do repositório, feito pelo Wellington.
- Rotação da `aes-master-key` e `associated_data`: precisa recifrar tokens, frente própria.
- CSP (`base-uri`, `object-src`, `form-action`) e HTMX local: frente do painel, com teste em navegador.
- `run_gaql` lendo no stream: preventivo, sem pressão medida (pico de 50% de memória). Mexe no executor mais usado, desenho próprio.
- Buckets, descriptions e Fase 2B: dependem da remedição de uso.
- `mcp` 2.x e `google-ads` novos: frente própria, com smoke de handshake.
- Hipóteses não medidas: atribuição mista na Meta, conta `CANCELED` no inventário, 2635 como subcode, `objectCreator`.
- `add_keywords` sem teto de lance: baixo, pede decisão de produto.
- Reativar gestor revive Bearer, `/logout` no servidor, invite sem conferir e-mail: baixos, próxima rodada de auth.

**Minors deferidos nas revisões** (ledger):
- Task 2: o teste de "sem OAuth" não exercita o raise; import duplo em `client.py`.
- Task 3: `invalid_client`/`invalid_scope` caíam em "temporário" (`invalid_client`/`unauthorized_client` corrigidos no fecho; `invalid_scope` segue); `hd` sem conferência.
- Task 4: host `<desconhecido>` vira trava só digitada; porta e banco fora da comparação.
- Tasks 6-10: número estrangeiro sem `+` segue com `+55`; `apply_change` sem recheck em orçamento/lance não verificado.
- Tasks 11-13: sem teto em `_avisos_vistos`; o guard da versão do Graph generalizado no fecho.
- Tasks 18-20: `confirm` sempre `kind danger`; toast "já estava" como success; import local em `sessions.py`.
- Tasks 21-22: `audit_detail` traduzia `denied` (corrigido no fecho); comentário de 13 categorias (corrigido: 13 criáveis, 17 auditáveis).

**Por desenho:** upload de conversões 100% recusado aparece como `error` no painel (audit) enquanto a
resposta ao gestor continua `applied`. A resposta não mudou; o audit passou a dizer a verdade.

## Textos prontos para `/findings-add`

(Sem numerar: o `/findings-add` é do Wellington. Nenhum defeito abaixo tem guard contra a classe inteira, salvo onde dito.)

1. **(MEDIUM, corrigido 30/10, #174)** Refresh do OAuth do Google rodava síncrono dentro do event loop
   (travava todas as chamadas do worker durante a ida ao Google). Agora via `run_blocking`, com guard.
   Fora: nenhum guard varre outras chamadas síncronas do SDK no loop.
2. **(MEDIUM, corrigido 30/10, #174)** OAuth ausente, revogado ou com falha transitória chegava ao gestor
   como "Erro interno"/orientação errada ("reconecte" para erro de rede). Só `invalid_grant` orienta
   reconectar, e aponta o painel. Fora: `invalid_scope` segue como temporário.
3. **(HIGH, corrigido 30/10, #174)** Login OAuth sem `state` preso ao navegador (login CSRF) e sem recusar
   `verified_email=False`; `/docs` e `/openapi.json` expostos. Nonce em cookie, e-mail não verificado
   recusado. Fora: `hd` sem conferência (decisão do Wellington); smoke com Google real não feito.
4. **(HIGH, corrigido 30/10, #175)** Runbook de restore nunca executado: o INSERT seguinte ao restore dava
   `UniqueViolationError` porque a sequence do `audit_log` não era recolocada. Restore agora é módulo
   (`src/jobs/restore.py`), na ordem de FK, em uma transação, com `setval`, `--confirmar-host` e destino
   vazio. Fora: testado em Postgres 16 (testcontainer), não no Supabase; porta e banco fora da comparação.
5. **(MEDIUM, corrigido 30/10, #175)** Reconciliação bloqueada (e crash do piggyback Meta) saía com exit 0:
   a policy de job falho, a única que vê o job, nunca disparava. Agora exit 1 depois de upsert, audit e
   purge; `maxRetries=3` dá até 4 execuções/dia (um e-mail). Também: o COPY do backup herdava o
   `command_timeout` de 30 s. Fora: nenhum guard cobre exit code dos outros jobs.
6. **(MEDIUM, corrigido 30/10, #176)** Micros truncados: R$ 2,01 era enviado como 2.009.999 (float, `int()`
   sem arredondar), e o preview divergia do payload. `brl_para_micros` único, com guard por AST; `percent_off`
   também. Fora: outros caminhos de conversão para micros fora dos arquivos que o AST varre.
7. **(MEDIUM, corrigido 30/10, #176)** `audit_log` das mutações MCP não dizia se houve efeito
   (`had_effect`); o upload de conversões não contava recusas — 100% de recusa saía como sucesso.
   Agora `had_effect` gravado, aceitas e recusadas contadas, 100% recusa vira `error` com motivo; contagem
   incompleta é não medida, não zero. Fora: `apply_change` sem recheck de orçamento/lance não verificado.
8. **(HIGH, corrigido 30/10, #176 e #184)** `update_conversion_action` mudava `primary_for_goal` (meta de
   lance do Smart Bidding) sem confirmação; `dismiss_recommendation` aceitava `resource_name` de outra
   conta (e, achado na revisão final, `apply_recommendation` também). Agora CONFIRM para qualquer
   `primary_for_goal` e recusa por prefixo `customers/<id>/`. Fora: `dismiss` sem teste real contra o Google.
9. **(MEDIUM, corrigido 30/10, #176)** Customer Match: telefone com DDI sem `+` (ex.: `5583…`) era tratado
   como nacional e recebia `+55` de novo, gerando hash errado, sem confundir com DDD 55. Fora: número
   estrangeiro sem `+` segue com `+55`.
10. **(HIGH, corrigido 30/10, #177)** Graph pinada em `v22.0`, expirada na Marketing API em 19/02/2026: a
    Meta fazia auto-upgrade em silêncio. Agora `v25.0` numa constante; `x-ad-api-version-warning` vira
    `log.error` (uma vez por texto) e alerta; chamada com erro também conta no BUC; código 80000 é limite;
    mensagens do Modelo B. Fora: sem teto em `_avisos_vistos`; sem verificação automática da data de sunset.
11. **(MEDIUM, corrigido 30/10, #178)** Pipeline de deploy: `resync` e `backup` recebiam a imagem antes do
    smoke; deploy podia ser pulado em silêncio quando o `before` não tinha rodado; a captura da revisão do
    rollback tinha `|| true`; Actions por tag mutável. Agora jobs só após smoke verde, `detectar_mudanca`
    confia no `before` só se a run dele concluiu com sucesso (senão fail-open), Actions por SHA com guard.
    Fora: nenhuma verificação em `deploy.yml` por execução real além da run do #178.
12. **(LOW, corrigido 30/10, #178)** `facebook-business` morto desde o F190 seguia como dependência (com
    `aiohttp` e `multidict`); `certifi`, `pyjwt`, `opentelemetry-api` desatualizados. `pip-audit` limpo.
    Mais um guard contra migration destrutiva acima da 011. Fora: `mcp` 2.x e `google-ads` novos.
13. **(MEDIUM, corrigido 30/10, #184)** Painel: "Quota MCP hoje" contava a mutação em dobro
    (`developer_token_id NOT LIKE 'mgr:%'`); gestor `is_active=False` aparecia ativo; série de 30 dias sem
    zeros nos dias vazios; dia em UTC em vez de `America/Sao_Paulo`. Fora: o F84 proíbe sincronizar as
    colunas de status.
14. **(MEDIUM, corrigido 30/10, #184)** Matriz de acesso decidia pelo estado do banco: aba velha invertia o
    acesso, e o toast lia `el.checked`. Agora o checkbox envia `desejado=grant|revoke`; pedido igual ao
    estado atual não muda nada nem grava audit; sem `desejado` → 422. Desativar e promover/despromover
    gestor passam a pedir confirmação. Fora: `confirm` sempre `kind danger`; toast "já estava" como success.
15. **(LOW, corrigido 30/10, #184)** Textos falsos e hora do painel: `strftime` em UTC, "Reconectar via
    /admin" (Modelo B), aviso de `meta_connected` ausente, `text-v4-green` com contraste insuficiente em
    texto pequeno; `denied` não traduzido no detalhe do audit; numerador Meta sem filtrar conta ativa.
    Fora: comentário de categorias.
16. **(LOW, corrigido 30/10, #184)** Contratos das tools: o enum de `audit_orphan_smart_actions` e
    `audit_goal_attribution` não tinha `PHONE_CALL_LEAD`, `ADD_TO_CART`, `BEGIN_CHECKOUT`, `SUBSCRIBE_PAID`;
    `validate_gaql` dizia "sem consumir quota" (consome 1 operação); token de "8 caracteres"; `raw_grid`
    "blocos nomeados"; `remove_audience` sem avisar que audiência de campanha não vem de
    `get_audience_performance`. Constante única, guard `test_contratos_enum`. Fora: buckets e descriptions
    dependem da remedição de uso.
