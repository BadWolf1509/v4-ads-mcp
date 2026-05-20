# PostToolUse hook: auto-format Python files with ruff after Edit/Write/MultiEdit.
# Stdin: JSON with tool_input.file_path. Exit 0 silently if not a .py file or ruff unavailable.
# Non-blocking: any failure is silent to avoid breaking the edit flow.

$ErrorActionPreference = "Stop"
try {
    $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $filePath = $payload.tool_input.file_path
    if (-not $filePath) { exit 0 }
    if ($filePath -notmatch '\.py$') { exit 0 }

    $ruff = Join-Path $env:CLAUDE_PROJECT_DIR ".venv\Scripts\ruff.exe"
    if (-not (Test-Path $ruff)) {
        $cmd = Get-Command ruff -ErrorAction SilentlyContinue
        if (-not $cmd) { exit 0 }
        $ruff = $cmd.Source
    }

    & $ruff format $filePath *>$null
    exit 0
} catch {
    exit 0
}
