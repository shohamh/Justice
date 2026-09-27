"""Local object-store topology and IAM contract tests."""

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]
POLICY_DIR = ROOT / "deploy" / "minio" / "policies"
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


def test_minio_server_is_private_tls_enabled_persistent_and_receives_generated_root_credentials():
    compose = _compose()
    minio = compose["services"]["minio"]
    assert "ports" not in minio
    assert "--certs-dir" in minio["command"]
    assert any("minio-data" in volume for volume in minio["volumes"])
    assert "storage" in minio["networks"]
    assert compose["networks"]["storage"]["internal"] is True
    assert minio["env_file"] == ["./deploy/minio/secrets/minio-root.env"]
    cert_script = (ROOT / "scripts/dev-certs.ps1").read_text(encoding="utf-8")
    assert '$minioRootEnv = Join-Path $secretsDirectory "minio-root.env"' in cert_script
    assert 'Set-Content -Path $minioRootEnv' in cert_script


def test_initializer_is_the_only_root_admin_client_and_creates_private_bucket():
    compose = _compose()
    initializer = compose["services"]["minio-init"]
    assert "minio" in initializer["depends_on"]
    assert initializer["restart"] == "no"
    assert "storage" in initializer["networks"]
    assert initializer["env_file"] == ["./deploy/minio/secrets/initializer.env"]
    cert_script = (ROOT / "scripts/dev-certs.ps1").read_text(encoding="utf-8")
    assert cert_script.count('"MINIO_ROOT_USER=$rootUser", "MINIO_ROOT_PASSWORD=$rootPassword"') == 2
    script = (ROOT / "deploy/minio/init-bucket.sh").read_text(encoding="utf-8")
    assert "mc mb --ignore-existing" in script
    assert "mc anonymous set none" in script
    assert "maintenance" in script and "gateway-get" in script and "api-put-get" in script
    assert 'case "$MINIO_BUCKET" in' in script
    assert "*[!a-z0-9-]*" in script
    assert 'sed "s/__BUCKET__/$MINIO_BUCKET/g"' in script
    assert 'mc admin policy create local "$policy"' in script
    assert "mc admin policy info local" not in script


def test_minio_and_initializer_receive_root_credentials_but_app_services_do_not():
    compose = _compose()
    initializer = compose["services"]["minio-init"]
    assert initializer["env_file"] == ["./deploy/minio/secrets/initializer.env"]
    for name, service in compose["services"].items():
        if name in {"minio", "minio-init"}:
            continue
        assert "MINIO_ROOT_USER" not in service.get("environment", {})
        assert "MINIO_ROOT_PASSWORD" not in service.get("environment", {})
        assert "minio-root.env" not in str(service.get("env_file", []))
        assert "initializer.env" not in str(service.get("env_file", []))
    env_defaults = (ROOT / ".env.defaults").read_text(encoding="utf-8")
    assert "MINIO_ROOT_PASSWORD=" not in env_defaults
    assert "STORAGE_SECRET_ACCESS_KEY=" not in env_defaults
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "deploy/minio/secrets/" in ignored
    cert_script = (ROOT / "scripts/dev-certs.ps1").read_text(encoding="utf-8")
    for identity in ("MINIO_ROOT_PASSWORD", "STORAGE_SECRET_ACCESS_KEY", "STORAGE_GATEWAY_SECRET_ACCESS_KEY",
                     "STORAGE_MAINTENANCE_SECRET_ACCESS_KEY"):
        assert identity in cert_script


def test_policy_templates_render_to_a_configured_bucket():
    configured_bucket = "justice-storage-test"
    for name in ("api-put-get.json", "gateway-get.json", "maintenance.json"):
        template = (POLICY_DIR / name).read_text(encoding="utf-8")
        assert "__BUCKET__" in template
        rendered = json.loads(template.replace("__BUCKET__", configured_bucket))
        resources = [statement["Resource"] for statement in _statements(rendered)]
        resources = [resource for item in resources for resource in (item if isinstance(item, list) else [item])]
        assert resources
        assert all(configured_bucket in resource and "__BUCKET__" not in resource for resource in resources)


def test_initializer_rerenders_changed_policy_source_on_every_run():
    script = (ROOT / "deploy/minio/init-bucket.sh").read_text(encoding="utf-8")
    assert "for policy in api-put-get gateway-get maintenance; do" in script
    assert 'sed "s/__BUCKET__/$MINIO_BUCKET/g" "/policies/$policy.json"' in script
    assert 'mc admin policy create local "$policy" "$rendered_policy"' in script
    assert "mc admin policy info local" not in script

    source = (POLICY_DIR / "api-put-get.json").read_text(encoding="utf-8")
    first_render = json.loads(source.replace("__BUCKET__", "justice-storage-test"))
    changed_source = source.replace('"s3:GetObject"', '"s3:GetObject", "s3:DeleteObject"')
    second_render = json.loads(changed_source.replace("__BUCKET__", "justice-storage-test"))
    assert _allowed_actions(first_render) == {"s3:GetObject", "s3:PutObject"}
    assert _allowed_actions(second_render) == {"s3:GetObject", "s3:PutObject", "s3:DeleteObject"}


def test_api_identity_has_only_object_put_get_and_no_bucket_or_delete_access():
    policy = _policy("api-put-get.json")
    actions = _allowed_actions(policy)
    assert actions == {"s3:GetObject", "s3:PutObject"}
    assert {statement["Resource"] for statement in _statements(policy)} == {"arn:aws:s3:::__BUCKET__/*"}
    assert not actions & {"s3:ListBucket", "s3:DeleteObject", "s3:CreateBucket", "s3:PutBucketPolicy"}


def test_gateway_identity_is_get_only():
    policy = _policy("gateway-get.json")
    actions = _allowed_actions(policy)
    assert actions == {"s3:GetObject"}
    assert all(statement["Resource"] == "arn:aws:s3:::__BUCKET__/*" for statement in _statements(policy))
    assert not actions & {"s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:PutBucketPolicy"}


def test_maintenance_identity_can_manage_managed_object_prefixes_only():
    policy = _policy("maintenance.json")
    actions = _allowed_actions(policy)
    assert actions == {"s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"}
    bucket_statement = next(s for s in _statements(policy) if "s3:ListBucket" in s["Action"])
    assert bucket_statement["Resource"] == "arn:aws:s3:::__BUCKET__"
    assert set(bucket_statement["Condition"]["StringLike"]["s3:prefix"]) == {f"{p}*" for p in PREFIXES}
    object_statement = next(s for s in _statements(policy) if "s3:GetObject" in s["Action"])
    assert set(object_statement["Resource"]) == {f"arn:aws:s3:::__BUCKET__/{prefix}*" for prefix in PREFIXES}
    assert not actions & {"s3:CreateBucket", "s3:PutBucketPolicy", "s3:PutUserPolicy", "s3:DeleteBucket"}


def test_generated_certificate_and_secret_paths_are_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("deploy/minio/certs/", "deploy/minio/secrets/", "*.key", "*.pem"):
        assert pattern in ignored
    cert_script = (ROOT / "scripts/dev-certs.ps1").read_text(encoding="utf-8")
    for service_name in ("gateway", "file-authorization", "minio", "proxy"):
        assert service_name in cert_script
