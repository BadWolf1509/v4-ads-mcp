# Tools Meta: leitura, auditoria e escrita

**Data:** 2026-10-31
**Status:** aprovada pelo Wellington em 31/10; escrita depende dos pré-requisitos
**Levantamento de origem:** sessão de 31/10 (uso de 90 dias, servidor oficial da Meta, changelog v25)

## Intenção

Levar a Meta ao nível de operação que o Google já tem no MCP. Hoje são 7 tools de leitura, e nenhuma
mostra status nem orçamento: o gestor não descobre pelo MCP se uma campanha está ativa.

O motivo de construir, com o servidor oficial da Meta já existindo, é a governança: gate de acesso por
conta, auditoria por gestor, dry-run com confirmação, relato medido em PT-BR e auditorias no padrão V4.
Tool que não usa esse diferencial não entra.

## Metas

- Dar leitura de metadados, histórico, criativos, públicos e sinais (Onda 1).
- Dar auditorias que apontem o que corrigir (Onda 2).
- Permitir pausar, ativar, ajustar orçamento e criar campanha completa, com confirmação (Onda 3).

## Fora de escopo

Catálogo, impulsionar post, excluir entidade, alterar limite de gasto da conta, Biblioteca de Anúncios,
teste A/B, públicos (criar ou alterar), lista de clientes, lookalike, regras automáticas e download de
leads. Cada um volta como decisão própria se surgir demanda.

## Antimetas (fracasso mesmo se funcionar)

- Gastar dinheiro de cliente sem confirmação explícita naquela ação.
- Criar anúncio já ativo.
- Dizer "aplicado" sem conferir o que a Meta gravou.
- Escrita sem saber qual gestor pediu.
- Publicar qualquer tool de escrita antes dos pré-requisitos.

## Decisões do Wellington

1. A spec cobre as 3 ondas, mas a escrita só vai ao ar depois dos pré-requisitos e de aval nominal.
2. Ativar e aumentar orçamento: qualquer gestor com acesso de escrita à conta, com dry-run e confirmação.
   Não há teto nem exigência de admin.
3. A criação cobre, desde a primeira versão, Mensagens (WhatsApp/Direct), Leads, Vendas, Tráfego e
   Reconhecimento. Vendas é conversão no site com pixel, sem catálogo.

4. **Liberação por interruptor de gestor.** As tools de escrita só aparecem e funcionam para gestores numa
   lista. Permite o smoke real antes de liberar para todos.
5. **Acessos rebaixados e reconcedidos.** Uma migration passa os acessos Meta atuais para leitura, e o
   painel ganha controle leitura/escrita. A escrita é concedida por gestor e conta.
6. **Papel de anunciante só nas contas operadas, com token permanente.** Não há job de renovação nesta
   frente; o risco de vazamento segue aberto no F129.

## Decisões minhas (revisar ao ler)

- **Toda escrita Meta exige confirmação.** Não há auto-apply por quantidade, ao contrário do Google até
  5 itens: `classify` devolve sempre confirmação para operação `meta_*`, inclusive pausar.
- **Tudo que é criado nasce `PAUSED`.** O payload fixa o status no servidor, e o gestor não o escolhe.
  Ativar é sempre uma chamada separada de `meta_update_status`.
- **Ondas em PRs separados, nesta ordem:** 1, 2, 3. A Onda 3 tem uma fase de infraestrutura antes das tools.
- **Nomes e contrato seguem os das tools Meta atuais:** prefixo `meta_`, `ad_account_id` no formato
  `act_<id>`, métrica só por `metricas_da_linha`, `null` para o não reportado, janelas com
  `resolve_meta_date_window`.
- **Todas as tools novas entram em `bucket="defer"`**, menos `meta_get_entities`, que vai para `always`.
- **Prova de posse:** antes de escrever em `/{id}`, a entidade é lida por um edge da conta gateada
  (`/act_x/campaigns` filtrado por id, e equivalentes), e o POST só sai se ela vier. A prova roda no
  dry-run e **de novo no `apply_change`**, porque o token vive 10 minutos. O executor de escrita tem contrato
  próprio de edge por objeto, e a contenção do guard `test_meta_graph_execution_is_contained` é estendida.
- **Drift:** ator humano é autorizado por lista na chamada (nome ou ID), como o `responsible_user_emails` do
  Google; ação do system user é casada com o `audit_log` por entidade e janela. Sem cadastro novo no banco.
  A Onda 3 grava o ID da entidade em `params_summary` para isso. Antes dela, toda ação do system user é drift,
  e está certo: o MCP ainda não escreve.

## Pré-requisitos

### Da Onda 1 e 2

- Cada campo novo validado com `ads_get_field_context` do MCP oficial da Meta antes do ship.
  **Não rodou na Onda 1** (o MCP oficial não estava na sessão); os campos foram provados por sonda GET
  (`docs/operacao/sonda-meta-onda1-2026-10-31.md`) e a validação segue pendente.
- **F129, primeira metade:** reduzir o system user para só análise enquanto só há leitura, testado em uma
  conta antes das demais. Ação do Wellington no BM. Se a redução quebrar alguma leitura, reverter e
  registrar; isso não bloqueia as Ondas 1 e 2.

### Bloqueadores da Onda 3 (nada de escrita vai ao ar sem todos)

1. **`ads_management` confirmado**, por `debug_token` do token real. Hoje não medido.
2. **Papel do system user** elevado de análise para anunciante (`ADVERTISE`) só nas contas que forem
   operadas, quando a Onda 3 for ao ar. Em conta sem o papel, a Meta recusa, e a resposta explica isso.
3. **Nível de acesso da API:** pedir acesso completo (exige 500 chamadas em 15 dias). No nível de
   desenvolvimento a escrita fica limitada a cerca de 300 pontos + 40 por anúncio ativo, por hora e conta.
   Se o pedido não sair, a Onda 3 pode ir ao ar com aviso de limite, por decisão do Wellington.
4. **Executor de escrita** e governança (seção Onda 3).

## Onda 1: leitura (10 tools planejadas, 8 entregues)

> **Resultado (01/11):** `meta_get_custom_audiences` e `meta_get_signal_health` foram retiradas: duas contas
> (a interna e `act_27798855556414269`) devolveram 0 linhas em `customaudiences` e `adspixels`, o que não
> distingue "não tem" de "o token não enxerga"; sem endpoint provado a tool sai, como esta seção manda.
> `reachestimate` foi descartado (veio vazio); `meta_get_delivery_estimate` usa só `delivery_estimate`.

| Tool | Entrega | Origem |
|---|---|---|
| `meta_get_entities` | Campanhas, conjuntos e anúncios com status efetivo, orçamento, lance, objetivo e problemas de entrega; filtro por nível e status | `/campaigns`, `/adsets`, `/ads` |
| `meta_get_change_history` | Quem mudou o quê, por período | `activities` |
| `meta_get_creatives` | Criativos e anúncios que os usam | `adcreatives` |
| `meta_get_ad_preview` | Prévia por posicionamento | `generatepreviews` |
| `meta_get_budget_pacing` | Gasto x orçamento e projeção, com as regras do `get_budget_pacing` Google (dia corrente não conta como dia inteiro, F199) | metadados + insights |
| `meta_get_custom_audiences` | Públicos, tamanho e status | `customaudiences` |
| `meta_get_delivery_estimate` | Alcance estimado para uma segmentação | `delivery_estimate`, `reachestimate` |
| `meta_search_targeting` | Busca de interesses e segmentações | `targetingsearch` |
| `meta_get_pages` | Páginas e contas Instagram utilizáveis | a confirmar |
| `meta_get_signal_health` | Pixel/dataset: eventos, deduplicação e qualidade | a confirmar |

Endpoint marcado "a confirmar": se não houver caminho pela Graph com o token atual, a tool é retirada e o
motivo registrado, sem substituir por dado inferido.

`meta_get_entities` substitui o aviso atual das tools de desempenho de que status não vem. As descriptions
passam a apontar para ela.

## Onda 2: auditorias (4 tools)

Só leitura, com limiares em constantes nomeadas e devolvidos na resposta.

| Tool | Aponta |
|---|---|
| `meta_audit_delivery_health` | Aprendizado travado, frequência alta, anúncio reprovado ou com entrega limitada |
| `meta_audit_creative_fatigue` | Queda de CTR com alta de frequência por anúncio |
| `meta_audit_budget_limited` | Conjunto limitado por orçamento |
| `meta_detect_drift` | Mudança de quem não está autorizado, sobre `meta_get_change_history` |

**`meta_detect_drift` tem limite que precisa aparecer na resposta:** toda ação pelo MCP sai como o system
user, então cruzar a autoria real exige o `audit_log`. Ação do system user sem linha no `audit_log` é drift.

Toda auditoria distingue "sem problema" de "não foi possível medir": dado ausente é `null` com motivo, e o
resultado traz a cobertura.

## Onda 3: escrita (7 tools)

### Infraestrutura

- `run_meta_graph_post`, irmão de `run_meta_graph_get`: mesmo gate incondicional, mesmo amarramento de
  `edge` à conta (F190), token no header, contabilização de uso e tradução de erro.
- **Sem retry automático em POST.** Timeout depois do envio vira resultado "desconhecido", com instrução
  de conferir, nunca nova tentativa.
- **Interruptor:** lista de gestores em configuração, lida no catálogo e no executor. Fora dela, a tool não
  aparece e, se chamada, é recusada. A lista vazia é o padrão. Guard: gestor fora da lista nunca alcança o POST.
- **Acesso de escrita:** exige nível `write` em `manager_meta_account_access`; leitura não basta. Migration
  (com script idempotente e auditável) passa os acessos atuais para `read`. O painel ganha o controle
  leitura/escrita na matriz Meta e deixa de gravar `write` fixo; novos acessos nascem como `read`.
- `apply_change` passa a despachar operações `meta_*`, com a mesma regra de token único por sessão e TTL.
- `audit_log` com `platform="meta"`, `manager_id`, payload resumido e `x-fb-trace-id`.
- **Pré-voo:** ler a entidade antes (existe, pertence à conta, estado atual).
- **Pós-voo:** reler depois de escrever e devolver `efeito` (`mudou`, `sem_efeito`, `null`), como no Google.

### Tools

| Ordem | Tool | Regras |
|---|---|---|
| 1 | `meta_update_status` | Campanha, conjunto ou anúncio. Ativar mostra no dry-run o orçamento que passa a gastar |
| 2 | `meta_update_budget` | Conjunto ou campanha. Preview mostra antes, depois e variação. Trata a [regra de 4 mudanças por hora por conjunto](https://developers.facebook.com/docs/marketing-api/overview/rate-limiting): erro 613/1487632 vira mensagem clara |
| 3 | `meta_create_campaign` | 5 objetivos, sempre pausada |
| 4 | `meta_create_ad_set` | Destino, otimização, orçamento, segmentação e posicionamentos, sempre pausado |
| 5 | `meta_upload_image` | Aceita URL ou base64 com limite de tamanho a definir no plano |
| 6 | `meta_create_creative` | Imagem única na primeira versão. Vídeo e carrossel ficam fora |
| 7 | `meta_create_ad` | Liga criativo ao conjunto, sempre pausado |

**Advantage+:** seguir a [estrutura unificada](https://developers.facebook.com/documentation/ads-commerce/marketing-api/marketing-api-changelog/version25.0); não usar campos de Shopping/App antigos, bloqueados em todas as versões desde 19/05/2026.

**Categorias especiais de anúncio** (`special_ad_categories`): parâmetro obrigatório na criação, sem
padrão silencioso.

**Dinheiro:** orçamento entra em BRL na tool e é convertido para a unidade mínima da moeda da conta, lida da
conta. Conta em outra moeda é recusada na primeira versão.

**Falha parcial na criação:** as três entidades são criadas por chamadas separadas. Não há rollback
automático; a resposta de cada tool devolve os IDs criados, e o que ficou pausado não gasta.

## Testes

- Unitários dos construtores e do parser, com `respx`, seguindo `docs/convencoes/testes.md`.
- Integração do gate, do `apply_change` e do `audit_log` no full sweep.
- Toda tool nova passa pelo `mcp-tool-quality-reviewer`.
- Guards do repositório: contagem de tools, buckets, descriptions e contrato de métrica.
- Sabotagem: gate de escrita, payload `PAUSED` e pós-voo precisam ser vistos falhando.
- **Smoke de escrita com o gestor presente**, em conta interna, em campanha de teste pausada, começando
  por `meta_update_status`.

## Definição de pronto

- **Onda 1 e 2:** chamada real em sessão nova, em ao menos duas contas, e número batendo com o Gerenciador
  em uma delas.
- **Onda 3:** todos os bloqueadores resolvidos, dry-run e aplicação reais em conta interna com o interruptor
  limitado a um gestor, `efeito` conferido no Gerenciador, entrada no `audit_log` com o gestor certo, e aval
  nominal do Wellington para abrir a lista aos demais.

## Riscos

- **Uso baixo:** o breakdown teve 13 chamadas em 90 dias. Medir o uso após cada onda antes de seguir.
- **v25 disponível até 23/02/2027:** a migração de versão cai logo depois desta frente.
- **Catálogo de tools:** 21 tools a mais pesam no contexto; por isso quase todas ficam em `defer`.
- **Limites em Dev:** leitura extra das Ondas 1 e 2 consome a mesma cota.

## Fica para quem constrói

Nome interno de módulos, formato exato dos parâmetros, limiares das auditorias (valores iniciais justificados
no plano), paginação e limites de `limit` por tool.
