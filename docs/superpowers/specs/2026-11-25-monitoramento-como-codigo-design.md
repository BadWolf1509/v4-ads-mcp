# Monitoramento como código — design curto (25/11/2026, aprovado)

## Intenção

Hoje a definição do monitoramento do `fluxo-certo-ads` existe só no Cloud Monitoring:

- canal de e-mail;
- uptime check;
- 2 métricas log-based;
- 5 policies.

Ela foi recriada em 25/11 a partir de um export do projeto antigo, que pode sumir. Projeto novo ou DR teriam de redigitar runbooks à mão (teste 1 do "Padrão de solução": depende de alguém lembrar). Objetivo: as definições versionadas no repositório e um aplicador que as leva a qualquer projeto.

## Objetivos

- **Definições** versionadas em `scripts/infra/monitoramento/*.json`, copiadas do export real, com marcadores:
  - `{PROJECT}`;
  - `{HOST}`;
  - `{CHANNEL}` (nome completo do canal);
  - `{CHECK_ID}` (ID do uptime check).
- **Aplicador** `python -m scripts.infra.monitoramento --project-id P --host H --alert-email E [--apply]`:
  - sem `--apply`, imprime o plano e não escreve nada;
  - com `--apply`, cria só o que falta;
  - a ordem é canal → uptime → métricas → policies, e cada etapa resolve o ID que a seguinte usa.
- **Classificação de cada recurso no plano:**
  - `criar`;
  - `igual`;
  - `diferente` — o existente diverge nos campos que o modelo define. É apontado, **nunca** sobrescrito nem apagado, e o processo sai com 1 para o operador ver.
- **Chave de identidade de cada recurso:**
  - canal: tipo e e-mail;
  - uptime check: `displayName`;
  - métrica: `name`;
  - policy: `displayName`.
- **Bootstrap:** o `--apply` do bootstrap chama o aplicador no fim, no lugar do lembrete impresso.

## Fora do escopo

- Atualizar ou apagar recursos (PATCH ou DELETE).
- Terraform.
- Rodar o aplicador no CI.
- Monitoramento novo além dos 9 recursos atuais.

## Abordagens

1. **Aplicador Python + JSON (escolhida).** Mesmo padrão do bootstrap (dry-run por padrão, `--apply`), REST direto e nenhuma ferramenta nova.
2. **Terraform.** Padrão de IaC, mas traz ferramenta e estado remoto novos para 9 recursos de um projeto solo.
3. **`gcloud` no bootstrap.** O componente de policies é alpha e não está instalado; acabaria em REST espalhado.

## Restrições

- Token via `gcloud auth print-access-token`, com `gcloud` resolvido por `shutil.which` (Windows), timeout e sem stderr mudo.
- Header `x-goog-user-project`.
- Restrições de forma da API, medidas em 25/11:
  - `notificationRateLimit` só em policy log-based (`conditionMatchedLog`);
  - campos de saída (`name`, `creationRecord`, `mutationRecord`) não entram no POST.

## Aceite

- **Testes unitários:**
  - os modelos montam sem marcador sobrando e sem `v4-ads-mcp-299432068772` nem `projects/v4-ads-mcp/`;
  - o que falta é criado;
  - o que existe igual é pulado;
  - o diferente não é tocado e sai com 1;
  - a segunda rodada não cria nada.
- **Dry-run real contra o `fluxo-certo-ads`:** os 9 recursos como `igual`.

## Para quem implementa

- Formato da saída do plano.
- Como comparar "igual": só os campos do modelo, ignorando os campos de saída do servidor.
- Estrutura interna do cliente HTTP, que deve ser injetável nos testes.
