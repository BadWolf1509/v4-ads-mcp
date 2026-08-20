# Sessão 2026-08-19 — Handoff (investigação de infra e CI → 5 findings fechados)

> Terceira varredura do dia, depois de [frontend](session-2026-08-19-frontend-handoff.md) (F101-F108) e [backend](session-2026-08-19-backend-handoff.md) (F109-F112). Agora: workflows do GitHub Actions, deploy, Cloud Run Jobs, scripts de gate, lockfile e migrations. **5 achados (F113-F117), todos fechados.**

## Limite declarado

O `gcloud` estava **sem credencial válida** — `Reauthentication failed. cannot prompt during non-interactive execution`. A nota do CLAUDE.md sobre isso, de 08-11, continua correta.

Consequência: auditei a **configuração declarativa do repo**. Estado vivo — env real dos jobs, crons do Cloud Scheduler, alert policies do Monitoring, IAM — **não foi verificado**. Isso mudou o desenho de um fix (F114): sem conseguir enumerar o estado dos jobs, usei `--update-*` (merge) em vez de `--set-*` (replace), que apagaria o que eu não visse.

## TL;DR

| # | Achado | Commit |
|---|---|---|
| **F113** | `ci.yml` ensinava a regenerar o lockfile sem `--universal` — o comando quebra o build Linux | `3cfa6c6` |
| **F115** | O guard do Tailwind só existia no CI | `3cfa6c6` |
| **F114** | Os 3 Cloud Run Jobs precisam de 8 campos obrigatórios que nada no repo declarava | `191953e` |
| **F116** | Rollback deduzia a revisão anterior por ordem de criação | `a754aa4` |
| **F117** | Checkbox de branch protection desmarcado com a proteção ativa | `a754aa4` |

`check_pre_push.py` verde em cada commit — agora com **6 steps**, não 5.

## O achado com maior potencial de estrago

**F113.** O `ci.yml` dizia, no comentário do step de instalação:

```
Regerar o lock: uv pip compile pyproject.toml -o requirements.txt
```

Falta o `--universal`. Rodei os dois em vez de deduzir:

| | `pywin32` no lockfile |
|---|---|
| como o CI ensinava | `pywin32==312` |
| com `--universal` | `pywin32==312 ; sys_platform == 'win32'` |

A máquina do dev é Windows (`uv … x86_64-pc-windows-msvc`), então o comando resolve pra aquela plataforma e o `pywin32` sai **sem marker**. O buildpack CNB então tenta instalá-lo no Linux e o build quebra.

É a classe **F99** na sua forma mais cara: não é doc velha, é doc que instrui a quebrar produção — e estava exatamente onde alguém olharia ao mexer no step de instalação. O CLAUDE.md tinha o comando certo; o arquivo mais próximo do problema, o errado.

## O fix que a falta de gcloud desenhou

**F114.** Os três Cloud Run Jobs rodam o mesmo codebase e chamam `get_settings()`, que valida o `Settings` **inteiro** na subida. Logo cada um precisa dos 8 campos obrigatórios — inclusive `migrate` e `backup`, que funcionalmente só tocam o banco.

O `deploy.yml` já re-aponta imagem e `--command` dos 3 a cada push, e o comentário se gaba disso ("self-healing contra drift manual"). Mas o env ficava só na criação à mão. Sem fonte de verdade e sem guard: `test_deploy_env_matches_settings` lê `--set-env-vars`/`--set-secrets`, que só existem no step do **serviço**.

Três evidências de que isso já doía:

1. O **F95** registrou que os jobs seguem montando os 3 secrets Supabase removidos — a config manual já derivou.
2. `deploy.yml` dizia *"DATABASE_URL foi setado na criação do job"*; `infra-setup.md` corrigia (*"precisa do MESMO secret set do resync"*). Discordavam, e o que subestimava era o arquivo que se edita.
3. Um campo obrigatório novo em `Settings` seria pego pelo guard no serviço e quebraria os 3 jobs em silêncio. `migrate` roda em todo deploy e falharia alto; `resync` (diário) e `backup` (semanal, o artefato de compliance) falhariam quietos — a cegueira que o **F93** atacou.

**A escolha de `--update-*` em vez de `--set-*` é consequência direta do gcloud fora do ar.** `--set-secrets` **substitui** a lista inteira; sem conseguir enumerar o estado real dos jobs, eu apagaria o que não visse. `--update-*` faz merge: é idempotente e só acrescenta.

A lista vive num `env:` do job para não ser triplicada — triplicar criaria exatamente a divergência que o guard existe para impedir. O guard expande a variável antes de parsear.

## Duas armadilhas de guard, as duas já catalogadas

Nenhuma novidade conceitual — o que assusta é a frequência.

1. **Guard raso onde o caminho é transitivo (F115).** A paridade CI×local acusava lacuna porque o gate chama `check_tailwind_sync.py`, que chama `build_tailwind.py`. Precisou de fecho de um nível. É a mesma correção que o guard do F109 exigiu **no mesmo dia**.
2. **Guard casando a própria prosa (F116).** O bloco de comentário que **explica** o fix cita `revisions list` ao descrever o que saiu, e o guard o acusou. É a armadilha do **F87** — **4ª vez** neste repo. A correção é ignorar linha de comentário, não apagar a explicação.

## Um erro meu que vale registrar

Ao testar o guard do F116 por sabotagem, rodei `git checkout .github/workflows/deploy.yml` para reverter a sabotagem — **num arquivo cuja correção ainda não estava commitada**. O checkout restaurou o HEAD e descartou o fix junto. Percebi na verificação seguinte (o `grep` mostrou o código antigo de volta) e reapliquei.

Lição: `git checkout <arquivo>` não distingue "desfaz a sabotagem" de "desfaz o trabalho". Para sabotagem em arquivo sujo, guarde uma cópia e restaure dela — foi o que fiz nos outros testes desta sessão e funcionou.

## Verificado e limpo

Lista de migrations do `test_migrations.py` em sync com o disco (4/4); os 3 processos referenciados por `--command=/cnb/process/<type>` existem no `Procfile`; lockfile consistente por nome (as 14 deps de prod presentes, zero dep de dev vazada); ordem do deploy correta (migrations antes do serviço); `--update-secrets` (merge) e `--set-secrets` (replace) usados cada um no lugar certo; concurrency bem separada (job-level no CI pra não matar o deploy, workflow-level `deploy-prod` serializando os deploys); o smoke tolera propagação e distingue "bearer vencido" de "stack quebrado".

**Hipótese que caiu:** o `infra-setup.md` parecia declarar dois crons diferentes pro mesmo Cloud Scheduler (`0 6 BRT` e `0 7 UTC`). O segundo está na seção marcada como **HISTÓRICO** (projeto antigo). Ler o bloco inteiro derrubou o achado — segunda vez no mesmo dia, depois da barra sticky do `/admin/audit`.

## Pendente

Nada deste pacote. O que continua aberto é operacional e independe de código: **reautenticar o `gcloud`** (`gcloud auth login`) para conseguir auditar o estado vivo, e as ações humanas já listadas no CLAUDE.md (F67 custom domain, decomissionar o projeto antigo, decidir a sessão do `lucassoares`).
