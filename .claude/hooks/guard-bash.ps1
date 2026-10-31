# PreToolUse hook: bloqueia quatro formas de comando que ja causaram dano aqui e
# que a regra escrita nao impediu de voltar (ver Don't do do CLAUDE.md):
#
#   1. gate ligado ao `git commit` por algo que nao seja `&&`: o commit roda
#      mesmo com o gate vermelho (02/09, 27/09 e 02/10).
#   2. `gcloud` com stderr silenciado: a reautenticacao pendura em silencio
#      (9h39 em uma vez).
#   3. `git checkout` de arquivo: descarta trabalho nao commitado.
#   4. espera sem limite de tempo: um `until grep` num log apagado rodou por
#      23h30 em 30/10, porque falhar parecia "ainda nao terminou".
#
# Stdin: JSON com tool_input.command.
# Fora de escopo e erro de parse falham ABERTO: este guard roda em todo comando,
# e negar quando nao entendeu pararia a sessao inteira.

function Write-Deny([string]$motivo) {
    @{
        hookSpecificOutput = @{
            hookEventName            = "PreToolUse"
            permissionDecision       = "deny"
            permissionDecisionReason = $motivo
        }
    } | ConvertTo-Json -Depth 5 -Compress | Write-Output
    exit 0
}

try {
    $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $comando = [string]$payload.tool_input.command
} catch {
    exit 0
}
if (-not $comando) { exit 0 }

# Corpo de heredoc e texto, nao comando: mensagem de commit pode citar estas regras.
$cmd = ($comando -replace "(?s)<<-?\s*['""]?\w+.*$", "")

if ($cmd -match "(?s)check_pre_push(?:_full)?\.py(?<meio>.*?)git\s+commit") {
    $meio = $Matches["meio"]
    if ($meio -match "(?<!\|)\|(?!\|)|;|`n") {
        Write-Deny "Gate ligado ao git commit sem &&: o commit roda mesmo com o gate vermelho. Forma aceita, numa linha: gate > log 2>&1 && git add ... && git commit ..."
    }
}

if ($cmd -match "gcloud\b[^\n|;&]*2>\s*(/dev/null|\`$null|NUL)") {
    Write-Deny "gcloud com stderr silenciado pendura em silencio quando a credencial expira. Rode sem o redirect."
}

$arquivo = "git\s+checkout\b[^\n|;&]*(\s--\s|\s\.(\s|$)|\s[^\s-][^\s]*\.[A-Za-z0-9]{1,6}(\s|$))"
if ($cmd -match $arquivo) {
    Write-Deny "git checkout de arquivo descarta trabalho nao commitado. Para sabotar um teste, copie o arquivo e restaure da copia. Se for mesmo necessario, peca ao humano."
}

$espera = "(?m)(^|[;&|(]\s*)(until\s|while\s+(true|:)\b)"
if ($cmd -match $espera -and $cmd -notmatch "\btimeout\s+\d") {
    Write-Deny "Espera sem limite de tempo nunca termina se a condicao nao vier. Use: timeout 590 bash -c 'until ...; do sleep 20; done'. Nao descarte o erro da condicao com 2>/dev/null."
}

exit 0
