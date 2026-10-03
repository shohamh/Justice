import pytest
from botocore.exceptions import ClientError

from app.storage.initialize_bucket import initialize_bucket


class FakeS3:
    def __init__(self, exists):
        self.exists = exists
        self.created = []
    def head_bucket(self, **kwargs):
        if not self.exists:
            raise ClientError({"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadBucket")
    def create_bucket(self, **kwargs):
        self.created.append(kwargs["Bucket"])
        self.exists = True

def test_creates_missing_bucket_and_is_idempotent(monkeypatch):
    monkeypatch.setenv("STORAGE_BUCKET", "justice-files")
    client = FakeS3(False)
    initialize_bucket(client, attempts=1)
    initialize_bucket(client, attempts=1)
    assert client.created == ["justice-files"]

def test_does_not_treat_access_denied_as_missing_bucket(monkeypatch):
    monkeypatch.setenv("STORAGE_BUCKET", "justice-files")
    class Denied(FakeS3):
        def head_bucket(self, **kwargs):
            raise ClientError({"Error": {"Code": "403"}, "ResponseMetadata": {"HTTPStatusCode": 403}}, "HeadBucket")
    with pytest.raises(ClientError):
        initialize_bucket(Denied(False), attempts=1)
