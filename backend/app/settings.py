from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    db_admin_url: str = Field(alias="DB_ADMIN_URL")
    jwt_secret: str = Field(alias="JWT_SECRET", min_length=32)
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_minutes: int = Field(default=15, alias="ACCESS_TOKEN_MINUTES")
    refresh_token_days: int = Field(default=30, alias="REFRESH_TOKEN_DAYS")
    allowed_origins: str = Field(default="http://localhost:5173", alias="ALLOWED_ORIGINS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    login_rate_limit: str = Field(default="5/5minutes", alias="LOGIN_RATE_LIMIT")

    bootstrap_admin_personal_number: str | None = Field(default=None, alias="BOOTSTRAP_ADMIN_PERSONAL_NUMBER")
    bootstrap_admin_full_name: str | None = Field(default=None, alias="BOOTSTRAP_ADMIN_FULL_NAME")
    bootstrap_admin_password: str | None = Field(default=None, alias="BOOTSTRAP_ADMIN_PASSWORD")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
