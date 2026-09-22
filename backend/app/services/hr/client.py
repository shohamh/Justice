import ssl
import time
from collections.abc import AsyncIterator

import httpx

from app.services.hr.errors import HrApiError, HrClientNotConfigured
from app.services.hr.schemas import (
    HrGroup,
    HrGroupWithReports,
    HrHealthCheckResult,
    HrUser,
    HrUserWithReports,
)


class HrApiClient:
    """Async client for the external HR (משא"ן) API. Raises HrApiError on
    any failure; no retry is attempted here — retry policy belongs to the
    sync engine that calls this client."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        ca_bundle_path: str = "",
        page_size: int = 200,
        timeout: float = 10.0,
    ) -> None:
        if not base_url or not api_key:
            raise HrClientNotConfigured("HrApiClient requires both base_url and api_key")
        self._page_size = page_size
        self._verify: bool | str = ca_bundle_path or True
        # httpx>=0.28 deprecates passing a bare path string as `verify=`;
        # build an explicit SSLContext to avoid the DeprecationWarning while
        # still keeping self._verify as the plain bool/str the tests check.
        transport_verify: bool | ssl.SSLContext = (
            ssl.create_default_context(cafile=self._verify) if isinstance(self._verify, str) else self._verify
        )
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-KEY": api_key},
            verify=transport_verify,
            timeout=timeout,
        )

    async def __aenter__(self) -> "HrApiClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        try:
            response = await self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise HrApiError(status_code=None, message=str(exc), url=str(self._http.base_url) + path) from exc
        if response.status_code >= 400:
            raise HrApiError(
                status_code=response.status_code,
                message=response.text,
                url=str(response.url),
            )
        try:
            return response.json()
        except ValueError as exc:
            raise HrApiError(
                status_code=response.status_code, message=f"malformed JSON: {exc}", url=str(response.url)
            ) from exc

    async def get_user(self, prop: str, id: str) -> HrUser:
        data = await self._get(f"/api/v1/user/{prop}/{id}")
        return HrUser.model_validate(data)

    async def get_user_subhierarchy(
        self, prop: str, id: str, maximum_depth: int | None = None
    ) -> HrUserWithReports:
        params = {"maximumDepth": maximum_depth} if maximum_depth is not None else None
        data = await self._get(f"/api/v1/user/{prop}/{id}/subhierarchy", params=params)
        return HrUserWithReports.model_validate(data)

    async def iter_users(self, **filters: object) -> AsyncIterator[HrUser]:
        if "image" in filters:
            filters["photo"] = filters.pop("image")
        page = 1
        while True:
            params = {**filters, "take": self._page_size, "page": page}
            data = await self._get("/api/v1/user", params=params)
            records = [HrUser.model_validate(item) for item in data]
            for record in records:
                yield record
            if len(records) < self._page_size:
                return
            page += 1

    async def get_user_image(self, prop: str, id: str) -> bytes:
        try:
            response = await self._http.get(f"/api/v1/user/{prop}/{id}/image")
        except httpx.HTTPError as exc:
            raise HrApiError(status_code=None, message=str(exc), url=f"/api/v1/user/{prop}/{id}/image") from exc
        if response.status_code >= 400:
            raise HrApiError(status_code=response.status_code, message=response.text, url=str(response.url))
        return response.content

    async def get_group(self, group_id: str) -> HrGroup:
        data = await self._get(f"/api/v1/group/{group_id}")
        return HrGroup.model_validate(data)

    async def get_group_subhierarchy(self, group_id: str, maximum_depth: int | None = None) -> HrGroupWithReports:
        params = {"maximumDepth": maximum_depth} if maximum_depth is not None else None
        data = await self._get(f"/api/v1/group/{group_id}/subhierarchy", params=params)
        return HrGroupWithReports.model_validate(data)

    async def iter_groups(self, **filters: object) -> AsyncIterator[HrGroup]:
        page = 1
        while True:
            params = {**filters, "take": self._page_size, "page": page}
            data = await self._get("/api/v1/group", params=params)
            records = [HrGroup.model_validate(item) for item in data]
            for record in records:
                yield record
            if len(records) < self._page_size:
                return
            page += 1

    async def check_connection(self) -> HrHealthCheckResult:
        start = time.monotonic()
        try:
            await self._get("/api/v1/user", params={"take": 1})
        except HrApiError as exc:
            return HrHealthCheckResult(ok=False, latency_ms=(time.monotonic() - start) * 1000, error=exc.message)
        return HrHealthCheckResult(ok=True, latency_ms=(time.monotonic() - start) * 1000, error=None)
