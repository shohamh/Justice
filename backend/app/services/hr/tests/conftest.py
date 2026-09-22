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
