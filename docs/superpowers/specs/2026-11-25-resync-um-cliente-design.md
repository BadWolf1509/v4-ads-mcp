# Resync com um cliente só — design curto (25/11/2026, aprovado)

## Por quê

A rodada do resync sem aplicar, em 25/11 (audits 12861–12880), mostrou três problemas:

1. **A Meta desligada derruba o job todo dia.**
   - A etapa grava `meta_reconcile` com erro "token do system user nao configurado" e o job sai com 1.
   - O retry repete a execução 4 vezes.
   - Despausado, o alerta de job falho dispararia diariamente.
2. **O Google travaria no teto de segurança.**
   - A MDO enxerga 1 das 24 contas ativas (`bumped=23`).
   - Passada a carência de 3 dias, o plano tentaria remover 23 contas.
   - O teto (20% ou 5) bloqueia essa remoção e o job sai com 1 todo dia.
   - Isso é leitura do código, não medição.
3. **As credenciais de quem saiu continuam guardadas.**
   - 5 conexões OAuth `@v4company` seguem vivas.
   - Desativar o gestor revoga os grants, mas não as conexões.
   - O painel só deixa o dono revogar a própria conexão.

Além disso, o Gmail continua com 24 grants Google e 26 Meta.

## Decisões (aprovadas no menu)

### (a) Meta desligada explícita
- Nova configuração `meta_habilitada: bool = True`.
  - O padrão `true` preserva o comportamento de hoje: configuração esquecida continua sendo erro.
- O `deploy.yml` passa `META_HABILITADA=${{ vars.META_HABILITADA || 'true' }}` ao serviço e aos jobs.
- Com `false`, `_etapa_meta`:
  - grava `meta_reconcile` com `status=success` e `params_summary={"desligada": true}`;
  - não chama a Graph;
  - não conta no código de saída do job.

### (b) Desligamento revoga a credencial (JML)
- O toggle de desativação revoga as conexões OAuth vivas do gestor.
  - Acontece na mesma transação e entra no mesmo audit (`conexoes_revogadas`).
- Reativar não devolve as conexões: o gestor reconecta pelo OAuth.
- Backfill pelo comando `admin revogar-conexoes-de-inativos [--apply]`:
  - dry-run por padrão;
  - audit `cli_revoke_inactive_connections`.

### (c) Descomissionamento explícito
- Comando: `admin descomissionar --manter-google <ids> --manter-meta <ids> [--apply]`.
- Dry-run: lista as contas ativas fora da lista e os grants vivos nelas.
- `--apply`, numa transação:
  - desativa essas contas no inventário (`google_ads_accounts.deactivate` e `meta_ad_accounts.deactivate`);
  - revoga os grants com os motivos de churn já existentes (`left_mcc` e `partnership_ended`);
  - grava o audit `cli_decommission`.
- **Reverter:** conta que reaparece é reativada pelo resync, e os grants de churn voltam pela restauração que já existe.
- **Trava:** recusa se algum id de `--manter-*` não for uma conta **ativa** no inventário. Um erro de digitação não pode descomissionar tudo.

## Fora do escopo

- Subir o teto de segurança.
- MCC próprio.
- Apagar linhas do banco.
- Mudar o comportamento da reconciliação.

## Aceite

- **Testes:** unitários para (a) e para o toggle; integração com banco real para (b) e (c), no full sweep.
- **Depois do deploy, com avais separados:**
  1. `META_HABILITADA=false`;
  2. os dois comandos em dry-run e depois com `--apply`;
  3. uma rodada do resync sem aplicar, que deve sair com 0.
