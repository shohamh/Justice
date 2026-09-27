class HrClientNotConfigured(Exception):
    """Raised when HrApiClient is constructed without both a base URL and
    an API key."""


class HrApiError(Exception):
    """Raised for any non-2xx response, network error, or malformed JSON
    from the HR API. No retry is attempted by the client."""

    def __init__(self, *, status_code: int | None, message: str, url: str | None) -> None:
        self.status_code = status_code
        self.message = message
        self.url = url
        super().__init__(f"HR API error (status={status_code}, url={url}): {message}")
