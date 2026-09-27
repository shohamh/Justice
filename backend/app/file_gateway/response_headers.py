from __future__ import annotations

import re
from urllib.parse import quote

_RASTER_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_SAFE_TYPE = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")


def safe_filename(value: str) -> str:
    value = str(value).replace("\\", "/").split("/")[-1]
    value = "".join(ch for ch in value if ord(ch) >= 32 and ord(ch) != 127)
    value = value.strip(" .")[:180]
    return value or "download"


def build_file_headers(
    *, filename: str, content_type: str, size: int, inline: bool = False
) -> dict[str, str]:
    if not _SAFE_TYPE.fullmatch(content_type):
        raise ValueError("invalid content type")
    name = safe_filename(filename)
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace('"', "'")
    disposition = "inline" if inline and content_type.lower() in _RASTER_TYPES else "attachment"
    return {
        "Content-Type": content_type,
        "Content-Length": str(size),
        "Content-Disposition": f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
    }
