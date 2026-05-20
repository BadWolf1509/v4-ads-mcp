# PreToolUse hook: block Edit/Write on src/db/migrations/*.sql files that are already
# committed to git history. Migrations are append-only by repo convention (see CLAUDE.md):
# the _migrations tracker table does not re-apply edited files, so editing a deployed
# migration silently drifts the production schema from local.
#
# Stdin: JSON with tool_input.file_path.
# Exit 0 with permissionDecision="deny" to block, or exit 0 silently to allow.
# Errors fail-open (allow) to avoid breaking the flow.

$ErrorActionPreference = "Stop"
try {
    $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $filePath = $payload.tool_input.file_path
    if (-not $filePath) { exit 0 }

    $normalized = $filePath.Replace('\', '/')
    if ($normalized -notmatch 'src/db/migrations/.+\.sql$') { exit 0 }

    Set-Location $env:CLAUDE_PROJECT_DIR
    $relPath = $normalized -replace '^.*src/db/migrations/', 'src/db/migrations/'
    $gitLog = & git log --all --pretty=format:"%H" -- $relPath 2>$null
    if ([string]::IsNullOrWhiteSpace($gitLog)) { exit 0 }

    $fileName = Split-Path $normalized -Leaf
    $reasonLines = @(
        "Migration '$fileName' ja esta commitada em git history.",
        "",
        "Convencao do repo (CLAUDE.md): migrations sao append-only. O tracker _migrations nao re-aplica, entao editar uma migration ja deployada faz o schema de producao divergir do local.",
        "",
        "Acao recomendada: crie src/db/migrations/NNN+1_<descricao>.sql para a alteracao.",
        "",
        "Se voce precisa MESMO editar (ex: rollback emergencial pre-deploy, fix de typo em migration que ainda nao foi para producao), confirme com o usuario antes de prosseguir."
    )
    $reason = $reasonLines -join "`n"

    $response = @{
        hookSpecificOutput = @{
            hookEventName = "PreToolUse"
            permissionDecision = "deny"
            permissionDecisionReason = $reason
        }
    } | ConvertTo-Json -Depth 5 -Compress

    Write-Output $response
    exit 0
} catch {
    exit 0
}
