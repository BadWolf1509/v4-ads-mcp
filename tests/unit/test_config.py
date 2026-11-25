import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.config import Settings


def test_settings_loads_required_envs():
    env = {
        "APP_ENV": "development",
        "DATABASE_URL": "postgresql://u:p@localhost:5432/test",
        "SESSION_SIGNING_KEY": "x" * 32,
        "AES_MASTER_KEY": "y" * 32,
        "GOOGLE_OAUTH_CLIENT_ID": "client.apps.googleusercontent.com",
        "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
    }
    with patch.dict(os.environ, env, clear=True):
        s = Settings()
        assert s.app_env == "development"
        assert s.log_level == "info"  # default


def test_settings_rejects_short_signing_key():
    env = {
        "APP_ENV": "development",
        "DATABASE_URL": "postgresql://u:p@localhost:5432/test",
        "SESSION_SIGNING_KEY": "tooshort",  # < 32
        "AES_MASTER_KEY": "y" * 32,
        "GOOGLE_OAUTH_CLIENT_ID": "client",
        "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
    }
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()


def test_login_customer_id_must_be_digits():
    env = {
        "APP_ENV": "development",
        "DATABASE_URL": "postgresql://u:p@localhost:5432/test",
        "SESSION_SIGNING_KEY": "x" * 32,
        "AES_MASTER_KEY": "y" * 32,
        "GOOGLE_OAUTH_CLIENT_ID": "client",
        "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "123-456-7890",  # has dashes
    }
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()


_BASE = {
    "APP_ENV": "development",
    "DATABASE_URL": "postgresql://u:p@localhost:5432/test",
    "SESSION_SIGNING_KEY": "x" * 32,
    "AES_MASTER_KEY": "y" * 32,
    "GOOGLE_OAUTH_CLIENT_ID": "client.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
}


def test_secret_so_com_espaco_vale_vazio():
    """O Secret Manager recusa versão vazia: `" "` é como um secret diz "Meta indisponível"."""
    env = {**_BASE, "META_APP_ID": " ", "META_APP_SECRET": " ", "META_SYSTEM_USER_TOKEN": " "}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()
    assert (s.meta_app_id, s.meta_app_secret, s.meta_system_user_token) == ("", "", "")


def test_quebra_de_linha_no_fim_do_secret_some():
    """Arquivo salvo no Notepad pode terminar em quebra de linha; o valor não pode carregá-la."""
    env = {
        **_BASE,
        "DATABASE_URL": "postgresql://u:p@h:5432/db\r\n",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890\n",
    }
    with patch.dict(os.environ, env, clear=True):
        s = Settings()
    assert s.database_url == "postgresql://u:p@h:5432/db"
    assert s.google_ads_login_customer_id == "1234567890"
