# GCP MCP servers — status: REVERTIDO (limitação atual do Claude Code)

**Last updated:** 2026-05-19
**Status:** ⛔ NÃO USAR — endpoints removidos do `.mcp.json`

## TL;DR

Tentamos conectar `gcp-cloud-run` + `gcp-cloud-logging` (endpoints oficiais GA do Google) em `.mcp.json` no Sprint Sprint pós-setup-2026-05-19. **Não funciona com Claude Code v2.1.x** por limitação documentada do client. Reverido pra continuar usando `gcloud` CLI via Bash (allowlist já existe em `.claude/settings.local.json`).

Esse doc fica como registro pra revisitar quando Anthropic resolver a limitação.

## O que tentamos

| Endpoint | Status final |
|---|---|
| `https://run.googleapis.com/mcp` | ❌ `Incompatible auth server: does not support dynamic client registration` |
| `https://logging.googleapis.com/mcp` | ❌ Mesmo erro |

Configs tentadas:
1. OAuth automático (Claude Code padrão pra HTTP server novo) — falhou
2. `headersHelper` script chamando `gcloud auth application-default print-access-token` — falhou (script funciona standalone, mas Claude Code nunca chega a usá-lo)

## Root cause (não é nosso fix)

**Documentado em [Cloudflare/mcp issue #95](https://github.com/cloudflare/mcp/issues/95):**

> MCP clients (Claude Code, mcp-remote) always initiate OAuth discovery/negotiation with the server **before** sending any custom headers.

E na [doc oficial Claude Code MCP](https://code.claude.com/docs/en/mcp):

> The guide does not specify a mechanism to force Claude Code to skip OAuth discovery or prioritize static headers over dynamic OAuth registration.

Quando o endpoint GCP responde com header `WWW-Authenticate: Bearer realm=...`, o Claude Code interpreta como "tem OAuth, vou tentar DCR" e nunca chega a executar o `headersHelper`. Como os endpoints GCP usam OAuth 2.0 com client_id pré-registrado (não RFC 7591 DCR), o handshake falha antes do Bearer token ser enviado.

**É bug/limitação do Claude Code, não do GCP.** Não há workaround conhecido na visão atual do issue.

## Decisão: reverter

`.mcp.json` voltou pra ter só Supabase:

```json
{
  "mcpServers": {
    "supabase": {
      "type": "http",
      "url": "https://mcp.supabase.com/mcp?project_ref=laiqtoisehgkwfxaezjl"
    }
  }
}
```

## O que continua funcionando (fluxo pré-2026-05-19)

`gcloud` CLI via Bash. Allowlist focada já existe em `.claude/settings.local.json`:

| Categoria | Allowlist atual |
|---|---|
| Cloud Run | `Bash(gcloud run *)` |
| Cloud Logging | `Bash(gcloud logging *)` |
| Secret Manager | `Bash(gcloud secrets *)` + 11 helpers `export VAR=$(gcloud secrets versions access ...)` |
| Cloud Build | `Bash(gcloud builds *)` |
| Cloud Scheduler | `Bash(gcloud scheduler *)` |
| Beta features | `Bash(gcloud beta *)` |
| Config | `Bash(gcloud config *)` |

Comandos do dia-a-dia que continuam funcionando sem permission prompt:
```bash
gcloud run revisions list --service=v4-ads-mcp --region=southamerica-east1
gcloud run services describe v4-ads-mcp --region=southamerica-east1
gcloud logging read 'resource.labels.service_name="v4-ads-mcp" severity=ERROR' --limit=20 --format=json
gcloud secrets versions access latest --secret=database-url --project=v4-ads-mcp-prod
gcloud builds list --limit=5 --format="value(id,status,createTime)"
```

## Arquivos que ficam preservados (custo zero)

- `.claude/hooks/gcp-auth-headers.ps1` — script `headersHelper` permanece. Quando Anthropic resolver a limitação, restaurar `.mcp.json` (adicionar de volta `gcp-cloud-run` + `gcp-cloud-logging` com `headersHelper`) e tudo funciona em ~1 min.

## Quando revisitar

Sinais pra reabrir essa decisão:
- Cloudflare/mcp issue #95 fechado com fix
- Release notes do Claude Code citando "skip OAuth discovery" ou "force bearer auth" como nova feature
- Google publicando stdio MCP wrapper oficial (proxy local que faz ADC auth e expõe stdio pro Claude Code)
- Anthropic publicando workaround específico GCP/AWS/Azure

Até lá, continuar `gcloud` via Bash.

## Refs

- [Cloudflare/mcp issue #95 — API Token mode doesn't work with Claude Code](https://github.com/cloudflare/mcp/issues/95)
- [Connect Claude Code to tools via MCP — official docs](https://code.claude.com/docs/en/mcp)
- [Cloud Run MCP server reference](https://docs.cloud.google.com/run/docs/use-cloud-run-mcp) (endpoint válido, mas inacessível pelo Claude Code hoje)
- [Cloud Logging MCP server reference](https://docs.cloud.google.com/logging/docs/reference/v2_mcp/mcp) (idem)
