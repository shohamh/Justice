import httpx
import pytest
import respx

from app.services.hr.client import HrApiClient
from app.services.hr.errors import HrApiError, HrClientNotConfigured
from app.services.hr.tests.conftest import load_fixture

# A throwaway self-signed cert used only to satisfy httpx's eager
# SSLContext parsing of `verify=<path>` at AsyncClient construction time
# (see test_client_uses_ca_bundle_path_when_set below).
_SELF_SIGNED_TEST_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIICxTCCAa2gAwIBAgIUOfDmt9f3KQzbvN3Y4vtYvTdSW0YwDQYJKoZIhvcNAQEL
BQAwEjEQMA4GA1UEAwwHdGVzdC1jYTAeFw0yNjA5MjIxODA3MTFaFw0zNjA5MTkx
ODA3MTFaMBIxEDAOBgNVBAMMB3Rlc3QtY2EwggEiMA0GCSqGSIb3DQEBAQUAA4IB
DwAwggEKAoIBAQDMUqBcm7KIzxRRNG+JezdcrU9+Mg8yPrFz7fT6H38FcTZ/TVWD
FBRqLs0pwEhNP6z2whapKAWiGyzLmYYv3do9fQMS6yjrN+cahJw0qpAbkPOzYw2d
HdPPz9UBUFGy58aanPMC4fdXK91cPnjtqlEZjOSpttBP0PCqBXe3Wi1Avqlkla2N
H7L1eE/9MWF3qFFBbc+3z3S3nO992hLm/b7r5nWvRB0bTjVYlPbIrfElIzu8Y6Q8
JDiHkoNctlMCpZSzrzUNj8RBDjmB2SP0arZGkjJOeSwwn7BjPFeVV1afg4LxHE24
XhePRdnI7kSZtiXc09gg+QfAvKt48q32e5afAgMBAAGjEzARMA8GA1UdEwEB/wQF
MAMBAf8wDQYJKoZIhvcNAQELBQADggEBADOrZvU9m2Tm5IZu1ipBZ1l7y6QRhNDx
UIsLXRfGwIUOP0DHx4J45oKNX1ZCGTxRK+lkReDBJLMg+gOQpp4ayNlXJfGWjPQV
6MuXoGuzbxlWs1dHUBK616gC9HmdqnAvI/GT5v51TqL7ZG6JB4phuaestVUdh3FG
GvFg9MbrkB+IyIhh3cBBEfouEVsOjlTFuuiyRDmQ2C+P/pIqRQC4acvvGosXjVa4
9xUEgQ1sGOdq62fKD/NFO9ugMr4SesR4TWpioqTi/dzho1JNXeiWRhbjPoPGGBHO
pp/HkHEybgRmxP4jAfwjKanTga6AKwE7cr0g6lKZCgKsw/V6VJz/et8=
-----END CERTIFICATE-----
"""


def test_raises_when_base_url_missing(hr_api_key):
    with pytest.raises(HrClientNotConfigured):
        HrApiClient(base_url="", api_key=hr_api_key)


def test_raises_when_api_key_missing(hr_base_url):
    with pytest.raises(HrClientNotConfigured):
        HrApiClient(base_url=hr_base_url, api_key="")


@pytest.mark.asyncio
async def test_get_user_sends_auth_header_and_parses_response(hr_base_url, hr_api_key):
    fixture = load_fixture("user_single.json")
    with respx.mock(base_url=hr_base_url) as mock:
        route = mock.get("/api/v1/user/personalNumber/7654321").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            user = await client.get_user("personalNumber", "7654321")
        assert route.called
        sent_request = route.calls.last.request
        assert sent_request.headers["X-API-KEY"] == hr_api_key
        assert user.personal_number == "7654321"
        assert user.full_name == "John Doe"


@pytest.mark.asyncio
async def test_get_user_raises_hr_api_error_on_404(hr_base_url, hr_api_key):
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/user/personalNumber/missing").mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            with pytest.raises(HrApiError) as exc_info:
                await client.get_user("personalNumber", "missing")
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_user_raises_hr_api_error_on_500(hr_base_url, hr_api_key):
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/user/personalNumber/7654321").mock(return_value=httpx.Response(500, text="boom"))
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            with pytest.raises(HrApiError) as exc_info:
                await client.get_user("personalNumber", "7654321")
        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_get_user_raises_hr_api_error_on_timeout(hr_base_url, hr_api_key):
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/user/personalNumber/7654321").mock(side_effect=httpx.ConnectTimeout("timed out"))
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            with pytest.raises(HrApiError) as exc_info:
                await client.get_user("personalNumber", "7654321")
        assert exc_info.value.status_code is None


@pytest.mark.asyncio
async def test_get_user_raises_hr_api_error_on_malformed_json(hr_base_url, hr_api_key):
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/user/personalNumber/7654321").mock(
            return_value=httpx.Response(200, text="not json")
        )
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            with pytest.raises(HrApiError):
                await client.get_user("personalNumber", "7654321")


@pytest.mark.asyncio
async def test_get_user_image_returns_raw_bytes(hr_base_url, hr_api_key):
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"fake-image-data"
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/user/personalNumber/7654321/image").mock(
            return_value=httpx.Response(200, content=image_bytes, headers={"content-type": "image/png"})
        )
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            result = await client.get_user_image("personalNumber", "7654321")
        assert result == image_bytes


@pytest.mark.asyncio
async def test_get_group_parses_response(hr_base_url, hr_api_key):
    fixture = load_fixture("group_single.json")
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/group/g1").mock(return_value=httpx.Response(200, json=fixture))
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            group = await client.get_group("g1")
        assert group.id == "g1"
        assert group.parent_id == "b1"


@pytest.mark.asyncio
async def test_check_connection_success(hr_base_url, hr_api_key):
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/user", params={"take": "1"}).mock(return_value=httpx.Response(200, json=[]))
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            result = await client.check_connection()
        assert result.ok is True
        assert result.latency_ms >= 0
        assert result.error is None


@pytest.mark.asyncio
async def test_check_connection_failure(hr_base_url, hr_api_key):
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/user", params={"take": "1"}).mock(return_value=httpx.Response(503, text="down"))
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            result = await client.check_connection()
        assert result.ok is False
        assert result.error is not None


def test_client_uses_system_trust_store_when_no_ca_bundle(hr_base_url, hr_api_key):
    client = HrApiClient(base_url=hr_base_url, api_key=hr_api_key)
    assert client._verify is True


def test_client_uses_ca_bundle_path_when_set(hr_base_url, hr_api_key, tmp_path):
    # httpx (0.28+) eagerly builds an SSLContext from `verify=<path>` at
    # AsyncClient construction time, so the file must contain a real,
    # parseable certificate rather than arbitrary placeholder text.
    ca_file = tmp_path / "internal-ca.pem"
    ca_file.write_text(_SELF_SIGNED_TEST_CERT_PEM)
    client = HrApiClient(base_url=hr_base_url, api_key=hr_api_key, ca_bundle_path=str(ca_file))
    assert client._verify == str(ca_file)
