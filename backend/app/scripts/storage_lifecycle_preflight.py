"""Exercise object persistence and outage behavior in the isolated Task 8 stack."""

from __future__ import annotations

import hashlib
import socket
import sys

from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
    SSLError,
)

from app.settings import get_storage_settings
from app.storage.s3 import S3MaintenanceObjectStorage, S3ObjectStorage

_KEY = "exemption_request/00000000-0000-4000-8000-000000000008"
_PAYLOAD = b"task8-seaweedfs-restart-and-outage-probe-v1\n"
_SHA256 = hashlib.sha256(_PAYLOAD).hexdigest()


def _storage() -> S3ObjectStorage:
    return S3ObjectStorage(get_storage_settings())


def _verify() -> None:
    body, length = _storage().open_read(key=_KEY)
    try:
        payload = body.read()
    finally:
        body.close()
    if length != len(_PAYLOAD) or payload != _PAYLOAD:
        raise RuntimeError("Lifecycle object did not survive the SeaweedFS restart")
    print("Task 8 storage lifecycle: object bytes survived SeaweedFS restart")


def main() -> int:
    operation = sys.argv[1] if len(sys.argv) == 2 else ""
    storage = _storage()
    if operation == "write":
        storage.put_bytes(
            key=_KEY,
            data=_PAYLOAD,
            content_type="application/octet-stream",
            sha256=_SHA256,
        )
        print("Task 8 storage lifecycle: probe object written")
        return 0
    if operation == "verify":
        _verify()
        return 0
    if operation == "outage":
        try:
            storage.open_read(key=_KEY)
        except (ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError):
            print("Task 8 storage lifecycle: SeaweedFS outage surfaced as a connection failure")
            return 0
        raise RuntimeError("SeaweedFS outage unexpectedly returned an object")
    if operation == "tls-negative":
        settings = get_storage_settings()
        negative_checks = (
            (
                "untrusted CA",
                settings.model_copy(update={
                    "storage_ca_bundle_path": "/etc/ssl/certs/ca-certificates.crt",
                }),
            ),
            (
                "hostname mismatch",
                settings.model_copy(update={
                    "storage_endpoint_url": f"https://{socket.gethostbyname('seaweedfs')}:9443",
                }),
            ),
        )
        for label, invalid_settings in negative_checks:
            try:
                S3ObjectStorage(invalid_settings).head(key=_KEY)
            except SSLError:
                continue
            raise RuntimeError(f"S3 TLS verification accepted an invalid {label}")
        print("Task 8 S3 TLS: untrusted CA and hostname mismatch both rejected")
        return 0
    if operation == "runtime-iam":
        for operation_name, request in (
            ("ListObjectsV2", lambda: storage._client.list_objects_v2(  # noqa: SLF001
                Bucket=storage._bucket, Prefix="exemption_request/"  # noqa: SLF001
            )),
            ("DeleteObject", lambda: storage._client.delete_object(  # noqa: SLF001
                Bucket=storage._bucket, Key=_KEY  # noqa: SLF001
            )),
        ):
            try:
                request()
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code not in {"AccessDenied", "403"}:
                    raise
            else:
                raise RuntimeError(f"Runtime storage identity unexpectedly allowed {operation_name}")

        print("Task 8 storage IAM: runtime list/delete denied")
        return 0

    if operation == "gateway-iam":
        body, length = storage.open_read(key=_KEY)
        try:
            if length != len(_PAYLOAD) or body.read() != _PAYLOAD:
                raise RuntimeError("Gateway identity returned incorrect object bytes")
        finally:
            body.close()

        denied_requests = (
            ("PutObject", lambda: storage._client.put_object(  # noqa: SLF001
                Bucket=storage._bucket, Key=_KEY, Body=_PAYLOAD  # noqa: SLF001
            )),
            ("ListObjectsV2", lambda: storage._client.list_objects_v2(  # noqa: SLF001
                Bucket=storage._bucket, Prefix="exemption_request/"  # noqa: SLF001
            )),
            ("DeleteObject", lambda: storage._client.delete_object(  # noqa: SLF001
                Bucket=storage._bucket, Key=_KEY  # noqa: SLF001
            )),
        )
        for operation_name, request in denied_requests:
            try:
                request()
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code not in {"AccessDenied", "403"}:
                    raise
            else:
                raise RuntimeError(f"Gateway storage identity unexpectedly allowed {operation_name}")
        print("Task 8 storage IAM: gateway get allowed; put/list/delete denied")
        return 0

    if operation == "maintenance-iam":
        maintenance = S3MaintenanceObjectStorage(get_storage_settings())
        if _KEY not in set(maintenance.iter_keys(prefix="exemption_request/")):
            raise RuntimeError("Maintenance identity could not list the managed probe")
        maintenance.delete(key=_KEY)
        if maintenance.head(key=_KEY) is not None:
            raise RuntimeError("Maintenance identity delete did not remove the probe")
        print("Task 8 storage IAM: maintenance list/delete allowed")
        return 0
    raise SystemExit("Usage: python -m app.scripts.storage_lifecycle_preflight write|verify|outage")


if __name__ == "__main__":
    raise SystemExit(main())
