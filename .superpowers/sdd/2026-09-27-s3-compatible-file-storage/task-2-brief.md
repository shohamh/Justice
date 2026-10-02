### Task 2: Add local MinIO, TLS certificates, and least-privilege identities

**Files:**
- Modify: docker-compose.yml
- Modify: .env.defaults
- Modify: .gitignore
- Create: scripts/dev-certs.ps1
- Create: deploy/minio/init-bucket.sh
- Create: deploy/minio/policies/api-put-get.json
- Create: deploy/minio/policies/gateway-get.json
- Create: deploy/minio/policies/maintenance.json
- Test: backend/app/storage/tests/test_compose_storage.py

**Interfaces:**
- API identity has put/get only; gateway has get only; maintenance/migration has scoped list/get/put/delete. The MinIO server and one-shot initializer receive the same generated root credential pair in separate ignored env files because MinIO requires root env values to avoid the `minioadmin` fallback. The initializer is the only root admin client; API, gateway, and maintenance processes never receive root credentials.
- Local certificates cover gateway, authorization service, MinIO, and proxy Compose DNS names. Keep generated private keys and credentials ignored by Git.

- [ ] **Step 1: Add failing tests for MinIO TLS, bucket initialization, and least-privilege policies**

  Cover API put/get, gateway get-only, and maintenance scoped list/get/put/delete permissions; assert denied actions fail.

- [ ] **Step 2: Run focused storage configuration tests and confirm they fail**

  Verify Compose services, TLS configuration, and policy wiring.

- [ ] **Step 3: Implement MinIO and its Compose topology**

  Add MinIO with TLS server certificates, persistent data, private bucket initialization, and the least-privilege policies above. Keep it on the internal storage network and do not publish its port. The MinIO server and one-shot initializer receive the same generated root credential pair; the initializer is the only admin client and creates the bucket and service users. API, gateway, and maintenance processes never receive root credentials. Add generated certificates and secrets to .gitignore.

- [ ] **Step 4: Verify Compose configuration, TLS identity, and IAM**

  Run `docker compose config --quiet` and `.\scripts\dev-certs.ps1`, then start `minio` and `minio-init`. Confirm MinIO health, private bucket policies, TLS SAN verification from an API container, and denied host connections to its port.

- [ ] **Step 5: Commit the local storage infrastructure**

  Commit Compose, the cert helper, MinIO initialization and policies, and focused infrastructure tests as the private object store infrastructure change.

