from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root env files, resolved by absolute path so they're found regardless
# of the process working directory (backend/ for local runs, repo root for
# others). .env.defaults holds the non-secret, committed dev defaults; .env
# holds local secrets/overrides (gitignored) and is read second, so any value
# it sets wins over .env.defaults.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULTS_FILE = _REPO_ROOT / ".env.defaults"
_SECRETS_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_DEFAULTS_FILE, _SECRETS_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = Field(alias="DATABASE_URL")
    db_admin_url: str = Field(alias="DB_ADMIN_URL")
    jwt_secret: str = Field(alias="JWT_SECRET", min_length=32)
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_minutes: int = Field(default=15, alias="ACCESS_TOKEN_MINUTES")
    refresh_token_days: int = Field(default=30, alias="REFRESH_TOKEN_DAYS")
    allowed_origins: str = Field(default="http://localhost:5173", alias="ALLOWED_ORIGINS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    login_rate_limit: str = Field(default="10/5minutes", alias="LOGIN_RATE_LIMIT")
    login_account_rate_limit: str = Field(default="10/5minutes", alias="LOGIN_ACCOUNT_RATE_LIMIT")
    invite_code_rate_limit: str = Field(default="20/hour", alias="INVITE_CODE_RATE_LIMIT")
    cookie_secure: bool = Field(default=True, alias="COOKIE_SECURE")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_bot_username: str = Field(default="", alias="TELEGRAM_BOT_USERNAME")
    frontend_url: str = Field(default="http://localhost:5173", alias="FRONTEND_URL")

    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", alias="SMTP_FROM")

    bootstrap_admin_personal_number: str | None = Field(
        default=None, alias="BOOTSTRAP_ADMIN_PERSONAL_NUMBER"
    )
    bootstrap_admin_full_name: str | None = Field(default=None, alias="BOOTSTRAP_ADMIN_FULL_NAME")
    bootstrap_admin_password: str | None = Field(default=None, alias="BOOTSTRAP_ADMIN_PASSWORD")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
