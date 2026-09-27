from app.services.hr.errors import HrApiError, HrClientNotConfigured


def test_hr_client_not_configured_is_exception():
    err = HrClientNotConfigured("base_url and api_key are required")
    assert isinstance(err, Exception)
    assert "required" in str(err)


def test_hr_api_error_carries_status_and_url():
    err = HrApiError(status_code=500, message="Internal Server Error", url="https://hr.example/api/v1/user")
    assert err.status_code == 500
    assert err.message == "Internal Server Error"
    assert err.url == "https://hr.example/api/v1/user"
    assert "500" in str(err)


def test_hr_api_error_without_status_code():
    err = HrApiError(status_code=None, message="Connection timed out", url="https://hr.example/api/v1/user")
    assert err.status_code is None
    assert "timed out" in str(err)
