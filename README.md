# V4 Ads MCP

MCP server giving Claude (and other MCP clients) native control over V4 Company's Google Ads accounts. See `docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md` for the design spec.

## Dev setup

1. Install Python 3.12 or 3.13 (`pyenv install 3.12` or via your system).
2. Create venv: `uv venv` (or `python -m venv .venv`); then activate: `source .venv/bin/activate` (Linux/macOS) or `.venv\Scripts\activate` (Windows).
3. Install deps: `uv pip install -e ".[dev]"` (or `pip install -e ".[dev]"` if you don't have uv)
4. Copy `.env.example` to `.env` and fill in values.
5. Run tests: `pytest`
6. Run app locally: `uvicorn src.app:app --reload --port 8080`

## Stack

Python 3.12+ · FastAPI · MCP Python SDK · asyncpg · Postgres (Supabase) · Cloud Run · GitHub Actions

## Documentation

- Design spec: [`docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md`](docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md)
- Infra setup: [`docs/operacao/infra-setup.md`](docs/operacao/infra-setup.md)

## Repository

`https://github.com/BadWolf1509/v4-ads-mcp`
