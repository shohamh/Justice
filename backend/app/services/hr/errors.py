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


class HrIdentityConflictError(ValueError):
    """An HR record's identity cannot be applied without guessing.

    Raised by the sync's identity checks and caught per person by
    ``run_person_sync``, which records it as an admin-visible warning and
    continues the run. ``kind`` is ``duplicate_personal_number``,
    ``email_collision``, ``ad_username_collision`` or ``email_invalid``;
    ``reason`` says how the sync resolved it (``latest``, ``preferred_stale``,
    ``preferred_ambiguous``, ``preferred_invalid``, ``email_not_applied``).
    ``candidates`` are the HR records involved (see
    ``app.services.hr.conflicts.HrCandidate``); ``applied_index`` indexes the
    one that is applied, None if none is. ``str(error)`` carries no personal
    data.
    """

    def __init__(
        self,
        *,
        personal_number: str,
        kind: str,
        reason: str,
        candidates: list,
        applied_index: int | None,
        colliding_soldier_ids: list[str] | None = None,
    ) -> None:
        self.personal_number = personal_number
        self.kind = kind
        self.reason = reason
        self.candidates = candidates
        self.applied_index = applied_index
        self.colliding_soldier_ids = colliding_soldier_ids or []
        super().__init__(f"{kind} ({reason}) for personal number {personal_number}")
