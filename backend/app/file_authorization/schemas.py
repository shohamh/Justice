from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.storage.keys import validate_managed_key


class RequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExemptionRequestFileRequest(RequestBase):
    kind: Literal["exemption_request"]
    request_id: uuid.UUID
    file_id: uuid.UUID


class SoldierExemptionFileRequest(RequestBase):
    kind: Literal["soldier_exemption"]
    exemption_id: uuid.UUID
    file_id: uuid.UUID


class GimelimAttachmentRequest(RequestBase):
    kind: Literal["gimelim"]
    dismissal_id: uuid.UUID
    attachment_id: uuid.UUID


class BugReportScreenshotRequest(RequestBase):
    kind: Literal["bug_report_screenshot"]
    report_id: uuid.UUID


class BugReportCommentAttachmentRequest(RequestBase):
    kind: Literal["bug_report_comment"]
    report_id: uuid.UUID
    comment_id: uuid.UUID
    attachment_id: uuid.UUID


class ImportWorkbookRequest(RequestBase):
    kind: Literal["import_workbook"]
    session_id: uuid.UUID


FileAuthorizationRequest = Annotated[
    ExemptionRequestFileRequest
    | SoldierExemptionFileRequest
    | GimelimAttachmentRequest
    | BugReportScreenshotRequest
    | BugReportCommentAttachmentRequest
    | ImportWorkbookRequest,
    Field(discriminator="kind"),
]


class FileAuthorizationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    object_key: str
    sha256: str
    size: int = Field(ge=0)
    content_type: str = Field(min_length=1, max_length=127)
    filename: str = Field(min_length=1, max_length=255)

    @field_validator("object_key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not validate_managed_key(value) or value.startswith(("bug_report_json_mirror/",)):
            raise ValueError("invalid managed object key")
        return value

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value, flags=re.ASCII):
            raise ValueError("invalid checksum")
        return value

    @field_validator("content_type")
    @classmethod
    def safe_content_type(cls, value: str) -> str:
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("invalid content type")
        return value
