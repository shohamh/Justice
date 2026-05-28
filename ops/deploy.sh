#!/usr/bin/env bash
# Provision and launch the prod stack on a fresh Debian/Ubuntu GCP e2-micro VM.
# Run as a sudo-capable user from the repo root: bash ops/deploy.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose --env-file ops/.env -f ops/docker-compose.prod.yml)

# 1. Swap — e2-micro has ~1GB RAM; 2G swap keeps Postgres + uvicorn + the image build alive.
if ! swapon --show 2>/dev/null | grep -q '/swapfile'; then
	echo ">> Creating 2G swapfile"
	sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
	sudo chmod 600 /swapfile
	sudo mkswap /swapfile
	sudo swapon /swapfile
	grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# 2. Docker Engine + compose plugin (idempotent).
if ! command -v docker >/dev/null 2>&1; then
	echo ">> Installing Docker"
	curl -fsSL https://get.docker.com | sudo sh
	sudo usermod -aG docker "$USER" || true
fi

# 3. Require the filled-in env file.
if [ ! -f "$REPO_DIR/ops/.env" ]; then
	echo "ERROR: $REPO_DIR/ops/.env is missing." >&2
	echo "Copy ops/.env.prod.example to ops/.env and fill in real secrets first." >&2
	exit 1
fi

# 4. Build and launch.
cd "$REPO_DIR"
echo ">> Building and starting the stack"
sudo "${COMPOSE[@]}" up -d --build
echo ">> Status:"
sudo "${COMPOSE[@]}" ps
