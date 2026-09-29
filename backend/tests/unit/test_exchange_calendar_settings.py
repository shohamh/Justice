import pytest
from pydantic import ValidationError

from app import exchange_calendar_worker
from app.settings import Settings

_CORE_ENV = {
    "DATABASE_URL": "postgresql+psycopg://justice:test@localhost/justice",
    "DB_ADMIN_URL": "postgresql+psycopg://admin:test@localhost/justice",
    "JWT_SECRET": "test-only-jwt-secret-that-is-long-enough",
}
_EXCHANGE_ENV = (
    "EXCHANGE_CALENDAR_ENABLED",
    "EXCHANGE_EWS_URL",
    "EXCHANGE_MAILBOX",
    "EXCHANGE_USERNAME",
    "EXCHANGE_PASSWORD",
    "EXCHANGE_AUTH_TYPE",
    "EXCHANGE_REQUESTS_PER_MINUTE",
)


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name, value in _CORE_ENV.items():
        monkeypatch.setenv(name, value)
    for name in _EXCHANGE_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_exchange_calendar_is_disabled_when_unconfigured(
    settings_env: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None)

    assert settings.exchange_calendar_enabled is False


def test_exchange_calendar_request_limit_accepts_supported_boundaries(
    settings_env: pytest.MonkeyPatch,
) -> None:
    for rate in (1, 200):
        settings_env.setenv("EXCHANGE_REQUESTS_PER_MINUTE", str(rate))
        assert Settings(_env_file=None).exchange_requests_per_minute == rate


def test_exchange_calendar_request_limit_rejects_values_outside_supported_range(
    settings_env: pytest.MonkeyPatch,
) -> None:
    for rate in (0, 201):
        settings_env.setenv("EXCHANGE_REQUESTS_PER_MINUTE", str(rate))
        with pytest.raises(ValidationError):
            Settings(_env_file=None)


def test_enabled_worker_fails_clearly_without_required_settings_or_secret(
    settings_env: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "test-only-exchange-password"
    settings_env.setenv("EXCHANGE_CALENDAR_ENABLED", "true")
    settings_env.setenv("EXCHANGE_PASSWORD", secret)
    settings = Settings(_env_file=None)

    with pytest.raises(
        ValueError,
        match="EXCHANGE_EWS_URL.*EXCHANGE_MAILBOX.*EXCHANGE_USERNAME",
    ) as exc_info:
        exchange_calendar_worker.main(settings=settings)

    assert secret not in str(exc_info.value)
    assert secret not in caplog.text


def test_enabled_worker_identifies_missing_password_without_disclosing_values(
    settings_env: pytest.MonkeyPatch,
) -> None:
    settings_env.setenv("EXCHANGE_CALENDAR_ENABLED", "true")
    settings_env.setenv(
        "EXCHANGE_EWS_URL", "https://exchange.example.local/EWS/Exchange.asmx"
    )
    settings_env.setenv("EXCHANGE_MAILBOX", "svc_justice@example.local")
    settings_env.setenv("EXCHANGE_USERNAME", "DOMAIN\\svc_justice")
    settings = Settings(_env_file=None)

    with pytest.raises(ValueError, match="EXCHANGE_PASSWORD"):
        exchange_calendar_worker.main(settings=settings)


def test_exchange_password_is_hidden_from_settings_representation(
    settings_env: pytest.MonkeyPatch,
) -> None:
    secret = "test-only-exchange-password"
    settings_env.setenv("EXCHANGE_PASSWORD", secret)
    settings = Settings(_env_file=None)

    assert secret not in repr(settings)
    assert secret not in str(settings)


def test_exchange_password_can_be_loaded_from_a_deployment_secret_file(
    settings_env: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    secret = "test-only-exchange-password"
    (tmp_path / "EXCHANGE_PASSWORD").write_text(secret, encoding="utf-8")

    settings = Settings(_env_file=None, _secrets_dir=tmp_path)

    assert settings.exchange_password is not None
    assert settings.exchange_password.get_secret_value() == secret
    assert secret not in repr(settings)
