from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root env files, resolved by absolute path so they're found regardless
# of the process working directory (backend/ for local runs, repo root for
# others). .env.defaults holds the non-secret, committed dev defaults; .env
# holds local secrets/overrides (gitignored) and is read second, so any value
# it sets wins over .env.defaults.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULTS_FILE = _REPO_ROOT / ".env.defaults"
_SECRETS_FILE = _REPO_ROOT / ".env"
_RUNTIME_SECRETS_DIR = Path("/run/secrets")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_DEFAULTS_FILE, _SECRETS_FILE),
        env_file_encoding="utf-8",
        secrets_dir=(
            str(_RUNTIME_SECRETS_DIR) if _RUNTIME_SECRETS_DIR.is_dir() else None
        ),
        extra="ignore",
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
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    loki_url: str = Field(default="", alias="LOKI_URL")
    error_log_rate_limit_max_per_window: int = Field(default=10, alias="ERROR_LOG_RATE_LIMIT_MAX_PER_WINDOW")
    error_log_rate_limit_window_seconds: float = Field(default=60.0, alias="ERROR_LOG_RATE_LIMIT_WINDOW_SECONDS")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_bot_username: str = Field(default="", alias="TELEGRAM_BOT_USERNAME")
    frontend_url: str = Field(default="http://localhost:5173", alias="FRONTEND_URL")

    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", alias="SMTP_FROM")

    hr_api_base_url: str = Field(default="", alias="HR_API_BASE_URL")
    hr_api_key: str = Field(default="", alias="HR_API_KEY")
    hr_api_ca_bundle_path: str = Field(default="", alias="HR_API_CA_BUNDLE_PATH")
    hr_api_page_size: int = Field(default=200, alias="HR_API_PAGE_SIZE")

    exchange_calendar_enabled: bool = Field(default=False, alias="EXCHANGE_CALENDAR_ENABLED")
    exchange_ews_url: str = Field(default="", alias="EXCHANGE_EWS_URL")
    exchange_mailbox: str = Field(default="", alias="EXCHANGE_MAILBOX")
    exchange_username: str = Field(default="", alias="EXCHANGE_USERNAME")
    exchange_password: SecretStr | None = Field(default=None, alias="EXCHANGE_PASSWORD")
    exchange_auth_type: str = Field(default="", alias="EXCHANGE_AUTH_TYPE")
    exchange_requests_per_minute: int = Field(
        default=200, ge=1, le=200, alias="EXCHANGE_REQUESTS_PER_MINUTE"
    )

    bootstrap_admin_personal_number: str | None = Field(
        default=None, alias="BOOTSTRAP_ADMIN_PERSONAL_NUMBER"
    )
    bootstrap_admin_full_name: str | None = Field(default=None, alias="BOOTSTRAP_ADMIN_FULL_NAME")
    bootstrap_admin_password: str | None = Field(default=None, alias="BOOTSTRAP_ADMIN_PASSWORD")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def hr_sync_enabled(self) -> bool:
        return bool(self.hr_api_base_url and self.hr_api_key)

    def require_exchange_calendar_configuration(self) -> tuple[str, str, str, str]:
        """Return worker credentials or report only which setting names are missing."""
        password = (
            self.exchange_password.get_secret_value()
            if self.exchange_password is not None
            else ""
        )
        required = {
            "EXCHANGE_EWS_URL": self.exchange_ews_url,
            "EXCHANGE_MAILBOX": self.exchange_mailbox,
            "EXCHANGE_USERNAME": self.exchange_username,
            "EXCHANGE_PASSWORD": password,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                "Exchange calendar is enabled but required settings are missing: "
                + ", ".join(missing)
            )
        return (
            self.exchange_ews_url,
            self.exchange_mailbox,
            self.exchange_username,
            password,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
