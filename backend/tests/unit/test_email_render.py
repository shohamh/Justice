import pytest
from app.services.email import render_notification_email


def test_render_includes_title():
    html = render_notification_email(
        title="בדיקה",
        body=None,
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
    )
    assert "בדיקה" in html


def test_render_includes_body_when_provided():
    html = render_notification_email(
        title="כותרת",
        body="גוף ההודעה",
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
    )
    assert "גוף ההודעה" in html


def test_render_omits_body_when_none():
    html = render_notification_email(
        title="כותרת",
        body=None,
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
    )
    assert "גוף ההודעה" not in html


def test_render_includes_action_buttons_when_urls_provided():
    html = render_notification_email(
        title="כותרת",
        body=None,
        app_url="http://localhost:5173/constraints",
        frontend_url="http://localhost:5173",
        approve_url="http://localhost:5173/action?token=abc",
        reject_url="http://localhost:5173/action?token=xyz",
    )
    assert "http://localhost:5173/action?token=abc" in html
    assert "http://localhost:5173/action?token=xyz" in html
    assert "אשר" in html
    assert "דחה" in html


def test_render_omits_action_buttons_when_urls_absent():
    html = render_notification_email(
        title="כותרת",
        body=None,
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
    )
    assert "אשר" not in html
    assert "דחה" not in html


def test_render_includes_logo_url():
    html = render_notification_email(
        title="כותרת",
        body=None,
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
    )
    assert "favicon.svg" in html


def test_render_gender_aware_open_label_female():
    html = render_notification_email(
        title="כותרת",
        body=None,
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
        soldier_gender="female",
    )
    assert "פתחי במערכת" in html


def test_render_gender_aware_open_label_male():
    html = render_notification_email(
        title="כותרת",
        body=None,
        app_url="http://localhost:5173/schedule",
        frontend_url="http://localhost:5173",
        soldier_gender="male",
    )
    assert "פתח במערכת" in html


def test_send_email_bounds_the_smtp_connection_with_a_timeout(monkeypatch):
    """The email worker holds the outbox row lock (C1 claim) while it sends, so
    an unresponsive SMTP server must not hang the send indefinitely."""
    import types

    import app.settings as app_settings
    from app.services import email as email_service

    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, *args, **kwargs):
            calls["timeout"] = kwargs.get("timeout", args[1] if len(args) > 1 else None)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, msg):
            calls["sent"] = True

    settings = types.SimpleNamespace(
        smtp_host="smtp.example.test", smtp_port=587, smtp_user="", smtp_password="", smtp_from="noreply@example.test",
    )
    monkeypatch.setattr(app_settings, "get_settings", lambda: settings)
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)

    assert email_service.send_email(to="a@example.test", subject="s", body="b") is True
    assert calls["sent"] is True
    assert calls["timeout"] is not None and 0 < calls["timeout"] <= 60
