# Deploying to a free GCP e2-micro VM

The whole stack (Postgres + FastAPI backend + React SPA) runs on one host behind Caddy,
which terminates TLS and serves the SPA + reverse-proxies `/api` on a single origin
(so the `SameSite=strict` auth cookie keeps working). TLS is free via Let's Encrypt using
a `nip.io` hostname derived from the VM's IP.

## 1. Provision the VM (run locally, needs gcloud + a billing-enabled project)

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud config set compute/zone us-central1-a   # Always Free regions: us-west1, us-central1, us-east1

# Static IP (free while attached to a running instance) — keeps the nip.io URL + cert stable
gcloud compute addresses create cod2-ip --region=us-central1
gcloud compute addresses describe cod2-ip --region=us-central1 --format='get(address)'

# Always Free shape: e2-micro, free region, pd-standard <= 30GB
gcloud compute instances create cod2 \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-standard \
  --address=cod2-ip \
  --tags=http-server,https-server

# Open 80 (required for Let's Encrypt HTTP-01) and 443
gcloud compute firewall-rules create allow-http  --network=default --direction=INGRESS --action=ALLOW --rules=tcp:80  --source-ranges=0.0.0.0/0 --target-tags=http-server
gcloud compute firewall-rules create allow-https --network=default --direction=INGRESS --action=ALLOW --rules=tcp:443 --source-ranges=0.0.0.0/0 --target-tags=https-server
```

## 2. Deploy (run on the VM)

```bash
gcloud compute ssh cod2 --zone=us-central1-a   # from your machine

sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/shohamh/callofduty2.git
cd callofduty2

cp ops/.env.prod.example ops/.env
# Edit ops/.env: set POSTGRES_PASSWORD (must match DB_ADMIN_URL), JWT_SECRET
# (openssl rand -base64 48), SITE_ADDRESS=<IP>.nip.io, ALLOWED_ORIGINS=https://<IP>.nip.io
nano ops/.env

bash ops/deploy.sh
```

Open `https://<IP>.nip.io` and log in with the bootstrap admin.

## Notes

- Keep port 80 open even though you use HTTPS — Caddy needs it for the ACME challenge.
- First cert issuance takes ~10-30s.
- Update later: `git pull` on the VM, then re-run `bash ops/deploy.sh` (migrations re-run idempotently).
- The `app` Postgres role password is fixed to `app_pw` by migration 0001; see `ops/.env.prod.example`.
- If you stop/delete the VM, release the static IP to avoid a small charge:
  `gcloud compute addresses delete cod2-ip --region=us-central1`.
