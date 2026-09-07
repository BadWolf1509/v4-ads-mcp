# PreToolUse hook: bloqueia Edit/Write em src/db/migrations/*.sql que ja tenha
# chegado a origin/main. Migrations sao append-only por convencao do repo
# (CLAUDE.md): o tracker _migrations nao re-aplica arquivo editado, entao mexer
# numa migration ja DEPLOYADA faz o schema de producao divergir do local.
#
# Stdin: JSON com tool_input.file_path.
# Exit 0 com permissionDecision="deny" pra bloquear, ou exit 0 silencioso pra liberar.
#
# ---------------------------------------------------------------------------
# Por que o proxy e `origin/main` e nao `git log --all` (mudanca de 2026-09-06)
#
# A versao anterior casava QUALQUER commit em QUALQUER branch. Nesta ferramenta
# "deployada" tem definicao precisa: chegou em `main`, porque o job de migration
# roda no deploy e o deploy e gated em `main` (ci.yml job test -> job deploy).
# Migration commitada numa branch de feature nunca rodou em lugar nenhum.
#
# O proxy largo nao era so inconveniente: TODA correcao de migration antes do
# merge disparava o bloqueio, e um guard que dispara errado com frequencia
# treina quem trabalha a contorna-lo. Em 2026-09-06 foi exatamente o que
# aconteceu — o bloqueio veio numa 009 nao mesclada, e a correcao acabou
# aplicada por `sed`, passando por fora do guard. Guard preciso e mais seguro
# que guard largo, porque e obedecido.
#
# Fallback conservador: se `origin/main` nao resolver (clone sem remote, fetch
# nunca feito), volta ao proxy largo. Na duvida, bloqueia.
#
# ---------------------------------------------------------------------------
# Por que a falha e FECHADA, e por que so depois do check de caminho
#
# A versao anterior terminava em `catch { exit 0 }`: qualquer erro — git
# indisponivel, caminho estranho, tropeco do PowerShell — liberava a edicao em
# silencio. Pra um guard que protege schema de producao, a falha segura e
# bloquear e obrigar o humano a olhar.
#
# Mas o fail-closed e ESCOPADO. Enquanto nao se sabe qual arquivo o tool vai
# tocar, negar bloquearia toda edicao do repositorio — entao a fase de parse e
# de checagem de caminho falha ABERTO. Depois de saber que e uma migration, o
# guard esta em escopo e falha FECHADO.

function Write-Deny([string[]]$lines) {
    $response = @{
        hookSpecificOutput = @{
            hookEventName            = "PreToolUse"
            permissionDecision       = "deny"
            permissionDecisionReason = ($lines -join "`n")
        }
    } | ConvertTo-Json -Depth 5 -Compress
    Write-Output $response
    exit 0
}

# --- Fase 1: fora de escopo falha ABERTO ------------------------------------
$ErrorActionPreference = "Stop"
try {
    $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $filePath = $payload.tool_input.file_path
} catch {
    exit 0
}
if (-not $filePath) { exit 0 }

$normalized = $filePath.Replace('\', '/')
if ($normalized -notmatch 'src/db/migrations/.+\.sql$') { exit 0 }

# --- Fase 2: e migration, entao o guard falha FECHADO ------------------------
$fileName = Split-Path $normalized -Leaf

try {
    # CLAUDE_PROJECT_DIR so existe sob o Claude Code. Este hook tambem e usado
    # pelo Codex (.codex/hooks.json), que nao define a variavel — sem o
    # fallback, o Set-Location falhava e o guard liberava a edicao em silencio.
    $root = if ($env:CLAUDE_PROJECT_DIR) { $env:CLAUDE_PROJECT_DIR }
            else { & git rev-parse --show-toplevel 2>$null }
    if ($root) { Set-Location $root }
    $relPath = $normalized -replace '^.*src/db/migrations/', 'src/db/migrations/'

    # O arquivo ja esteve em origin/main? Se nunca esteve, nunca rodou.
    $historico = & git log origin/main --pretty=format:"%H" -- $relPath 2>$null
    if ($LASTEXITCODE -ne 0) {
        # origin/main nao resolveu — volta ao proxy largo, conservador.
        $historico = & git log --all --pretty=format:"%H" -- $relPath 2>$null
        $escopo = "git history (origin/main nao resolveu; usando o proxy largo)"
    } else {
        $escopo = "origin/main"
    }

    if ([string]::IsNullOrWhiteSpace($historico)) { exit 0 }

    Write-Deny @(
        "Migration '$fileName' ja esta em $escopo — ou seja, ja rodou (ou vai rodar) em producao.",
        "",
        "Convencao do repo (CLAUDE.md): migrations sao append-only. O tracker _migrations nao re-aplica arquivo editado, entao editar esta migration faz o schema de producao divergir do local, em silencio.",
        "",
        "Acao correta: crie src/db/migrations/NNN+1_<descricao>.sql com a alteracao.",
        "",
        "NAO contorne este bloqueio. Se voce acha que ele esta errado, PARE e pergunte ao humano — nao tente outra ferramenta (sed, python, shell) pra aplicar a mesma edicao. Rotear por fora de um guard e sempre defeito, mesmo quando a conclusao sobre o risco esta certa."
    )
} catch {
    Write-Deny @(
        "Guard de migration NAO conseguiu avaliar '$fileName': $($_.Exception.Message)",
        "",
        "Bloqueando por seguranca. Este guard protege o schema de producao, e a falha segura e negar — a versao anterior liberava a edicao em silencio quando algo dava errado, que e o pior desfecho possivel pra um guard.",
        "",
        "PARE e pergunte ao humano. Nao contorne com outra ferramenta."
    )
}
