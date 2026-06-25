# Backend crash logging — design

## Problem

The backend process sometimes crashes after running for a while, with no
reliable way to diagnose why: uvicorn logs only go to the terminal (lost on
restart/close), there's no file-based log, and a crash currently means the
process just stops — manually in `dev.ps1`, or container-dead in
`docker-compose` (no restart policy on `backend` today).

Goal: persist backend (and bot) logs to a file on disk in both the native
dev (`dev.ps1`) and `docker-compose` flows, make crashes clearly identifiable
in that file, and auto-restart after a crash so the service self-heals while
leaving evidence behind.

## 1. Logging configuration

New `backend/app/logging_config.py` exposing `setup_logging(log_filename: str)`,
called once at process startup by both the backend app and the bot.

- `RotatingFileHandler(logs/<log_filename>, maxBytes=10_000_000, backupCount=5)`
  attached to the root logger — bounded growth, no manual cleanup.
- `StreamHandler(sys.stdout)` also attached to root, so `dev.ps1`'s colored
  terminal output and `docker compose logs` are unaffected.
- Formatter: `%(asctime)s %(levelname)s %(name)s: %(message)s`.
- Explicitly attaches the same handlers to `uvicorn`, `uvicorn.error`, and
  `uvicorn.access` loggers (they don't propagate to root by default), so
  request logs and uvicorn's own startup/error output land in the file.
- Creates the `logs/` directory (relative to the project root) if missing.
- Installs a `sys.excepthook` that logs any uncaught exception in the main
  thread at CRITICAL with full traceback before the process exits.

Backend calls `setup_logging("backend.log")`; bot calls `setup_logging("bot.log")`.
Both write into the project's existing root-level `logs/` directory (already
used by `dev.ps1` for prior log files).

## 2. In-process crash markers

- **Backend** (`app/main.py` `lifespan`): log
  `"=== STARTUP pid=<pid> ==="` at the start of `lifespan`, and
  `"=== CLEAN SHUTDOWN ==="` at the end, after the email worker task is
  cancelled. A STARTUP line with no preceding CLEAN SHUTDOWN line is an
  unambiguous, greppable crash signal.
- Install an asyncio exception handler (`loop.set_exception_handler`) in
  `lifespan` so an unhandled exception in the background `run_email_worker`
  task is logged at CRITICAL with traceback instead of vanishing silently.
- **Bot** (`bot/main.py`): same STARTUP/CLEAN SHUTDOWN markers around
  `app.run_polling()`. Wrap the call in try/except that logs CRITICAL with
  traceback on crash, then re-raises so the process still exits non-zero
  (required for the supervisors/restart policies below to detect failure).

## 3. dev.ps1 flow — auto-restart on crash

- **Backend**: extend `backend/run_dev_server.py`, which already supervises
  uvicorn and restarts it on file changes. Restructure the watch loop so file
  watching runs in a background thread while the main loop also polls
  `proc.poll()`. On an *unexpected* exit (not one we triggered ourselves via
  `stop_server()` for a file-change restart or shutdown), append a CRASH
  marker line directly to `logs/backend.log`, wait a short backoff (~1s), and
  call `start_server()` again. Ctrl+C / SIGTERM / SIGBREAK still exit cleanly
  without triggering a restart.
- **Bot**: today `dev.ps1` launches `python -m bot.main` directly with no
  supervision. Add `backend/run_dev_bot.py`, mirroring `run_dev_server.py`'s
  structure (start subprocess, detect crash vs. clean exit, append CRASH
  marker to `logs/bot.log`, auto-restart with backoff). Update `dev.ps1`'s bot
  command to invoke this wrapper instead of calling `bot.main` directly.

## 4. docker-compose flow — mount + restart policy

- Add `restart: unless-stopped` to the `backend` service (already present on
  `telegram-bot`) — Docker's restart policy handles auto-restart-on-crash for
  containers; no custom supervisor needed inside the container.
- Add `./logs:/app/logs` volume mount to both `backend` and `telegram-bot`
  services, so files written inside the container at `/app/logs/backend.log`
  and `/app/logs/bot.log` land in the host's `./logs/` directory — the same
  directory `dev.ps1` writes to natively.
- No Dockerfile changes needed; `setup_logging` creates `logs/` if missing.

## 5. Verification plan

- Start the dev stack, hit a route, confirm lines appear in
  `logs/backend.log` and `logs/bot.log`.
- Force a crash (e.g. temporarily raise in a background task, or kill the
  uvicorn process) and confirm: a CRASH marker appears in the log, and the
  process auto-restarts within a couple seconds — in both `dev.ps1` and
  `docker compose up` flows.
- `docker compose down && docker compose up`, then confirm `./logs/backend.log`
  on the host has content (proves the volume mount works).

## Out of scope

- Structured/JSON logging, log shipping to an external service.
- Auto-restart/logging changes to `frontend` or `db` services.
- Cleaning up the existing stale root-level files (`backend.log`,
  `backend_err.log`, `backend_pid.txt`, `backend/run_dev_server.log`,
  `logs/dev_server_*.log`) — these are untracked, already covered by the
  `*.log` gitignore pattern, and unrelated to any current script.
