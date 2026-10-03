"""Initialize the private local SeaweedFS bucket with the bootstrap identity."""
import logging
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

logger = logging.getLogger(__name__)
_RETRYABLE = (ConnectionClosedError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError)

def _client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["STORAGE_ENDPOINT_URL"],
        region_name=os.getenv("STORAGE_REGION", "us-east-1"),
        aws_access_key_id=os.environ["STORAGE_BOOTSTRAP_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["STORAGE_BOOTSTRAP_SECRET_ACCESS_KEY"],
        verify=os.environ["STORAGE_CA_BUNDLE_PATH"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                      retries={"max_attempts": 2, "mode": "standard"},
                      connect_timeout=3, read_timeout=5),
    )

def initialize_bucket(client=None, *, attempts: int = 30, interval: float = 2.0) -> None:
    bucket = os.environ["STORAGE_BUCKET"]
    client = client or _client()
    for attempt in range(attempts):
        try:
            try:
                client.head_bucket(Bucket=bucket)
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if code not in {"404", "NoSuchBucket", "NotFound"} and status != 404:
                    raise
                client.create_bucket(Bucket=bucket)
            logger.info("Private object storage bucket is ready")
            return
        except _RETRYABLE as exc:
            if attempt + 1 == attempts:
                raise RuntimeError("SeaweedFS S3 endpoint did not become ready") from exc
            time.sleep(interval)
    raise RuntimeError("SeaweedFS S3 endpoint did not become ready")

if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    initialize_bucket()
