from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.error_logging import log_frontend_error

router = APIRouter()


class ClientErrorReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_id: str = Field(default="unknown", max_length=100)
    kind: str = Field(default="unknown", max_length=40)
    message: str = Field(default="", max_length=4000)
    stack: str | None = Field(default=None, max_length=8000)
    url: str | None = Field(default=None, max_length=2000)
    method: str | None = Field(default=None, max_length=20)
    status: int | None = None
    request_data: Any = None
    response_data: Any = None
    browser_url: str | None = Field(default=None, max_length=2000)
    user_agent: str | None = Field(default=None, max_length=1000)
    response_headers: Any = None
    filename: str | None = Field(default=None, max_length=2000)
    line: int | None = None
    column: int | None = None


@router.post("/client-errors", status_code=204)
async def report_client_error(report: ClientErrorReport) -> None:
    log_frontend_error(report.model_dump())
