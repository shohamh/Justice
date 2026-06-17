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
