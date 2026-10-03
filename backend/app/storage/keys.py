"""Opaque, fixed-shape keys for managed objects."""

import re
from typing import Literal, get_args
from uuid import UUID

FileClass = Literal[
    "soldier_exemption", "exemption_request", "gimelim", "bug_report_screenshot",
    "bug_report_comment", "import_workbook", "bug_report_json_mirror",
]
MANAGED_PREFIXES: frozenset[str] = frozenset(get_args(FileClass))
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z",
    re.ASCII,
)


def make_object_key(file_class: FileClass, object_id: UUID) -> str:
    if file_class not in MANAGED_PREFIXES or not isinstance(object_id, UUID):
        raise ValueError("Invalid managed object identity")
    return f"{file_class}/{object_id}"


def validate_managed_key(key: str) -> bool:
    if not isinstance(key, str) or key.count("/") != 1:
        return False
    prefix, object_id = key.split("/", 1)
    return prefix in MANAGED_PREFIXES and _UUID_PATTERN.fullmatch(object_id) is not None
