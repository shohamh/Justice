# Exchange calendar sync operations

Justice publishes official duty calendar events to the organization's on-premises Exchange server. The durable outbox worker performs all EWS requests in its own process. FastAPI startup does not import the EWS client or contact Exchange, so Exchange outages do not prevent the API from starting or serving Justice data.

## Production setup

Before enabling the worker, have the Exchange administrator confirm all of the following:

- The internal EWS URL for the correct Exchange organization, usually `https://<exchange-host>/EWS/Exchange.asmx`, including valid TLS and network reachability from the Justice host.
- The supported authentication mode and exact username format. Set `EXCHANGE_AUTH_TYPE` to the administrator-approved mode (for example, `NTLM`); do not infer it from a test server.
- The `svc_justice` account is a dedicated service account with the minimum required permission to create, update, find, and cancel events in the selected shared mailbox. Confirm the exact mailbox permission or impersonation role with the administrator.
- The server's actual throttling policy. The configured application limit is a client safeguard; it does not change or guarantee Exchange's server-side throttling behavior.

Set `EXCHANGE_CALENDAR_ENABLED=true`, the confirmed endpoint, mailbox, username, auth type, and request limit in `deploy/.env.production`. Keep `EXCHANGE_PASSWORD` out of that file. Provision the password separately using the organization's deployment secret manager, then make it available as a protected file whose path is set by `EXCHANGE_PASSWORD_FILE`. Restrict the file and its parent directory to the deployment account. Compose mounts that file as `/run/secrets/EXCHANGE_PASSWORD` for the worker only; the value is never part of the example env file or API container environment.

The production worker uses the backend image and `python -m app.exchange_calendar_worker`. It has no published port and waits for a healthy database and the one-shot `schema-migration` service to complete. The API is a separate service and does not run the worker.

After provisioning the secret and completing the administrator checks, deploy with the same env file used for Compose interpolation:

```powershell
docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml config
docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml up -d --build
```

If the worker is enabled but endpoint, mailbox, username, or password is missing, it exits with a message naming the missing setting only. It does not include a credential value in its exception or logs. Fix the configuration and restart `exchange-calendar-worker`.

## Settings

| Setting | Purpose | Default / limit |
| --- | --- | --- |
| `EXCHANGE_CALENDAR_ENABLED` | Enables the dedicated worker | `false` in Settings; production example sets `true` |
| `EXCHANGE_EWS_URL` | Administrator-confirmed on-prem EWS endpoint | Required when enabled |
| `EXCHANGE_MAILBOX` | Shared calendar mailbox | Required when enabled |
| `EXCHANGE_USERNAME` | `svc_justice` login name in the confirmed format | Required when enabled |
| `EXCHANGE_PASSWORD` | Worker credential, loaded from the deployment secret file in production | Never put in an env example or log |
| `EXCHANGE_AUTH_TYPE` | Administrator-confirmed authentication mode | Optional if the client uses its default |
| `EXCHANGE_REQUESTS_PER_MINUTE` | Client-side request limiter | Default `200`; allowed range `1`–`200` |

The server-wide cap is 200 requests per minute. An administrator may choose a lower value in the allowed range. Values above 200 are rejected at settings validation, even if the Exchange server advertises a higher limit.

## Local development

The native development stack remains the default. Start the worker only when needed:

```powershell
.\dev.ps1 -ExchangeCalendarWorker
```

The worker appears as a separate `exchange-calendar` log stream. Without the switch, `dev.ps1` does not launch it. If the switch is used while `EXCHANGE_CALENDAR_ENABLED` is absent or false, the process logs that it is disabled and exits. For an isolated Compose run, the root `exchange-calendar-worker` service is behind the `exchange-calendar` profile.

## Optional Gromox smoke test (test only)

Gromox is a disposable EWS-compatible test endpoint. It is not part of production Compose, the backend image, production environment configuration, or application startup. Do not point this test at the live `svc_justice` mailbox.

Start a disposable Gromox instance and mailbox in an isolated test environment, then inject these test-only variables from a local secret manager or shell environment:

- `JUSTICE_TEST_GROMOX_ENABLED=1`
- `JUSTICE_TEST_GROMOX_ENDPOINT`
- `JUSTICE_TEST_GROMOX_MAILBOX`
- `JUSTICE_TEST_GROMOX_USERNAME`
- `JUSTICE_TEST_GROMOX_PASSWORD`
- `JUSTICE_TEST_GROMOX_ATTENDEE`
- `JUSTICE_TEST_GROMOX_AUTH_TYPE` (only when the test instance needs an explicit mode)

From `backend/`, run:

```powershell
pytest tests/integration/test_exchange_calendar_gromox.py -q
```

The test skips unless explicitly enabled and configured. It creates a disposable meeting, exercises its lifecycle through the EWS client, and cleans up the test event. Keep its endpoint and credentials separate from production values.

## Queue, retry, and time behavior

Queue claims prefer larger priority values:

| Work | Priority |
| --- | ---: |
| Backfill | 10 |
| Reconciliation | 50 |
| Current user changes | 100 |
| Explicit urgent/admin retry | 200 |

The worker probes Exchange every 15 minutes and runs the bootstrap reconciliation every 6 hours. Failed work remains recorded in the outbox. Retryable event failures enter `retry_wait` with a persisted next-attempt time; Exchange throttling or a busy response can also set a shared backoff, which prevents repeated requests during the server's cooldown. The worker resumes due work after the delay and continues to favor recent user changes over background backfill.

Dates and event times follow `Asia/Jerusalem`, including Israel daylight-saving transitions. The production backend image and database are configured for that timezone so a duty's Justice date stays the same calendar date in Exchange.

## Status and outage handling

Admins can open **Admin Settings → Exchange Calendar Sync**. The panel shows queue/status counts, recent attempts, worker heartbeat, Exchange reachability, and any shared backoff. Event history includes safe error categories and current attendee/projection problems; it does not expose passwords, raw SOAP/XML, or Exchange item IDs. Admins can inspect a failed or partial event and request a single urgent retry from that panel.

When Exchange is unreachable or throttling, keep using Justice as the source of truth. The API and duty workflows remain available while the separate worker records and delays sync work. Check the panel's heartbeat, reachability, sanitized error category, and backoff before acting. Do not delete outbox rows or repeatedly retry during a reported cooldown. Once network/authentication service is restored, the worker probes again and processes due work; use the admin retry only for items that remain failed or partial after recovery.
