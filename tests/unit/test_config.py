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
        "GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
    }
    with patch.dict(os.environ, env, clear=True):
        s = Settings()
        assert s.app_env == "development"
        assert s.app_timezone == "America/Sao_Paulo"  # default
        assert s.log_level == "info"  # default


def test_settings_rejects_short_signing_key():
    env = {
        "APP_ENV": "development",
        "DATABASE_URL": "postgresql://u:p@localhost:5432/test",
        "SESSION_SIGNING_KEY": "tooshort",  # < 32
        "AES_MASTER_KEY": "y" * 32,
        "GOOGLE_OAUTH_CLIENT_ID": "client",
        "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
        "GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
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
        "GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "123-456-7890",  # has dashes
    }
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValidationError):
        Settings()
