"""Application settings loaded from environment variables."""

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration; values come from env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    app_env: Literal["development", "staging", "production"]
    app_timezone: str = "America/Sao_Paulo"
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    # Database
    database_url: str

    # Crypto
    session_signing_key: str = Field(min_length=32)
    aes_master_key: str = Field(min_length=32)

    # Google OAuth (for the panel's Google Ads connection)
    google_oauth_client_id: str
    google_oauth_client_secret: str

    # Google Ads API
    google_ads_developer_token: str
    google_ads_login_customer_id: str

    # Meta Ads API (Sprint M.1 foundation)
    meta_app_id: str = ""
    meta_app_secret: str = ""
    # Meta Ads — system user token (Modelo B, Secret Manager: meta-system-user-token).
    # Token NÃO expira; vazio = feature de execução Meta indisponível (erro PT-BR amigável).
    meta_system_user_token: str = ""

    # Supabase (auth + DB)
    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str

    # Public URL for MCP endpoint (used in /sessions + /help connection snippets).
    # Projeto GCP novo (v4-ads-mcp, migração 2026-06-30). Override via env
    # PUBLIC_BASE_URL no Cloud Run (deploy.yml --set-env-vars).
    public_base_url: str = "https://v4-ads-mcp-299432068772.southamerica-east1.run.app"

    # Governance: F73 — cap diario por gestor (rate_counters chave "mgr:<uuid>",
    # paralelo ao cap global por developer_token_id).
    manager_daily_quota: int = 5000

    # Backup semanal do DB -> GCS (Cloud Run Job src/jobs/backup.py). Bucket
    # southamerica-east1/UBLA/lifecycle delete>90d já provisionado fora deste código.
    backup_bucket: str = "v4-ads-mcp-backups"

    # Phase 2: invite-only allowlist bootstrap
    # Comma-separated emails that get auto-promoted to admin on first OAuth login,
    # but ONLY when the managers table is empty. Once seeded, this value is dormant.
    # Set on Cloud Run via env var. Not a secret — it's an allowlist of bootstrap users.
    bootstrap_admin_emails: str = ""

    @property
    def bootstrap_admin_emails_set(self) -> set[str]:
        """Parse the comma-separated env into a normalized lowercased set."""
        return {e.strip().lower() for e in self.bootstrap_admin_emails.split(",") if e.strip()}

    @field_validator("google_ads_login_customer_id")
    @classmethod
    def validate_customer_id_format(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("google_ads_login_customer_id must be digits only (no dashes)")
        return v


def get_settings() -> Settings:
    """Factory used by FastAPI dependency injection."""
    return Settings()  # type: ignore[call-arg]
