from hashlib import sha256
from io import BytesIO
from uuid import UUID

import boto3
import pytest
from botocore.client import Config
from botocore.stub import Stubber

from app.settings import Settings, StorageMaintenanceSettings, StorageSettings
from app.storage.keys import make_object_key
from app.storage.s3 import S3MaintenanceObjectStorage, S3ObjectStorage

KEY = make_object_key("gimelim", UUID("01234567-89ab-4cde-8f01-23456789abcd"))
SHA = sha256(b"abc").hexdigest()


def settings(**overrides):
    values = dict(DATABASE_URL="x", DB_ADMIN_URL="x", JWT_SECRET="x" * 32,
                  STORAGE_BUCKET="private-files", STORAGE_REGION="us-east-1",
                  STORAGE_ENDPOINT_URL="https://storage.example.invalid",
                  STORAGE_ACCESS_KEY_ID="private-id", STORAGE_SECRET_ACCESS_KEY="private-secret",
                  STORAGE_SSE_ALGORITHM="aws:kms", STORAGE_SSE_KEY_ID="private-key-id")
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_storage_settings_do_not_require_database_or_jwt_secrets():
    storage_settings = StorageSettings(
        _env_file=None,
        STORAGE_BUCKET="private-files",
        STORAGE_ENDPOINT_URL="https://storage.example.invalid",
    )

    assert storage_settings.storage_bucket == "private-files"
    assert storage_settings.storage_endpoint_url == "https://storage.example.invalid"


def test_storage_maintenance_settings_require_database_but_not_jwt_or_admin_url():
    maintenance_settings = StorageMaintenanceSettings(
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://migration-role@db/justice",
        STORAGE_BUCKET="private-files",
        STORAGE_ENDPOINT_URL="https://storage.example.invalid",
    )

    assert maintenance_settings.database_url == "postgresql+psycopg://migration-role@db/justice"


def client():
    return boto3.client("s3", region_name="us-east-1",
                        endpoint_url="https://storage.example.invalid",
                        aws_access_key_id="private-id", aws_secret_access_key="private-secret",
                        config=Config(signature_version="s3v4"))


def test_put_and_head_include_private_bucket_checksum_and_encryption():
    s3 = client()
    with Stubber(s3) as stub:
        stub.add_response("put_object", {}, {"Bucket": "private-files", "Key": KEY,
            "Body": b"abc", "ContentType": "application/pdf", "Metadata": {"sha256": SHA},
            "ServerSideEncryption": "aws:kms", "SSEKMSKeyId": "private-key-id"})
        stub.add_response("head_object", {"ContentLength": 3, "Metadata": {"sha256": SHA},
            "ServerSideEncryption": "aws:kms", "SSEKMSKeyId": "private-key-id"},
            {"Bucket": "private-files", "Key": KEY})
        storage = S3ObjectStorage(settings(), client=s3)
        stored = storage.put_bytes(key=KEY, data=b"abc", content_type="application/pdf", sha256=SHA)
        assert stored.key == KEY and stored.size == 3 and stored.sha256 == SHA
        assert stored.encryption_algorithm == "aws:kms"
        assert stored.encryption_key_id == "private-key-id"
        assert storage.head(key=KEY) == stored


def test_get_returns_closeable_stream_and_length():
    s3 = client()
    with Stubber(s3) as stub:
        stub.add_response("get_object", {"Body": BytesIO(b"abc"), "ContentLength": 3},
                          {"Bucket": "private-files", "Key": KEY})
        body, length = S3ObjectStorage(settings(), client=s3).open_read(key=KEY)
        assert length == 3 and body.read() == b"abc"
        body.close()
        assert body.closed


def test_missing_head_returns_none_and_delete_uses_managed_key():
    s3 = client()
    with Stubber(s3) as stub:
        stub.add_client_error("head_object", service_error_code="404", http_status_code=404,
                              expected_params={"Bucket": "private-files", "Key": KEY})
        stub.add_response("delete_object", {}, {"Bucket": "private-files", "Key": KEY})
        runtime = S3ObjectStorage(settings(), client=s3)
        assert runtime.head(key=KEY) is None
        assert not hasattr(runtime, "delete")
        S3MaintenanceObjectStorage(settings(), client=s3).delete(key=KEY)


def test_bad_key_is_rejected_before_s3_call():
    storage = S3ObjectStorage(settings(), client=client())
    with pytest.raises(ValueError):
        storage.open_read(key="../private-files")
    assert not hasattr(storage, "delete")
    maintenance = S3MaintenanceObjectStorage(settings(), client=client())
    with pytest.raises(ValueError):
        maintenance.delete(key="https://storage.example.invalid/private-files")


def test_client_uses_verified_tls_and_configured_endpoint(monkeypatch):
    calls = []
    actual = client()
    def fake_client(service, **kwargs):
        calls.append((service, kwargs))
        return actual
    monkeypatch.setattr("app.storage.s3.boto3.client", fake_client)
    S3ObjectStorage(settings(STORAGE_CA_BUNDLE_PATH="C:/certs/storage-ca.pem"))
    service, kwargs = calls[0]
    assert service == "s3"
    assert kwargs["endpoint_url"] == "https://storage.example.invalid"
    assert kwargs["verify"] == "C:/certs/storage-ca.pem"
    S3ObjectStorage(settings())
    assert calls[1][1]["verify"] is True
    assert kwargs["config"].s3["addressing_style"] == "path"


def test_exception_text_does_not_include_secret_or_endpoint_credentials():
    with pytest.raises(ValueError) as exc:
        S3ObjectStorage(settings(STORAGE_ENDPOINT_URL="http://private-id:private-secret@storage.example.invalid"))
    assert "private-secret" not in str(exc.value)
    assert "private-id" not in str(exc.value)


def test_checksum_mismatch_rejected_before_s3_call():
    storage = S3ObjectStorage(settings(), client=client())
    with pytest.raises(ValueError, match="checksum"):
        storage.put_bytes(key=KEY, data=b"abc", content_type="application/pdf", sha256="0" * 64)


def test_only_maintenance_adapter_can_list_managed_prefix():
    s3 = client()
    runtime = S3ObjectStorage(settings(), client=s3)
    assert not hasattr(runtime, "iter_keys")
    maintenance = S3MaintenanceObjectStorage(settings(), client=s3)
    with pytest.raises(ValueError):
        list(maintenance.iter_keys(prefix="../"))
    with Stubber(s3) as stub:
        stub.add_response("list_objects_v2", {"Contents": [{"Key": KEY}]},
                          {"Bucket": "private-files", "Prefix": "gimelim/"})
        assert list(maintenance.iter_keys(prefix="gimelim/")) == [KEY]


def test_head_rejects_missing_checksum_metadata():
    s3 = client()
    with Stubber(s3) as stub:
        stub.add_response("head_object", {"ContentLength": 3},
                          {"Bucket": "private-files", "Key": KEY})
        with pytest.raises(ValueError, match="checksum"):
            S3ObjectStorage(settings(), client=s3).head(key=KEY)
