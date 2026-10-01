"""Local object-store topology and IAM contract tests."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]

def _compose():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

def test_seaweedfs_private_loopback_tls_and_persistent():
    compose = _compose()
    seaweed = compose["services"]["seaweedfs"]
    proxy = compose["services"]["seaweedfs-s3-proxy"]
    assert "ports" not in seaweed and "ports" not in proxy
    assert "-ip.bind=0.0.0.0" in seaweed["command"]
    assert "-s3.ip.bind=127.0.0.1" in seaweed["command"]
    assert "-s3.port=8333" in seaweed["command"]
    assert "-s3.port.https=8334" in seaweed["command"]
    assert "-s3.config=/etc/seaweedfs/s3.json" in seaweed["command"]
    assert "seaweedfs-data:/data" in seaweed["volumes"]
    assert compose["networks"]["storage"]["internal"] is True
    assert proxy["network_mode"] == "service:seaweedfs"
    nginx = (ROOT / "deploy/seaweedfs/nginx-s3.conf").read_text(encoding="utf-8")
    assert "listen 9443 ssl" in nginx and "proxy_ssl_verify on" in nginx

def test_initializer_is_one_shot_and_uses_bootstrap_identity():
    compose = _compose()
    init = compose["services"]["seaweedfs-init"]
    assert init["command"] == ["python", "-m", "app.storage.initialize_bucket"]
    assert init["restart"] == "no"
    assert init["env_file"] == ["./deploy/seaweedfs/secrets/initializer.env"]
    assert "seaweedfs-s3-proxy" in init["depends_on"]
    server = compose["services"]["seaweedfs"]
    assert "STORAGE_BOOTSTRAP_ACCESS_KEY_ID" not in server.get("environment", {})
    assert "./deploy/seaweedfs/secrets/encryption.env" in server["env_file"]
    script = (ROOT / "scripts/dev-certs.ps1").read_text(encoding="utf-8")
    assert 'actions = @("Admin")' in script
    assert "policyNames" in script
    assert "STORAGE_BOOTSTRAP_SECRET_ACCESS_KEY" in script

def test_static_identities_are_scoped_to_required_s3_actions():
    script = (ROOT / "scripts/dev-certs.ps1").read_text(encoding="utf-8")
    assert 'Action = @("s3:GetObject", "s3:PutObject")' in script
    assert 'Action = @("s3:GetObject")' in script
    assert 'Action = @("s3:ListBucket")' in script
    assert "s3:DeleteObject" in script
    assert '"$($_)/*"' in script

def test_secret_paths_and_endpoints_use_seaweedfs():
    defaults = (ROOT / ".env.defaults").read_text(encoding="utf-8")
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "STORAGE_ENDPOINT_URL=https://seaweedfs:9443" in defaults
    assert "MINIO_" not in defaults
    assert "deploy/seaweedfs/secrets/" in ignored
    assert "deploy/seaweedfs/certs/" in ignored
    services = _compose()["services"]
    assert services["file-gateway"]["env_file"] == ["./deploy/seaweedfs/secrets/gateway.env"]
    assert services["backend"]["env_file"][-1] == "./deploy/seaweedfs/secrets/api.env"
    assert services["file-storage-maintenance"]["env_file"] == ["./deploy/seaweedfs/secrets/maintenance.env"]
    endpoint = "$" + "{STORAGE_ENDPOINT_URL:-https://seaweedfs:9443}"
    assert services["file-gateway"]["environment"]["STORAGE_ENDPOINT_URL"] == endpoint
    assert services["file-storage-maintenance"]["environment"]["STORAGE_ENDPOINT_URL"] == endpoint

def test_file_gateway_mtls_and_production_storage_are_provider_agnostic():
    compose = _compose()
    services = compose["services"]
    assert services["file-authorization"]["networks"] == ["file-authz", "authz-db"]
    assert "DB_ADMIN_URL" in services["file-authorization"]["environment"]
    assert services["file-gateway"]["networks"] == ["default", "storage", "file-authz"]
    assert services["db"]["networks"] == ["default", "authz-db"]
    assert compose["networks"]["file-authz"]["internal"] is True
    assert "FILE_GATEWAY_CLIENT_CERT" in services["file-gateway"]["environment"]
    assert "FILE_AUTHORIZATION_GATEWAY_CA" in services["file-authorization"]["environment"]
    prod = yaml.safe_load((ROOT / "deploy/docker-compose.prod.yml").read_text(encoding="utf-8"))["services"]
    assert "STORAGE_ACCESS_KEY_ID" not in prod["file-storage-maintenance"]["environment"]


def test_docker_dev_launcher_starts_seaweedfs_storage_services():
    script = (ROOT / "dev.ps1").read_text(encoding="utf-8")
    match = re.search(r"\$composeServices\s*=\s*@\((.*?)\)", script, re.DOTALL)
    assert match is not None
    services = set(re.findall(r"'([^']+)'", match.group(1)))
    assert {"seaweedfs", "seaweedfs-s3-proxy", "seaweedfs-init"} <= services
    assert not {"minio", "minio-init"} & services


def test_compose_login_limit_keeps_default_and_allows_local_override():
    backend_environment = _compose()["services"]["backend"]["environment"]
    assert "LOGIN_RATE_LIMIT=${LOGIN_RATE_LIMIT:-10/5minutes}" in backend_environment
