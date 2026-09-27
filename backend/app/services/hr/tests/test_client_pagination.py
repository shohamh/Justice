import httpx
import pytest
import respx

from app.services.hr.client import HrApiClient
from app.services.hr.errors import HrApiError
from app.services.hr.tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_iter_users_stops_on_short_page(hr_base_url, hr_api_key):
    page1 = load_fixture("users_page1_full.json")
    page2 = load_fixture("users_page2_short.json")
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/user", params={"take": "2", "page": "1"}).mock(
            return_value=httpx.Response(200, json=page1)
        )
        mock.get("/api/v1/user", params={"take": "2", "page": "2"}).mock(
            return_value=httpx.Response(200, json=page2)
        )
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key, page_size=2) as client:
            users = [u async for u in client.iter_users()]
        assert [u.personal_number for u in users] == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_iter_users_stops_on_empty_first_page(hr_base_url, hr_api_key):
    empty = load_fixture("users_page_empty.json")
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/user", params={"take": "2", "page": "1"}).mock(
            return_value=httpx.Response(200, json=empty)
        )
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key, page_size=2) as client:
            users = [u async for u in client.iter_users()]
        assert users == []


@pytest.mark.asyncio
async def test_iter_users_handles_exact_multiple_then_empty_page(hr_base_url, hr_api_key):
    page1 = load_fixture("users_page1_full.json")
    empty = load_fixture("users_page_empty.json")
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/user", params={"take": "2", "page": "1"}).mock(
            return_value=httpx.Response(200, json=page1)
        )
        mock.get("/api/v1/user", params={"take": "2", "page": "2"}).mock(
            return_value=httpx.Response(200, json=empty)
        )
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key, page_size=2) as client:
            users = [u async for u in client.iter_users()]
        assert [u.personal_number for u in users] == ["1", "2"]


@pytest.mark.asyncio
async def test_iter_users_passes_through_filters_including_date_range(hr_base_url, hr_api_key):
    empty = load_fixture("users_page_empty.json")
    with respx.mock(base_url=hr_base_url) as mock:
        route = mock.get(
            "/api/v1/user",
            params={
                "take": "2",
                "page": "1",
                "rank": "רב טוראי",
                "serviceStartDate_gte": "2024-01-01",
                "serviceStartDate_lte": "2024-12-31",
                "query": "doe",
                "sortBy": "fullName",
                "sortOrder": "asc",
                "allFields": "true",
            },
        ).mock(return_value=httpx.Response(200, json=empty))
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key, page_size=2) as client:
            _ = [
                u
                async for u in client.iter_users(
                    rank="רב טוראי",
                    serviceStartDate_gte="2024-01-01",
                    serviceStartDate_lte="2024-12-31",
                    query="doe",
                    sortBy="fullName",
                    sortOrder="asc",
                    allFields="true",
                )
            ]
        assert route.called


@pytest.mark.asyncio
async def test_iter_users_renames_image_filter_to_photo(hr_base_url, hr_api_key):
    empty = load_fixture("users_page_empty.json")
    with respx.mock(base_url=hr_base_url) as mock:
        route = mock.get(
            "/api/v1/user", params={"take": "2", "page": "1", "photo": "some-url"}
        ).mock(return_value=httpx.Response(200, json=empty))
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key, page_size=2) as client:
            _ = [u async for u in client.iter_users(image="some-url")]
        assert route.called


@pytest.mark.asyncio
async def test_iter_groups_stops_on_short_page(hr_base_url, hr_api_key):
    page1 = load_fixture("groups_page1_short.json")
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/group", params={"take": "2", "page": "1"}).mock(
            return_value=httpx.Response(200, json=page1)
        )
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key, page_size=2) as client:
            groups = [g async for g in client.iter_groups()]
        assert [g.id for g in groups] == ["g1"]


@pytest.mark.asyncio
async def test_iter_groups_advances_to_next_page_when_page_is_full(hr_base_url, hr_api_key):
    page1 = load_fixture("groups_page1_full.json")
    empty = load_fixture("users_page_empty.json")
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/group", params={"take": "2", "page": "1"}).mock(
            return_value=httpx.Response(200, json=page1)
        )
        mock.get("/api/v1/group", params={"take": "2", "page": "2"}).mock(
            return_value=httpx.Response(200, json=empty)
        )
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key, page_size=2) as client:
            groups = [g async for g in client.iter_groups()]
        assert [g.id for g in groups] == ["g1", "g2"]


@pytest.mark.asyncio
async def test_get_user_subhierarchy_parses_manages(hr_base_url, hr_api_key):
    fixture = load_fixture("user_subhierarchy.json")
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/user/personalNumber/1/subhierarchy", params={"maximumDepth": "3"}).mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            result = await client.get_user_subhierarchy("personalNumber", "1", maximum_depth=3)
        assert result.personal_number == "1"
        assert [r.personal_number for r in result.manages] == ["2", "3"]


@pytest.mark.asyncio
async def test_get_user_subhierarchy_empty_manages(hr_base_url, hr_api_key):
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/user/personalNumber/1/subhierarchy").mock(
            return_value=httpx.Response(200, json={"personalNumber": "1", "fullName": "Solo", "manages": []})
        )
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            result = await client.get_user_subhierarchy("personalNumber", "1")
        assert result.manages == []


@pytest.mark.asyncio
async def test_get_group_subhierarchy_parses_sub_groups(hr_base_url, hr_api_key):
    fixture = load_fixture("group_subhierarchy.json")
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/group/g1/subhierarchy", params={"maximumDepth": "2"}).mock(
            return_value=httpx.Response(200, json=fixture)
        )
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            result = await client.get_group_subhierarchy("g1", maximum_depth=2)
        assert result.id == "g1"
        assert [g.id for g in result.sub_groups] == ["g2"]


@pytest.mark.asyncio
async def test_get_group_subhierarchy_raises_on_error(hr_base_url, hr_api_key):
    with respx.mock(base_url=hr_base_url) as mock:
        mock.get("/api/v1/group/missing/subhierarchy").mock(return_value=httpx.Response(404, text="not found"))
        async with HrApiClient(base_url=hr_base_url, api_key=hr_api_key) as client:
            with pytest.raises(HrApiError):
                await client.get_group_subhierarchy("missing")
