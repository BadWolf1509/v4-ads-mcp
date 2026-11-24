# Acesso pela tabela de gestores, sem trava de domínio — design (24/11/2026)

## Intenção

Wellington sai da V4 Lima Soares & Co e segue com o MCP atendendo um único cliente (Mestre da Obra
JP + Cabedelo). A conta que fica é `wellington.ribeiro.eng@gmail.com`, que precisa entrar no painel,
conectar o Google Ads e virar o único admin; nenhum `@v4company.com` continua com acesso.

## Hoje

- `is_allowed_email` (`src/auth/domain_check.py`) só aceita `v4company.com`; é chamada no callback do
  login (`decide_callback`, `oauth.py:73`) e no fluxo de conexão do Google Ads (`oauth.py:471`).
- O convite (`admin_invites.py:84`) recusa domínio fora da V4 (`bad_domain`).
- Depois da trava, a tabela `managers` já decide: convidado/ativo entra, desativado é barrado (F84),
  ausente é `not_invited`; bootstrap só com a tabela vazia.

## Objetivos / não-objetivos / anti-objetivos

- **Objetivo:** a tabela `managers` passa a ser a única allowlist — qualquer domínio, desde que
  convidado por um admin.
- **Não-objetivo:** mexer em projeto GCP, MCC, BM, secrets de API (frentes separadas, ver abaixo).
- **Anti-objetivo:** abrir login para quem não foi convidado; perder o fail-closed do status
  desconhecido, a checagem de `verified_email` ou o veredito do F84.

## Abordagens

| Abordagem | Troca | Escolha |
|---|---|---|
| **Tirar a trava; vale a tabela** | uma fonte de verdade; perde a 2ª camada (convite digitado errado entra) | **escolhida pelo Wellington** |
| Domínios por env var | mantém 2 camadas, mas liberar `gmail.com` quase anula a 1ª | descartada |
| E-mails exatos por env var | camada estreita, mas duplica a tabela (todo gestor novo pede deploy) | descartada |

## Desenho

1. `decide_callback`: remove o passo 1 (domínio). Mantém intacto o resto da árvore.
2. Conexão do Google Ads (`oauth.py:471`): remove a trava de domínio; a checagem de
   `verified_email is False` fica. O fluxo já exige gestor autenticado.
3. Convite: remove o `bad_domain`; mantém a validação de formato (um `@`, parte local e domínio não
   vazios) — reaproveitando a lógica de parse que hoje vive em `is_allowed_email`.
4. `domain_check.py`: vira só o parse de formato (ou sai, se nada mais usa). Textos que dizem
   "apenas @v4company.com" (`_shared.py`, `admin_invites.py`, erro do `oauth.py`) mudam.
5. `BOOTSTRAP_ADMIN_EMAILS` no `deploy.yml` passa a `wellington.ribeiro.eng@gmail.com` (só vale com a
   tabela vazia: restauração de DR). **Decisão do Claude.**
6. **Guards** (falham contra o código pré-fix): e-mail `@gmail.com` convidado loga
   (`promote_invited`); `@gmail.com` não convidado recebe `not_invited` (não `domain`); convite
   `@gmail.com` é aceito; conexão Ads com conta `@gmail.com` verificada passa.

## Depois do deploy (operação, cada passo com aval nominal)

1. Admin convida o Gmail pelo painel → Gmail loga → `bootstrap-admin --email <gmail>` promove a admin.
2. Gmail conecta o Google Ads e recebe os grants da MDO JP (Google `7862230676`, Meta
   `act_27798855556414269`).
3. Desativar no painel `anderson.cordeiro`, `luizfelipe`, `lucasavelino` e, por último,
   `wellington.ribeiro@v4company.com` (F213: revogação soft, audit preservado). Revogar a conexão
   OAuth órfã de `lucassoares` (inativo).

## Fora deste trabalho (bloqueiam a continuidade, não este PR)

- **Não medido:** tela de consentimento OAuth do projeto `v4-ads-mcp` — se for tipo *Interno*, o Google
  recusa o Gmail antes do nosso código; organização e faturamento do projeto; Gmail como owner.
- MCC `6436352492` e BM `619664032237208` são da V4: as reconciliações revogam a MDO quando ela sair
  deles — trocar `GOOGLE_ADS_LOGIN_CUSTOMER_ID`, `META_BUSINESS_ID` e `META_SYSTEM_USER_TOKEN` antes.
- Política do Google Ads sobre cliente fora da unidade (`estado-atual.md`).

## Para o implementador

Nomes de teste, onde fica o parse de formato e a redação exata dos textos.
