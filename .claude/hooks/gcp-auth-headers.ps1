# headersHelper for GCP MCP servers (gcp-cloud-run, gcp-cloud-logging).
#
# Outputs JSON {"Authorization": "Bearer <token>"} consumed by Claude Code's
# .mcp.json headersHelper config. Token comes from gcloud Application Default
# Credentials (`gcloud auth application-default print-access-token`).
#
# Pre-requisite (one-time): user MUST have run
#   gcloud auth application-default login
# at least once, producing ADC at %APPDATA%\gcloud\application_default_credentials.json.
#
# Fails open with empty JSON on error so the MCP connection attempt produces
# a clear auth error in Claude Code rather than a script error.

$ErrorActionPreference = "Stop"
try {
    # Find gcloud — try PATH first, then known Windows install location.
    $gcloudCmd = Get-Command gcloud -ErrorAction SilentlyContinue
    $gcloudExe = if ($gcloudCmd) { $gcloudCmd.Source } else { "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" }

    if (-not (Test-Path $gcloudExe -ErrorAction SilentlyContinue) -and -not $gcloudCmd) {
        Write-Output "{}"
        exit 0
    }

    $token = & $gcloudExe auth application-default print-access-token 2>$null
    if ([string]::IsNullOrWhiteSpace($token)) {
        Write-Output "{}"
        exit 0
    }

    $token = $token.Trim()
    $headers = @{ Authorization = "Bearer $token" }
    $json = $headers | ConvertTo-Json -Compress
    Write-Output $json
    exit 0
} catch {
    Write-Output "{}"
    exit 0
}
