# Estado atual — Fluxo Certo Ads (repositório `v4-ads-mcp`)

> **Volátil por natureza** — o `CLAUDE.md` mantém um resumo de poucas linhas e aponta para cá.
> **Ao terminar uma sessão, atualize ESTE arquivo** e mantenha-o curto (teto prático: ~10 KB).
> **Trabalho que fechou sai daqui:** o defeito vai para o catálogo, a narrativa para o handoff ou o
> `_archive/`, e aqui fica uma linha. O recorte de 11 a 24/11 (projeto antigo) está em
> [`_archive/estado-atual-2026-11-11-a-11-24.md`](../_archive/estado-atual-2026-11-11-a-11-24.md).

> **Última sessão:** [`session-2026-11-24-25-handoff.md`](session-2026-11-24-25-handoff.md) — 24–25/11:
> desligamento da V4, **migração para o projeto `fluxo-certo-ads`** (#283, #284), rebrand para
> **Fluxo Certo Ads**, Google Ads API no nível **Básico**. Antes:
> [`session-2026-11-17-handoff.md`](session-2026-11-17-handoff.md) (revogação na desativação, F213).

## Direção (desde 24/11)

- **O Wellington saiu da V4 Lima Soares & Co.** O projeto segue com ele, atendendo **um único cliente**:
  Mestre da Obra João Pessoa + Cabedelo (Google `7862230676`, Meta `act_27798855556414269`, BM
  `3771852976434166`). Não há mais clientes nem gestores da V4 como usuários.
- **Produto renomeado para "Fluxo Certo Ads"** (nome num global Jinja, `src/web/templating.py`). O
  repositório, os service accounts, os jobs e a chave de protocolo `com.v4company/bucket` mantêm o nome
  `v4-ads-mcp` de propósito (contrato com clientes MCP e com o `deploy.yml`).
- **Acesso:** a tabela `managers` é a única allowlist — sem trava de domínio desde #283.
- **Meta desligada** até existirem BM, app e system user próprios (secrets com `" "`, que o `Settings`
  lê como vazio).
- O "teste de 30 dias até 02/12" e a Fase 2B (soak de gestores) perderam o objeto com a saída dos
  gestores; ficam no arquivo.

## Produção — medido em 25/11

| | |
|---|---|
| Projeto GCP | **`fluxo-certo-ads`** (número `505452482961`), sem organização, owner e faturamento do Gmail |
| URL | **`https://v4-ads-mcp-505452482961.southamerica-east1.run.app`** — a única cadastrada no OAuth; o endereço alternativo `v4-ads-mcp-nbuw3bjhpq-rj.a.run.app` também responde, mas o login falha por ele |
| Revisão | `v4-ads-mcp-00001-cr5`, 100% (primeiro deploy, run `45535510962`, commit `6968b27`) |
| Saúde | `/health?deep=1` ok (`db: ok`, 83 tools); `/mcp` sem token → 401 |
| Google Ads API | nível **Básico** (15.000 ops/dia) no projeto; medido com `plan_keyword_ideas` real |
| Login-customer-id | **`7862230676`** (a própria MDO, acesso direto do Gmail) — **provisório**, sem MCC próprio |
| Admin | `wellington.ribeiro.eng@gmail.com` (`bootstrap-admin`, audit `cli_bootstrap_admin`) |
| OAuth | cliente web do projeto novo; marca **não verificada**; publicação em Produção pedida ao Wellington (em Teste, o token expira em 7 dias) — **não conferido** |
| Agendamentos | `v4-ads-mcp-resync-daily` e `v4-ads-mcp-backup-weekly` **PAUSADOS** |
| Alertas | **nenhum** no projeto novo (canal e 5 policies não recriados) |
| Banco | o mesmo Supabase (Session Pooler `:5432`), 11 migrations, `audit_log` íntegro |
| Catálogo | até **F215** (~6.400 linhas, 631 KB); candidatos desta sessão no handoff |

**Projeto antigo `v4-ads-mcp` (`299432068772`):** dentro da organização `v4company.com`, faturamento
**desligado em 24/11 às 21:30 BRT** pela própria conta `@v4company.com` (log de auditoria), serviço 503.
Os backups de `gs://v4-ads-mcp-backups` e o Secret Manager de lá ficaram inacessíveis.

## Decision gates abertos

1. **Reconciliação do Google com login-customer-id de conta (não MCC).** Pela leitura do job, o resync
   só enxergaria a MDO e revogaria os grants das outras 25 contas do inventário (`GOOGLE_RECONCILE_APPLY=
   true`). **Não executado.** Decidir: MCC próprio, ou `false` nas DUAS linhas do `deploy.yml`, antes de
   despausar o resync.
2. **Backup semanal pausado** → hoje **não há backup** do banco além do que o Supabase guarda. Despausar
   o `v4-ads-mcp-backup-weekly` não depende do gate 1 (o job de backup não reconcilia), mas está pausado
   junto: decidir em separado.
3. **Grants do Gmail:** 24 contas Google + 26 Meta liberadas por `admin_access_bulk_grant` em 25/11.
   Recomendado deixar só a MDO.
4. **Gestores `@v4company`:** 6 linhas — **4 ativos** (Wellington `@v4company`, Anderson, Luiz, Lucas
   Avelino) a desativar pelo painel (F213, soft) e 2 já inativos (Lucas Soares, Pedro). A conexão OAuth
   do Lucas Soares segue ativa e deve ser revogada.

## Próximo trabalho (em ordem)

1. **Alertas no projeto novo:** canal de e-mail do Gmail + as 5 policies (runbooks REST do
   [`infra-setup.md`](infra-setup.md)). Hoje queda ou job falho não avisa ninguém.
2. Gates 1–4 acima, com o Wellington.
3. **Meta:** BM e app próprios, system user all-targets (F64), parceria com o BM da MDO, 3 secrets e
   `vars.META_BUSINESS_ID`.
4. **Domínio próprio** na frente do Cloud Run (F67) — pré-requisito da verificação de marca do OAuth
   com redirect em domínio autorizado; o Básico já saiu sem ele.
5. Pendências menores da migração: M1/M5/M6 do bootstrap; logo definitivo no lugar da marca "FC";
   revisar privacidade e termos (rascunho; a verificação de marca usa as páginas da Vercel em
   `www.fluxocerto.dev.br`).

## Pendências que dependem do Wellington

- Publicar o OAuth em Produção e entrar de novo (token emitido em Teste expira em 7 dias).
- Search Console: verificar `fluxocerto.dev.br` com o Gmail (TXT no Registro.br) — a verificação de
  marca recusou por isso em 25/11.
- MCC próprio; pedir à V4 que desvincule a MDO do MCC `6436352492` e do BM `619664032237208` **depois**
  de o acesso próprio valer (o Google já vale, direto).
- O que fazer com o projeto antigo `v4-ads-mcp` (parado) e com o app Meta "V4 MDO Stories"
  (`4419481288293195`, do BM da V4).
- Assinatura do Google AI Pro do Gmail (plano da Jio, terminou em 24/11) — fora do projeto.

## Findings abertos

| ID | o que é |
|---|---|
| **F180** | em parte, provavelmente para sempre — o Google aceita operação impossível em vez de errar: leia `efeito` e `changed_count` |
| **F185** | `recommendation_subscription`: 4 de 11 opacos — limitação da API |
| **F187** | resumo no topo × detalhe embaixo — 4 instâncias |
| **F214** | log `conversion_upload_executed` diz `success` num upload 100% recusado quando o audit não pega conexão |
| **F186** | smoke autenticado do `/mcp` desarmado no pipeline (`SMOKE_MCP_BEARER`) |
| — | candidatos a finding desta sessão (só o Wellington cataloga, `/findings-add`): ver o [handoff](session-2026-11-24-25-handoff.md) |

O defeito de cada finding está no [catálogo](findings-catalog.md). 🔑 A lição que atravessa todos:
**existia a regra e não existia o mecanismo**.
