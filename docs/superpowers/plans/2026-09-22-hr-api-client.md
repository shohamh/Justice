# HR API Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure, fully-tested async HTTP client (`HrApiClient`) for the external HR (משא"ן) API, with typed request/response models, auto-pagination, off-by-default configuration, and support for an internal CA bundle — no DB writes, no field mapping, no routes/UI.

**Architecture:** A new `backend/app/services/hr/` subpackage holds raw Pydantic response models (`schemas.py`), a typed error hierarchy (`errors.py`), and the client itself (`client.py`), built on `httpx.AsyncClient`. Settings gain HR-specific fields following the existing "empty = disabled" idiom (`telegram_bot_token`, `smtp_host`). Tests use `respx` to mock the httpx transport against JSON fixtures — zero network I/O, zero live HR server dependency.

**Tech Stack:** Python 3.12, FastAPI/pydantic v2, httpx (async), respx (test mocking), pytest/pytest-asyncio (already configured with `asyncio_mode = "auto"`).

**Spec:** [docs/superpowers/specs/2026-09-22-hr-api-client-design.md](../specs/2026-09-22-hr-api-client-design.md)

## Global Constraints

- Client and schemas live under `backend/app/services/hr/` — models named `Hr*` (e.g. `HrUser`, not `User`) to avoid collisions with Justice's own `Soldier`/`HierarchyNode` models later.
- No DB imports anywhere in `app/services/hr/client.py` or `schemas.py` (this subsystem is DB-free, same discipline as `app/algorithm/`).
- No retry/backoff logic in the client — it raises `HrApiError` on any failure; retry policy is deferred to the sync engine (a later subsystem).
- Auth header on every request: `X-API-KEY: <settings.hr_api_key>`.
- Integration is disabled unless both `HR_API_BASE_URL` and `HR_API_KEY` are set (`settings.hr_sync_enabled`); the client itself always raises `HrClientNotConfigured` if constructed with either empty — it does not silently no-op.
- Pagination: `take` + `page` (1-based), keep requesting until a page returns fewer than `take` records (covers empty/short/exact-multiple cases uniformly).
- Tests never touch a real network — all HTTP is mocked via `respx` against fixture JSON files.
- 100% test coverage of `client.py`, `schemas.py`, `errors.py`.

---

## Task 1: Dependencies, settings, and env/docker scaffolding

**Files:**
- Modify: `backend/pyproject.toml` (add `httpx` to `dependencies`, add `respx` to `dev`)
- Modify: `backend/app/settings.py` (add HR fields + `hr_sync_enabled` property)
- Modify: `.env.example` (document new vars)
- Modify: `.env.defaults` (add `HR_API_PAGE_SIZE` default; leave key/url/cert blank — those are secrets/deploy-specific)
- Modify: `docker-compose.yml` (mount `./backend/certs:/app/certs:ro` on the `backend` service)
- Create: `backend/certs/.gitkeep`
- Modify: `.gitignore` (ignore `backend/certs/*` except `.gitkeep`)

**Interfaces:**
- Produces: `Settings.hr_api_base_url: str`, `Settings.hr_api_key: str`, `Settings.hr_api_ca_bundle_path: str`, `Settings.hr_api_page_size: int`, `Settings.hr_sync_enabled: bool` (property) — all consumed by Task 3 (client construction) and later subsystems.

This task has no test-first cycle of its own (it's config/scaffolding), but Step 5 verifies the settings load correctly.

- [ ] **Step 1: Add `httpx` and `respx` to `pyproject.toml`**

In `backend/pyproject.toml`, move `httpx` from the `dev` optional-dependencies list into the main `dependencies` list (it's now runtime code, not just test tooling), and add `respx` to `dev`:

```toml
dependencies = [
  "fastapi>=0.110",
  "ortools>=9.10",
  "uvicorn[standard]>=0.27",
  "sqlalchemy>=2.0.27",
  "alembic>=1.13",
  "psycopg[binary]>=3.1",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "argon2-cffi>=23.1",
  "python-jose[cryptography]>=3.3",
  "slowapi>=0.1.9",
  "python-multipart>=0.0.9",
  "python-telegram-bot>=21.0",
  "openpyxl>=3.1",
  "holidays>=0.46",
  "jinja2>=3.1",
  "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.23",
  "pytest-xdist>=3.5",
  "httpx>=0.27",
  "respx>=0.21",
  "testcontainers[postgres]>=4.0",
  "hypothesis>=6.99",
  "ruff>=0.3",
  "mypy>=1.9",
  "types-python-jose>=3.3",
]
```

(`httpx` stays listed under `dev` too since it's still a direct test-time import; duplication across the two lists already exists implicitly via transitive deps and is harmless.)

- [ ] **Step 2: Install the new dependencies**

Run (from `backend/`, with `.venv` activated):
```bash
pip install -e ".[dev]"
```
Expected: installs successfully, `respx` importable.

- [ ] **Step 3: Add HR settings fields**

In `backend/app/settings.py`, add after the `smtp_*` fields:

```python
    hr_api_base_url: str = Field(default="", alias="HR_API_BASE_URL")
    hr_api_key: str = Field(default="", alias="HR_API_KEY")
    hr_api_ca_bundle_path: str = Field(default="", alias="HR_API_CA_BUNDLE_PATH")
    hr_api_page_size: int = Field(default=200, alias="HR_API_PAGE_SIZE")
```

And add this property next to `cors_origins`:

```python
    @property
    def hr_sync_enabled(self) -> bool:
        return bool(self.hr_api_base_url and self.hr_api_key)
```

- [ ] **Step 4: Write a settings test**

Create/extend the existing settings test location — check for `backend/app/tests/test_settings.py` or similar first; if none exists, create `backend/app/tests/test_settings.py`:

```python
import os

from app.settings import Settings


def test_hr_sync_enabled_false_when_unset(monkeypatch):
    monkeypatch.delenv("HR_API_BASE_URL", raising=False)
    monkeypatch.delenv("HR_API_KEY", raising=False)
    s = Settings(_env_file=None, DATABASE_URL="x", DB_ADMIN_URL="x", JWT_SECRET="x" * 32)
    assert s.hr_sync_enabled is False


def test_hr_sync_enabled_true_when_both_set(monkeypatch):
    s = Settings(
        _env_file=None,
        DATABASE_URL="x",
        DB_ADMIN_URL="x",
        JWT_SECRET="x" * 32,
        HR_API_BASE_URL="https://hr.example.internal",
        HR_API_KEY="secret",
    )
    assert s.hr_sync_enabled is True


def test_hr_sync_enabled_false_when_only_one_set(monkeypatch):
    s = Settings(
        _env_file=None,
        DATABASE_URL="x",
        DB_ADMIN_URL="x",
        JWT_SECRET="x" * 32,
        HR_API_BASE_URL="https://hr.example.internal",
    )
    assert s.hr_sync_enabled is False
```

If `backend/app/tests/test_settings.py` already exists, add these three test functions to it instead of creating a new file (check `Settings` import path and any existing construction helper first, and reuse it).

- [ ] **Step 5: Run the settings tests**

Run: `pytest backend/app/tests/test_settings.py -v -k hr_sync_enabled`
Expected: 3 passed.

- [ ] **Step 6: Document new env vars**

In `.env.example`, add after the `TELEGRAM_BOT_TOKEN` block:

```
# HR (משא"ן) integration — leave both blank to disable
HR_API_BASE_URL=
HR_API_KEY=
# Path to a CA bundle (.pem) for verifying an internally-signed HR server,
# e.g. mounted via the backend/certs/ volume in docker-compose.yml.
# Leave blank to use the system trust store.
# HR_API_CA_BUNDLE_PATH=/app/certs/internal-ca.pem
```

In `.env.defaults`, add:

```
HR_API_PAGE_SIZE=200
```

- [ ] **Step 7: Add the certs mount for offline/internal-CA deployments**

Create `backend/certs/.gitkeep` (empty file).

In `.gitignore`, add:
```
backend/certs/*
!backend/certs/.gitkeep
```

In `docker-compose.yml`, under the `backend` service's `volumes:` list, add:
```yaml
      - ./backend/certs:/app/certs:ro
```

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/app/settings.py backend/app/tests/test_settings.py .env.example .env.defaults .gitignore docker-compose.yml backend/certs/.gitkeep
git commit -m "feat: add HR integration settings, deps, and CA bundle mount"
```

---

## Task 2: Raw HR schemas (`HrUser`, `HrGroup`, and variants)

**Files:**
- Create: `backend/app/services/hr/__init__.py` (empty)
- Create: `backend/app/services/hr/schemas.py`
- Create: `backend/app/services/hr/tests/__init__.py` (empty)
- Test: `backend/app/services/hr/tests/test_schemas.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces: `HrUser`, `HrUserWithReports`, `HrGroup`, `HrGroupWithReports`, `HrHealthCheckResult` Pydantic models — consumed by Task 3 (`client.py`).

- [ ] **Step 1: Write the failing schema tests**

Create `backend/app/services/hr/tests/test_schemas.py`:

```python
from app.services.hr.schemas import (
    HrGroup,
    HrGroupWithReports,
    HrHealthCheckResult,
    HrUser,
    HrUserWithReports,
)


def test_hr_user_parses_full_payload():
    payload = {
        "username": "jdoe",
        "firstName": "John",
        "lastName": "Doe",
        "fullName": "John Doe",
        "imageUrl": "https://hr.example/img/1",
        "mail": "jdoe@example.mil",
        "status": "active",
        "nationalIdentifier": "123456789",
        "personalNumber": "7654321",
        "rank": "רב טוראי",
        "gender": "male",
        "servicType": "chova",
        "job": "operator",
        "profession": "logistics",
        "professionId": "42",
        "serviceStartDate": "2024-01-01",
        "serviceEndDate": None,
        "baseEntryDate": "2024-01-05",
        "t_personID": "abc-123",
        "address": "Tel Aviv",
        "jobStartDate": "2024-02-01",
        "endHovaDate": "2026-01-01",
        "dateOfBirth": "2002-03-04",
        "phone": "050-1234567",
        "voip": "1234",
        "manager": "jsmith",
        "managerName": "Jane Smith",
        "managerUserName": "jsmith",
        "managerPersonalNumber": "1112223",
        "organization": "Unit 8200",
        "hulia": "A",
        "huliaId": "h1",
        "huliaManager": "jsmith",
        "team": "Team 1",
        "teamId": "t1",
        "teamManager": "jsmith",
        "mador": "Mador 1",
        "madorId": "m1",
        "madorManager": "jsmith",
        "branch": "Branch 1",
        "branchId": "b1",
        "branchManager": "jsmith",
        "shetach": "Shetach 1",
        "shetachId": "s1",
        "shetachManager": "jsmith",
        "department": "Dept 1",
        "departmentId": "d1",
        "departmentManager": "jsmith",
        "palga": "Palga 1",
        "palgaManager": "jsmith",
        "unit": "Unit 1",
        "unitId": "u1",
        "unitManager": "jsmith",
        "maritalStatus": "single",
        "minuy": "regular",
        "minuyRank": "רב טוראי",
        "isRashatz": False,
        "isRamad": False,
        "isRaan": False,
        "isMafmar": False,
        "isMefakedYechida": False,
    }
    user = HrUser.model_validate(payload)
    assert user.personal_number == "7654321"
    assert user.full_name == "John Doe"
    assert user.image_url == "https://hr.example/img/1"
    assert user.service_start_date == "2024-01-01"
    assert user.is_rashatz is False


def test_hr_user_tolerates_missing_optional_fields():
    user = HrUser.model_validate({"personalNumber": "1", "fullName": "Only Required"})
    assert user.personal_number == "1"
    assert user.mail is None
    assert user.rank is None


def test_hr_user_with_reports_parses_manages_list():
    payload = {
        "personalNumber": "1",
        "fullName": "Manager",
        "manages": [
            {"personalNumber": "2", "fullName": "Report One"},
            {"personalNumber": "3", "fullName": "Report Two"},
        ],
    }
    result = HrUserWithReports.model_validate(payload)
    assert len(result.manages) == 2
    assert result.manages[0].personal_number == "2"


def test_hr_user_with_reports_empty_manages():
    result = HrUserWithReports.model_validate({"personalNumber": "1", "fullName": "Solo", "manages": []})
    assert result.manages == []


def test_hr_group_parses_full_payload():
    payload = {
        "id": "g1",
        "name": "Group One",
        "kind": "unit",
        "unit": "Unit 1",
        "parentKind": "branch",
        "parentId": "b1",
        "parentName": "Branch 1",
    }
    group = HrGroup.model_validate(payload)
    assert group.id == "g1"
    assert group.parent_id == "b1"


def test_hr_group_with_reports_parses_subhierarchy():
    payload = {
        "id": "g1",
        "name": "Group One",
        "kind": "unit",
        "unit": "Unit 1",
        "parentKind": None,
        "parentId": None,
        "parentName": None,
        "subGroups": [{"id": "g2", "name": "Group Two", "kind": "team", "unit": "Unit 1",
                       "parentKind": "unit", "parentId": "g1", "parentName": "Group One"}],
    }
    result = HrGroupWithReports.model_validate(payload)
    assert len(result.sub_groups) == 1
    assert result.sub_groups[0].id == "g2"


def test_hr_health_check_result():
    ok = HrHealthCheckResult(ok=True, latency_ms=12.5, error=None)
    assert ok.ok is True
    failed = HrHealthCheckResult(ok=False, latency_ms=0.0, error="timeout")
    assert failed.error == "timeout"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/hr/tests/test_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.hr'` (or similar import error).

- [ ] **Step 3: Create the package and schemas**

Create `backend/app/services/hr/__init__.py` (empty file).

Create `backend/app/services/hr/tests/__init__.py` (empty file).

Create `backend/app/services/hr/schemas.py`:

```python
from pydantic import BaseModel, ConfigDict, Field


class HrUser(BaseModel):
    """Raw HR API user record. Field names mirror the HR API's JSON keys via
    aliases; snake_case attribute names are Justice-side convenience only —
    no value mapping happens here (see subsystem 2 for that)."""

    model_config = ConfigDict(populate_by_name=True)

    username: str | None = None
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    full_name: str = Field(alias="fullName")
    image_url: str | None = Field(default=None, alias="imageUrl")
    mail: str | None = None
    status: str | None = None
    national_identifier: str | None = Field(default=None, alias="nationalIdentifier")
    personal_number: str = Field(alias="personalNumber")
    rank: str | None = None
    gender: str | None = None
    serv_type: str | None = Field(default=None, alias="servicType")
    job: str | None = None
    profession: str | None = None
    profession_id: str | None = Field(default=None, alias="professionId")
    service_start_date: str | None = Field(default=None, alias="serviceStartDate")
    service_end_date: str | None = Field(default=None, alias="serviceEndDate")
    base_entry_date: str | None = Field(default=None, alias="baseEntryDate")
    t_person_id: str | None = Field(default=None, alias="t_personID")
    address: str | None = None
    job_start_date: str | None = Field(default=None, alias="jobStartDate")
    end_hova_date: str | None = Field(default=None, alias="endHovaDate")
    date_of_birth: str | None = Field(default=None, alias="dateOfBirth")
    phone: str | None = None
    voip: str | None = None
    manager: str | None = None
    manager_name: str | None = Field(default=None, alias="managerName")
    manager_user_name: str | None = Field(default=None, alias="managerUserName")
    manager_personal_number: str | None = Field(default=None, alias="managerPersonalNumber")
    organization: str | None = None
    hulia: str | None = None
    hulia_id: str | None = Field(default=None, alias="huliaId")
    hulia_manager: str | None = Field(default=None, alias="huliaManager")
    team: str | None = None
    team_id: str | None = Field(default=None, alias="teamId")
    team_manager: str | None = Field(default=None, alias="teamManager")
    mador: str | None = None
    mador_id: str | None = Field(default=None, alias="madorId")
    mador_manager: str | None = Field(default=None, alias="madorManager")
    branch: str | None = None
    branch_id: str | None = Field(default=None, alias="branchId")
    branch_manager: str | None = Field(default=None, alias="branchManager")
    shetach: str | None = None
    shetach_id: str | None = Field(default=None, alias="shetachId")
    shetach_manager: str | None = Field(default=None, alias="shetachManager")
    department: str | None = None
    department_id: str | None = Field(default=None, alias="departmentId")
    department_manager: str | None = Field(default=None, alias="departmentManager")
    palga: str | None = None
    palga_manager: str | None = Field(default=None, alias="palgaManager")
    unit: str | None = None
    unit_id: str | None = Field(default=None, alias="unitId")
    unit_manager: str | None = Field(default=None, alias="unitManager")
    marital_status: str | None = Field(default=None, alias="maritalStatus")
    minuy: str | None = None
    minuy_rank: str | None = Field(default=None, alias="minuyRank")
    is_rashatz: bool | None = Field(default=None, alias="isRashatz")
    is_ramad: bool | None = Field(default=None, alias="isRamad")
    is_raan: bool | None = Field(default=None, alias="isRaan")
    is_mafmar: bool | None = Field(default=None, alias="isMafmar")
    is_mefaked_yechida: bool | None = Field(default=None, alias="isMefakedYechida")


class HrUserWithReports(HrUser):
    """HR user extended with direct + indirect reports, as returned by the
    /subhierarchy endpoint."""

    manages: list[HrUser] = Field(default_factory=list)


class HrGroup(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    kind: str | None = None
    unit: str | None = None
    parent_kind: str | None = Field(default=None, alias="parentKind")
    parent_id: str | None = Field(default=None, alias="parentId")
    parent_name: str | None = Field(default=None, alias="parentName")


class HrGroupWithReports(HrGroup):
    """HR group extended with its subhierarchy. The HR API spec does not
    detail the exact nesting shape beyond "subhierarchy"; kept intentionally
    shallow (one level of sub_groups) rather than guessing a deep recursive
    shape — revisit if real fixture data shows otherwise."""

    sub_groups: list[HrGroup] = Field(default_factory=list, alias="subGroups")


class HrHealthCheckResult(BaseModel):
    ok: bool
    latency_ms: float
    error: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/app/services/hr/tests/test_schemas.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hr/__init__.py backend/app/services/hr/schemas.py backend/app/services/hr/tests/__init__.py backend/app/services/hr/tests/test_schemas.py
git commit -m "feat: add raw HR API Pydantic schemas"
```

---

## Task 3: Error hierarchy

**Files:**
- Create: `backend/app/services/hr/errors.py`
- Test: `backend/app/services/hr/tests/test_errors.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `HrClientNotConfigured(Exception)`, `HrApiError(Exception)` with attributes `status_code: int | None`, `message: str`, `url: str | None` — consumed by Task 4 (`client.py`).

- [ ] **Step 1: Write the failing test**

Create `backend/app/services/hr/tests/test_errors.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/hr/tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.hr.errors'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/hr/errors.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/hr/tests/test_errors.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hr/errors.py backend/app/services/hr/tests/test_errors.py
git commit -m "feat: add HR API error hierarchy"
```

---

## Task 4: `HrApiClient` — construction, single-record fetches, and CA bundle handling

**Files:**
- Create: `backend/app/services/hr/client.py`
- Create: `backend/app/services/hr/tests/conftest.py`
- Test: `backend/app/services/hr/tests/test_client.py`

**Interfaces:**
- Consumes: `HrUser`, `HrUserWithReports`, `HrGroup`, `HrGroupWithReports`, `HrHealthCheckResult` from `app.services.hr.schemas` (Task 2); `HrClientNotConfigured`, `HrApiError` from `app.services.hr.errors` (Task 3).
- Produces: `HrApiClient(base_url: str, api_key: str, *, ca_bundle_path: str = "", page_size: int = 200, timeout: float = 10.0)` with methods `get_user`, `iter_users`, `get_user_subhierarchy`, `get_user_image`, `iter_groups`, `get_group`, `get_group_subhierarchy`, `check_connection`, `aclose`, `__aenter__`, `__aexit__` — consumed by later subsystems (2–6) and by this task's own tests.

This task covers construction, `get_user`, `get_user_image`, `get_group`, error handling, and CA bundle config. Task 5 covers pagination (`iter_users`/`iter_groups`) and subhierarchy parsing, since those need more fixture setup.

- [ ] **Step 1: Create fixture files and shared test config**

Create `backend/app/services/hr/tests/fixtures/user_single.json`:

```json
{
  "personalNumber": "7654321",
  "fullName": "John Doe",
  "mail": "jdoe@example.mil",
  "rank": "רב טוראי",
  "gender": "male"
}
```

Create `backend/app/services/hr/tests/fixtures/group_single.json`:

```json
{
  "id": "g1",
  "name": "Group One",
  "kind": "unit",
  "unit": "Unit 1",
  "parentKind": "branch",
  "parentId": "b1",
  "parentName": "Branch 1"
}
```

Create `backend/app/services/hr/tests/conftest.py`:

```python
import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict | list:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def hr_base_url() -> str:
    return "https://hr.example.internal"


@pytest.fixture
def hr_api_key() -> str:
    return "test-api-key"
```

- [ ] **Step 2: Write the failing tests**

Create `backend/app/services/hr/tests/test_client.py`:

```python
import httpx
import pytest
import respx

from app.services.hr.client import HrApiClient
from app.services.hr.errors import HrApiError, HrClientNotConfigured
from app.services.hr.tests.conftest import load_fixture


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
    ca_file = tmp_path / "internal-ca.pem"
    ca_file.write_text("fake cert contents")
    client = HrApiClient(base_url=hr_base_url, api_key=hr_api_key, ca_bundle_path=str(ca_file))
    assert client._verify == str(ca_file)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest backend/app/services/hr/tests/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.hr.client'`.

- [ ] **Step 4: Write the implementation**

Create `backend/app/services/hr/client.py`:

```python
import time

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
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-KEY": api_key},
            verify=self._verify,
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

    async def check_connection(self) -> HrHealthCheckResult:
        start = time.monotonic()
        try:
            await self._get("/api/v1/user", params={"take": 1})
        except HrApiError as exc:
            return HrHealthCheckResult(ok=False, latency_ms=(time.monotonic() - start) * 1000, error=exc.message)
        return HrHealthCheckResult(ok=True, latency_ms=(time.monotonic() - start) * 1000, error=None)
```

(`iter_users`/`iter_groups` are intentionally omitted here — added in Task 5.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/app/services/hr/tests/test_client.py -v`
Expected: 12 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/hr/client.py backend/app/services/hr/tests/conftest.py backend/app/services/hr/tests/test_client.py backend/app/services/hr/tests/fixtures/user_single.json backend/app/services/hr/tests/fixtures/group_single.json
git commit -m "feat: add HrApiClient single-record fetches, image, and health check"
```

---

## Task 5: Pagination (`iter_users`, `iter_groups`), filter passthrough, and subhierarchy `manages`

**Files:**
- Modify: `backend/app/services/hr/client.py` (add `iter_users`, `iter_groups`)
- Test: `backend/app/services/hr/tests/test_client_pagination.py`
- Create fixtures: `backend/app/services/hr/tests/fixtures/users_page1_full.json`, `users_page2_short.json`, `users_page_empty.json`, `groups_page1_short.json`, `user_subhierarchy.json`

**Interfaces:**
- Consumes: `HrApiClient` from Task 4 (extends it in place), `HrUser`/`HrGroup`/`HrUserWithReports` from Task 2.
- Produces: `HrApiClient.iter_users(**filters) -> AsyncIterator[HrUser]`, `HrApiClient.iter_groups(**filters) -> AsyncIterator[HrGroup]` — consumed by the person-sync engine (subsystem 4) and hierarchy sync (subsystem 3).

- [ ] **Step 1: Create pagination fixtures**

Create `backend/app/services/hr/tests/fixtures/users_page1_full.json` (exactly 2 records, used with a client `page_size=2` in tests so "full page" is easy to construct):

```json
[
  {"personalNumber": "1", "fullName": "User One"},
  {"personalNumber": "2", "fullName": "User Two"}
]
```

Create `backend/app/services/hr/tests/fixtures/users_page2_short.json`:

```json
[
  {"personalNumber": "3", "fullName": "User Three"}
]
```

Create `backend/app/services/hr/tests/fixtures/users_page_empty.json`:

```json
[]
```

Create `backend/app/services/hr/tests/fixtures/groups_page1_short.json`:

```json
[
  {"id": "g1", "name": "Group One", "kind": "unit", "unit": "Unit 1", "parentKind": null, "parentId": null, "parentName": null}
]
```

Create `backend/app/services/hr/tests/fixtures/user_subhierarchy.json`:

```json
{
  "personalNumber": "1",
  "fullName": "Manager One",
  "manages": [
    {"personalNumber": "2", "fullName": "Report One"},
    {"personalNumber": "3", "fullName": "Report Two"}
  ]
}
```

Create `backend/app/services/hr/tests/fixtures/group_subhierarchy.json`:

```json
{
  "id": "g1",
  "name": "Group One",
  "kind": "unit",
  "unit": "Unit 1",
  "parentKind": null,
  "parentId": null,
  "parentName": null,
  "subGroups": [
    {"id": "g2", "name": "Group Two", "kind": "team", "unit": "Unit 1", "parentKind": "unit", "parentId": "g1", "parentName": "Group One"}
  ]
}
```

- [ ] **Step 2: Write the failing pagination tests**

Create `backend/app/services/hr/tests/test_client_pagination.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest backend/app/services/hr/tests/test_client_pagination.py -v`
Expected: FAIL — `AttributeError: 'HrApiClient' object has no attribute 'iter_users'`.

- [ ] **Step 4: Implement `iter_users` and `iter_groups`**

In `backend/app/services/hr/client.py`, add `from collections.abc import AsyncIterator` to the imports, and add these two methods to `HrApiClient` (after `get_user_subhierarchy` and after `get_group_subhierarchy` respectively — exact placement doesn't matter, keep them near their related single-record methods):

```python
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
```

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/app/services/hr/tests/test_client_pagination.py -v`
Expected: 10 passed.

- [ ] **Step 6: Run the full HR test suite together**

Run: `pytest backend/app/services/hr/tests/ -v`
Expected: all tests across `test_schemas.py`, `test_errors.py`, `test_client.py`, `test_client_pagination.py` pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/hr/client.py backend/app/services/hr/tests/test_client_pagination.py backend/app/services/hr/tests/fixtures/users_page1_full.json backend/app/services/hr/tests/fixtures/users_page2_short.json backend/app/services/hr/tests/fixtures/users_page_empty.json backend/app/services/hr/tests/fixtures/groups_page1_short.json backend/app/services/hr/tests/fixtures/user_subhierarchy.json backend/app/services/hr/tests/fixtures/group_subhierarchy.json
git commit -m "feat: add HrApiClient pagination for users and groups"
```

---

## Task 6: Coverage check and pytest marker registration

**Files:**
- Modify: `backend/pyproject.toml` (`[tool.pytest.ini_options]` — decide marker bucket for `app/services/hr`)

**Interfaces:**
- Consumes: nothing new — this task verifies Tasks 1–5's output meets the spec's coverage bar and fits existing test tooling.

- [ ] **Step 1: Check which marker bucket `app/services/hr` tests fall into**

Read `backend/tests/conftest.py` (or wherever the filename-based area-marker hook lives — confirm exact path first with `grep -rn "def pytest_collection_modifyitems" backend/`) to see how markers are assigned by file path/name. HR sync doesn't cleanly fit `soldiers` (profile/listing/import) or any existing bucket — decide between reusing `misc` (health check, audit log, settings loader — closest existing fit) or adding a new `hr` marker. Prefer reusing `misc` unless the hook's matching logic makes that awkward (e.g. if it matches on a literal path segment already reserved for something else).

If adding a new marker, add to `backend/pyproject.toml`:
```toml
  "hr: external HR (משא\"ן) integration — client, sync, mapping, activation",
```
and update the hook in the conftest to route `app/services/hr/**` to it.

If reusing `misc`, confirm the hook already matches `app/services/hr/tests/*` into `misc` by its existing rule (likely a catch-all "anything not matched above") — no code change needed, just confirm via `pytest app/services/hr/tests/ -v -m misc` (or `-m hr` if you added the new marker) returning the full HR test count.

- [ ] **Step 2: Run the HR suite via its marker to confirm routing**

Run: `pytest -m misc -v` (or `pytest -m hr -v` if a new marker was added), from `backend/`.
Expected: includes all `app/services/hr/tests/*` tests among the results (exact count depends on what else shares the marker).

- [ ] **Step 3: Run coverage for the HR package**

Run (from `backend/`):
```bash
pytest app/services/hr/tests/ --cov=app.services.hr --cov-report=term-missing -v
```
Expected: 100% coverage (or a report showing exactly which lines are missed) for `client.py`, `schemas.py`, `errors.py`. If any lines are missed, add a targeted test in the relevant `test_*.py` file for that branch (e.g. an uncovered `except` clause) and re-run until 100%.

- [ ] **Step 4: Run the full fast backend suite to confirm no regressions**

Run (from `backend/`): `pytest -q`
Expected: all pass, no new failures introduced.

- [ ] **Step 5: Commit (if the marker file changed)**

```bash
git add backend/pyproject.toml backend/tests/conftest.py
git commit -m "test: route app/services/hr tests to a pytest marker"
```

(Skip this commit if Step 1 concluded no code change was needed.)

---

## Self-Review Notes

- **Spec coverage:** client interface (all 8 methods + `check_connection`), auto-pagination with `take`/`page`, off-by-default settings (`hr_sync_enabled`), CA bundle support + Docker mount, `respx`-mocked fixture tests, `Hr*`-prefixed schema names, `image`→`photo` filter rename, error hierarchy with no retries, `.env.example`/`.env.defaults` documentation — all covered across Tasks 1–6.
- **Deferred by design (per spec's Non-goals):** field mapping to Justice vocab, DB writes, routes, frontend UI — correctly excluded from this plan.
- **Type consistency:** `HrApiClient.__init__` signature (`base_url, api_key, *, ca_bundle_path, page_size, timeout`) is consistent across Task 4's construction and Task 5's `page_size` usage in pagination tests. `HrUserWithReports.manages: list[HrUser]` and `HrGroupWithReports.sub_groups: list[HrGroup]` (Task 2) match what Task 4/5's `get_user_subhierarchy`/`get_group_subhierarchy` return and what Task 5's tests assert on (`result.manages`, `result.sub_groups`).
- **Gap found and fixed:** `get_group_subhierarchy` had no dedicated test in the original draft. Fixed by adding `test_get_group_subhierarchy_parses_sub_groups` and `test_get_group_subhierarchy_raises_on_error` to Task 5, with a matching `group_subhierarchy.json` fixture, so it gets the same happy-path + error-path coverage as `get_user_subhierarchy`.
