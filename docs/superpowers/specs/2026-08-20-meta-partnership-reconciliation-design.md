# Reconciliação da parceria Meta — entrada e saída automáticas

> **Status:** desenho aprovado em 2026-08-20, aguardando plano de implementação.
> **Origem:** o gestor reportou que `Mestre da Obra Petrolina` saiu da parceria com a
> V4 Lima Soares e continuava no MCP. A investigação virou o **F128**, cujo fix
> (contador de ausências) fechou o sintoma. Esta spec ataca a causa: o MCP **infere**
> o estado da parceria em vez de **consultá-lo**.

---

## 1. O problema

O inventário Meta é construído a partir de `/me/adaccounts` — a lista de contas às quais
o **system user está atribuído**. Isso confunde duas condições diferentes:

| Realidade | Como o MCP enxerga hoje |
|---|---|
| a unidade saiu da parceria | conta some de `/me/adaccounts` |
| a unidade está na parceria, mas ninguém atribuiu o SU à conta | conta some de `/me/adaccounts` |

As duas produzem o mesmo sintoma — ausência, e `#200` se alguém tentar usar. Como são
indistinguíveis, o sistema não pode agir com segurança sobre nenhuma das duas: desativar
por ausência derrubaria conta viva (F65/F85), e não desativar deixa ex-cliente no ar
(F128). O resultado é que **offboarding virou processo manual** e ficou dois meses sem
acontecer.

### Evidência medida (2026-08-20, produção)

Probe direto no Graph com o token do system user, cruzado com o banco:

```
PARCERIA (client_ad_accounts ∪ owned_ad_accounts): 25
ALCANCE do SU (/me/adaccounts):                    23
INVENTÁRIO ativo (meta_ad_accounts):               24
```

| Diff | Contas | Significado |
|---|---|---|
| ativo no inventário, **fora** da parceria | **1** — `Mestre da Obra Petrolina`, com **4 grants vivos** | saiu: offboarding |
| na parceria, **sem** o SU atribuído | **2** — `CA - V4 Lima Soares` (ativa), `CHUTE 07` (status 101) | atribuir o SU no Business Manager |
| na parceria, **fora** do inventário | as mesmas 2 | deveriam estar no catálogo |

Zero falso-positivo no conjunto de saída. E o de entrada revela que **a própria conta da
V4 nunca entrou no MCP**, por falta de atribuição do SU — invisível pelo mecanismo atual.

### O que o probe descartou

- **`/me/businesses` devolve 0.** O SU não se enxerga como membro de BM por essa edge; o
  ID do BM da V4 tem de ser **configuração**, não descoberta.
- **A Meta não sabe quem cuida de qual cliente.** `business_users` do BM devolve **uma**
  pessoa (o admin) e `assigned_users` das contas devolve só o próprio system user. Não
  existe fonte para automatizar a *concessão* — qualquer regra inventada ("todo mundo vê
  tudo", "o último que mexeu") seria arbitrária.

---

## 2. Decisões tomadas

**Entrada e saída não são simétricas, e o desenho respeita isso.**

| | Catálogo (`meta_ad_accounts`) | Acesso (`manager_meta_account_access`) |
|---|---|---|
| **entra na parceria** | automático | **nenhum** — a conta aparece no painel *sem delegação*, e o admin delega |
| **sai da parceria** | automático | **automático** — grants revogados |

É a regra de ouro de gestão de identidade (JML): **automatizar a retirada, manter humana a
concessão**. Revogar por engano se conserta com um clique e deixa trilha; conceder por
engano é incidente. Fora isso, como mostrado acima, a informação necessária para conceder
**não existe em lugar nenhum do sistema** — ela nasce da decisão comercial da V4, e o
painel é onde ela é registrada.

Duas decisões complementares, aprovadas:

1. **Revogação é *soft*.** A linha do grant permanece com `revoked_at` + `revoked_reason`;
   sai da matriz, o gate nega, e volta com um clique se a parceria voltar. Hoje `revoke` é
   `DELETE` puro e perderia a curadoria de quem tinha acesso.
2. **O gate passa a exigir conta ativa.** `can_manager_access` hoje lê **só** a tabela de
   grants — sem join, sem `is_active`. Com a checagem, conta fora da parceria para de
   responder **mesmo que o reconciliador atrase**. Sob o modelo de system user isso não é
   luxo: a Meta entrega tudo que o BM alcança, então o gate é a única fronteira que resta
   (*confused deputy* — o F128 é a instância viva).

---

## 3. Fonte autoritativa e mudança de contrato

**Estado desejado** = `GET /{BM}/client_ad_accounts` ∪ `GET /{BM}/owned_ad_accounts`.

`/me/adaccounts` **deixa de definir o inventário** e passa a alimentar um sinal separado:
`su_reachable`. A distinção é a base de tudo:

- `in_partnership=false` → **a conta não é mais nossa** → desativa e revoga.
- `su_reachable=false` com `in_partnership=true` → **é nossa, mas não conseguimos ler** →
  alerta para ação humana no Business Manager. **Nunca** desativa.

`meta_business_id` vira campo de `Settings` (não é segredo — é ID, entra como env var).
**Atenção F114:** campo obrigatório novo em `Settings` precisa ser declarado também nos
**3 Cloud Run Jobs** do `deploy.yml`, que chamam `get_settings()` e validam tudo na subida.
O guard `test_deploy_env_matches_settings.py` cobre as duas direções.

---

## 4. Componentes

Cada unidade com um propósito, testável isoladamente:

| Unidade | Responsabilidade | Depende de |
|---|---|---|
| `src/meta_ads/graph.py` | paginação Graph com contrato `complete` (F93) | httpx |
| `src/meta_ads/partnership.py` | busca as duas edges e devolve `PartnershipSnapshot` | graph |
| `src/meta_ads/reconcile.py` | **função pura**: `plan(partnership, reachable, inventory) -> Plan` | nada |
| `src/jobs/meta_resync.py` | aplica o plano em transação, com as travas | repos |
| repos | persistência do estado e da revogação soft | asyncpg |
| `src/web/routes.py` + template | as três filas no painel | repos |

O `plan()` puro é o coração: recebe conjuntos, devolve `Plan(to_add, to_remove,
unreachable)`. Sem I/O, ele é testável por tabela de casos — e é onde mora a lógica que,
errada, revoga acesso indevido.

**Refactor mínimo incluído:** o paginador vive hoje em `src/auth/meta_oauth.py`
(`_fetch_all_adaccounts`) e é reusado pelo job — acoplamento que o próprio código já
marcava como dívida. Ele sai para `src/meta_ads/graph.py`, consumido pelos dois. Sem isso
o novo módulo duplicaria paginação, que é o tipo de duplicação que apodrece em silêncio.

---

## 5. Fluxo

```
   Graph: client_ad_accounts ∪ owned_ad_accounts ──┐
   Graph: /me/adaccounts ─────────────────┐        │
                                          ▼        ▼
   DB: meta_ad_accounts ──────────────►  plan()  (puro)
                                             │
                     ┌───────────────────────┼───────────────────────┐
                     ▼                       ▼                       ▼
                  to_add                 to_remove              unreachable
            upsert + is_active=true   desativa + revoga        marca su_reachable
            (nenhum grant)            (soft, com motivo)       (só sinaliza)
```

**Aditivo sempre; destrutivo só sob condição.** Adicionar conta que *está* na parceria é
seguro mesmo com leitura parcial. Remover, não.

---

## 6. Modelo de dados

```sql
-- 006_meta_partnership_reconciliation.sql
ALTER TABLE meta_ad_accounts
    ADD COLUMN IF NOT EXISTS su_reachable BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE manager_meta_account_access
    ADD COLUMN IF NOT EXISTS revoked_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS revoked_reason TEXT;
```

Sem índice novo: a PK `(manager_id, ad_account_id)` já serve a busca do gate, e o filtro
`revoked_at IS NULL` recai sobre a linha já encontrada. Índice parcial aqui seria cópia da
PK — custo de escrita sem ganho de leitura.

**`missed_syncs` muda de significado** (introduzido horas antes, no F128): deixa de contar
ausência em `/me/adaccounts` e passa a contar **ausência na parceria**. A coluna continua
sendo o mecanismo de carência — o que muda é a fonte contra a qual ela conta. Manter as
duas semânticas seria estado duplicado com sentidos diferentes.

**"Sem delegação" não ganha coluna** — é derivável: conta ativa sem nenhum grant vivo.
Estado duplicado diverge; o derivado não pode.

### Contratos que mudam

- `can_manager_access`: `JOIN meta_ad_accounts ... WHERE is_active AND revoked_at IS NULL`
- `list_accounts_for_manager`, matriz de acesso: filtram `revoked_at IS NULL`
- `revoke` (manual, do painel): passa a ser soft, com `revoked_reason='manual'`
- `grant`: limpa `revoked_at`/`revoked_reason` ao reconceder (restauração é reconcessão)

---

## 7. Travas

A ação é destrutiva e esta família de bug já mordeu duas vezes (F65 desativou por escopo
errado; F85 desativou 25 contas por resposta vazia). Quatro travas, em camadas:

1. **Só reconcilia o lado destrutivo com leitura completa** das duas edges. Página que
   falhou não é churn (F93). O lado aditivo roda sempre.
2. **Carência:** a conta precisa faltar na parceria em **3 execuções completas seguidas**
   antes de sair. Um soluço do Graph não revoga acesso de ninguém.
3. **Guard percentual:** se o plano remove acima do limiar do inventário ativo, o lado
   destrutivo **não executa** — audita `status=error` e alerta. É o follow-up que o F85
   deixou explicitamente em aberto. Limiar proposto: **20% ou 5 contas, o que for menor**.
4. **Dry-run no rollout:** o job entra em produção com o lado destrutivo desligado,
   apenas registrando o plano que executaria. O controle é um campo de `Settings`
   (`meta_reconcile_apply`, default `false`) — env var, virável sem deploy de código, e
   sujeito à mesma regra do F114: declarar nos 3 Cloud Run Jobs.

---

## 8. Painel

`/admin/accounts/meta` passa a ter três filas — a seção *Fora do alcance do system user*
criada no F128 é absorvida por elas:

1. **Aguardando delegação** — na parceria, ativa, **zero grants vivos**. É a fila de
   trabalho do admin: o link leva direto à matriz. *É o que responde ao pedido "quero que
   apareça no dashboard e eu delego".*
2. **Sem o SU atribuído** — na parceria, `su_reachable=false`. Não é problema do MCP:
   instrui a atribuir o SU no Business Manager. Hoje: 2 contas.
3. **Saíram da parceria** — desativadas, com a contagem de grants revogados. O botão
   **restaurar** reconcede exatamente os grants que foram revogados por churn naquela
   conta (limpa `revoked_at`), para o caso de a parceria voltar. Ele é a razão de a
   revogação ser soft: sem a linha preservada não há o que restaurar, só refazer à mão.

---

## 9. Auditoria

- Uma linha por execução: `operation=meta_reconcile`, com `added`, `removed`,
  `unreachable`, `complete`, `applied` (false em dry-run) e o **guard percentual** quando
  ele barrar.
- Uma linha por conta cujos grants forem revogados: reusa `meta_access_cleanup` (o mesmo
  nome usado na limpeza manual de 15/08), com `reason='partnership_ended'` e a lista de
  gestores atingidos. Por conta, não por grant — forense suficiente, sem ruído.

Sob system user, a Meta registra tudo como `v4-ads-mcp-integracao`. O `audit_log` do MCP é
o **único** lugar onde a autoria real existe; por isso ele é parte do desenho, não enfeite.

---

## 10. Testes

| Camada | O que prova |
|---|---|
| unit — `plan()` | tabela de casos: entrada, saída, ambos, vazio, sem mudança, conta na parceria e não alcançável |
| unit — travas | incompleto não remove; carência segura por 3 execuções; guard percentual barra; dry-run não escreve |
| unit — Graph (`respx`) | paginação das duas edges; erro no meio marca `complete=false` |
| integração | soft-revoke persiste e o gate nega; reconceder limpa `revoked_at`; conta desativada some da matriz |
| **guard derivado** | `can_manager_access` **precisa** referenciar `is_active`/`revoked_at` — varre o source, não lista arquivos |

O guard derivado é o que impede a regressão silenciosa: sem ele, alguém "simplifica" o
JOIN um dia e o gate volta a liberar ex-cliente sem nenhum teste vermelho (foi assim que o
F86 renasceu como F109).

---

## 11. Rollout

1. Migration + código com `apply=false`. O job **observa e conta**, mas não destrói:
   entram as contas novas, o contador de ausências avança e a alcançabilidade do
   system user é marcada. Só `deactivate` e a revogação de grants ficam atrás da trava.
   *(Corrigido em 2026-08-20 durante a implementação: a versão original desta seção
   punha as três escritas observacionais atrás da mesma trava, o que deixava a fila
   "sem SU" vazia para sempre e tornava a remoção inalcançável — o soak não poderia
   demonstrar justamente o que existe para demonstrar.)*
2. Observar. Na **primeira** execução o plano mostra `added=2`, `bumped=1`,
   `unreachable=2` e **`removed=0`** — a carência de 3 execuções completas é o
   desenho, não uma falha. `removed=1` (Petrolina) aparece na **terceira**.
   Qualquer outro número significa que o desenho está errado, e ninguém perdeu acesso.
3. Virar `apply=true`. **Atenção operacional:** como o contador avança durante o soak,
   se a carência já estiver cumprida a revogação acontece na **primeira** execução
   depois de virar a chave — não há um segundo período de graça. O guard percentual
   limita o estrago a 4 contas nesse dia.
4. **Critério de aceite:** a Petrolina sai sozinha — inventário desativado, 4 grants
   revogados com motivo, linha no audit — sem ninguém tocar na matriz. E a fila
   "Aguardando delegação" mostra as contas novas **sem nenhum acesso concedido**.

---

## 12. Fora de escopo

- **O lado Google.** `manager_account_access.can_manager_access` tem o **mesmo** buraco
  (não consulta `is_active`). É a mesma classe e merece finding próprio, mas o Google não
  tem o conceito de parceria de BM — a fonte autoritativa lá é outra (`customer_client` do
  MCC). Misturar as duas neste trabalho aumentaria o raio sem melhorar nenhum dos dois.
- **Redução de permissão do system user** (hoje `MANAGE/ADVERTISE/ANALYZE` para um uso
  100% de leitura) e **rotação do token**: ações no Business Manager, não código.
- **Tools de escrita Meta.** Se entrarem, a atribuição no `audit_log` deixa de ser
  conveniência e vira requisito de governança.
- **Filtrar conta fechada** (`account_status=101`, caso do `CHUTE 07`): ela está na
  parceria, então entra no catálogo. Escondê-la é decisão de produto, não de correção.

---

## 13. Riscos e questões em aberto

| Risco | Mitigação |
|---|---|
| a edge de parceria muda de forma ou de permissão | `complete=false` bloqueia o destrutivo; o dry-run detecta antes |
| limiar do guard percentual mal calibrado | começa conservador (20%/5) e é config, não constante espalhada |
| admin não olha a fila de delegação | conta nova nasce **sem acesso**: o custo do esquecimento é "ninguém usou", nunca "alguém viu o que não devia" |
| BM com um único `business_user` | fora de escopo aqui, mas é ponto único de falha administrativa: registrar como pendência |

**Aberto:** o limiar exato do guard percentual, a confirmar no dry-run com dados reais.
