"""Local object-store topology and IAM contract tests."""

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]
POLICY_DIR = ROOT / "deploy" / "minio" / "policies"
BUCKET = "justice-files"
PREFIXES = {
    "soldier_exemption/",
    "exemption_request/",
    "gimelim/",
    "bug_report_screenshot/",
    "bug_report_comment/",
    "import_workbook/",
    "bug_report_json_mirror/",
}


def _compose():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _policy(name):
    return json.loads((POLICY_DIR / name).read_text(encoding="utf-8"))


def _statements(policy):
    return policy["Statement"]


def _allowed_actions(policy):
    return {
        action
        for statement in _statements(policy)
        if statement["Effect"] == "Allow"
        for action in (statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]])
    }


def test_minio_is_private_tls_enabled_persistent_and_not_host_published():
    compose = _compose()
    minio = compose["services"]["minio"]
    assert "ports" not in minio
    assert "--certs-dir" in minio["command"]
    assert any("minio-data" in volume for volume in minio["volumes"])
    assert "storage" in minio["networks"]
    assert compose["networks"]["storage"]["internal"] is True
    assert "MINIO_ROOT_USER" not in minio.get("environment", {})
    assert "MINIO_ROOT_PASSWORD" not in minio.get("environment", {})


def test_initializer_alone_receives_root_credentials_and_creates_private_bucket():
    compose = _compose()
    initializer = compose["services"]["minio-init"]
    assert "minio" in initializer["depends_on"]
    assert initializer["restart"] == "no"
    assert "storage" in initializer["networks"]
    assert initializer["env_file"] == ["./deploy/minio/secrets/initializer.env"]
    script = (ROOT / "deploy/minio/init-bucket.sh").read_text(encoding="utf-8")
    assert "mc mb --ignore-existing" in script
    assert "mc anonymous set none" in script
    assert "maintenance" in script and "gateway-get" in script and "api-put-get" in script


def test_only_initializer_receives_root_credentials_and_local_secrets_are_ignored():
    compose = _compose()
    initializer = compose["services"]["minio-init"]
    assert initializer["env_file"] == ["./deploy/minio/secrets/initializer.env"]
    assert "MINIO_ROOT_USER" not in compose["services"]["minio"].get("environment", {})
    env_defaults = (ROOT / ".env.defaults").read_text(encoding="utf-8")
    assert "MINIO_ROOT_PASSWORD=" not in env_defaults
    assert "STORAGE_SECRET_ACCESS_KEY=" not in env_defaults
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "deploy/minio/secrets/" in ignored
    cert_script = (ROOT / "scripts/dev-certs.ps1").read_text(encoding="utf-8")
    for identity in ("MINIO_ROOT_PASSWORD", "STORAGE_SECRET_ACCESS_KEY", "STORAGE_GATEWAY_SECRET_ACCESS_KEY",
                     "STORAGE_MAINTENANCE_SECRET_ACCESS_KEY"):
        assert identity in cert_script


def test_api_identity_has_only_object_put_get_and_no_bucket_or_delete_access():
    policy = _policy("api-put-get.json")
    actions = _allowed_actions(policy)
    assert actions == {"s3:GetObject", "s3:PutObject"}
    assert {statement["Resource"] for statement in _statements(policy)} == {f"arn:aws:s3:::{BUCKET}/*"}
    assert not actions & {"s3:ListBucket", "s3:DeleteObject", "s3:CreateBucket", "s3:PutBucketPolicy"}


def test_gateway_identity_is_get_only():
    policy = _policy("gateway-get.json")
    actions = _allowed_actions(policy)
    assert actions == {"s3:GetObject"}
    assert all(statement["Resource"] == f"arn:aws:s3:::{BUCKET}/*" for statement in _statements(policy))
    assert not actions & {"s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:PutBucketPolicy"}


def test_maintenance_identity_can_manage_managed_object_prefixes_only():
    policy = _policy("maintenance.json")
    actions = _allowed_actions(policy)
    assert actions == {"s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"}
    bucket_statement = next(s for s in _statements(policy) if "s3:ListBucket" in s["Action"])
    assert bucket_statement["Resource"] == f"arn:aws:s3:::{BUCKET}"
    assert set(bucket_statement["Condition"]["StringLike"]["s3:prefix"]) == {f"{p}*" for p in PREFIXES}
    object_statement = next(s for s in _statements(policy) if "s3:GetObject" in s["Action"])
    assert set(object_statement["Resource"]) == {f"arn:aws:s3:::{BUCKET}/{prefix}*" for prefix in PREFIXES}
    assert not actions & {"s3:CreateBucket", "s3:PutBucketPolicy", "s3:PutUserPolicy", "s3:DeleteBucket"}


def test_generated_certificate_and_secret_paths_are_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("deploy/minio/certs/", "deploy/minio/secrets/", "*.key", "*.pem"):
        assert pattern in ignored
    cert_script = (ROOT / "scripts/dev-certs.ps1").read_text(encoding="utf-8")
    for service_name in ("gateway", "file-authorization", "minio", "proxy"):
        assert service_name in cert_script
