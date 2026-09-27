"""Private S3-compatible adapter. Only maintenance callers can enumerate keys."""

from collections.abc import Iterator
from datetime import datetime
from hashlib import sha256 as hash_sha256
from typing import Any, BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.settings import Settings

from .keys import MANAGED_PREFIXES, validate_managed_key
from .protocol import StoredObject


def _checked_key(key: str) -> str:
    if not validate_managed_key(key):
        raise ValueError("Invalid managed object key")
    return key


class S3ObjectStorage:
    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self._bucket = settings.storage_bucket
        self._encryption_algorithm = settings.storage_sse_algorithm
        self._encryption_key_id = settings.storage_sse_key_id
        self._client = client or boto3.client(
            "s3",
            region_name=settings.storage_region,
            endpoint_url=settings.storage_endpoint_url or None,
            aws_access_key_id=(settings.storage_access_key_id.get_secret_value() or None),
            aws_secret_access_key=(settings.storage_secret_access_key.get_secret_value() or None),
            aws_session_token=(settings.storage_session_token.get_secret_value() or None),
            verify=settings.storage_ca_bundle_path or True,
            config=Config(s3={"addressing_style": "path" if settings.storage_path_style else "virtual"}),
        )

    def put_bytes(self, *, key: str, data: bytes, content_type: str, sha256: str) -> StoredObject:
        key = _checked_key(key)
        if sha256 != hash_sha256(data).hexdigest():
            raise ValueError("Object checksum does not match data")
        parameters: dict[str, Any] = {
            "Bucket": self._bucket, "Key": key, "Body": data,
            "ContentType": content_type, "Metadata": {"sha256": sha256},
        }
        if self._encryption_algorithm:
            parameters["ServerSideEncryption"] = self._encryption_algorithm
        if self._encryption_key_id:
            parameters["SSEKMSKeyId"] = self._encryption_key_id
        response = self._client.put_object(**parameters)
        return StoredObject(
            key, len(data), sha256,
            response.get("ServerSideEncryption", self._encryption_algorithm),
            response.get("SSEKMSKeyId", self._encryption_key_id),
        )

    def open_read(self, *, key: str) -> tuple[BinaryIO, int]:
        response = self._client.get_object(Bucket=self._bucket, Key=_checked_key(key))
        return response["Body"], response["ContentLength"]

    def head(self, *, key: str) -> StoredObject | None:
        key = _checked_key(key)
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        checksum = response.get("Metadata", {}).get("sha256")
        if not checksum:
            raise ValueError("Object checksum metadata is missing")
        return StoredObject(
            key, response["ContentLength"], checksum,
            response.get("ServerSideEncryption"), response.get("SSEKMSKeyId"),
        )

class S3MaintenanceObjectStorage(S3ObjectStorage):
    """Restricted maintenance identity for recovery enumeration and cleanup."""

    def delete(self, *, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=_checked_key(key))

    def iter_keys(self, *, prefix: str) -> Iterator[str]:
        for key, _ in self.iter_objects(prefix=prefix):
            yield key

    def iter_objects(self, *, prefix: str) -> Iterator[tuple[str, datetime | None]]:
        if prefix not in {f"{name}/" for name in MANAGED_PREFIXES}:
            raise ValueError("Invalid managed object prefix")
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                if not validate_managed_key(key) or not key.startswith(prefix):
                    raise ValueError("Invalid managed object key in listing")
                yield key, item.get("LastModified")
