"""Interface used by trusted application storage callers."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO, Protocol


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int
    sha256: str
    encryption_algorithm: str | None
    encryption_key_id: str | None


class ObjectStorage(Protocol):
    def put_bytes(self, *, key: str, data: bytes, content_type: str, sha256: str) -> StoredObject: ...

    def open_read(self, *, key: str) -> tuple[BinaryIO, int]: ...

    def head(self, *, key: str) -> StoredObject | None: ...


class MaintenanceObjectStorage(ObjectStorage, Protocol):
    """Narrowly privileged adapter reserved for migration/reconciliation."""

    def delete(self, *, key: str) -> None: ...

    def iter_keys(self, *, prefix: str) -> Iterator[str]: ...
