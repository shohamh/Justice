from __future__ import annotations

from functools import lru_cache

from app.settings import get_storage_settings
from app.storage.protocol import ObjectStorage
from app.storage.s3 import S3ObjectStorage


@lru_cache(maxsize=1)
def _storage() -> ObjectStorage:
    return S3ObjectStorage(get_storage_settings())


def get_object_storage() -> ObjectStorage:
    """FastAPI dependency for the least-privilege runtime storage identity."""
    return _storage()
