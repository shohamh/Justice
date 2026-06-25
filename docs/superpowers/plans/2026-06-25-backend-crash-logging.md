# Backend Crash Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist backend and bot logs to a rotating file in `logs/` for both the `dev.ps1` and `docker-compose` flows, make crashes unambiguous in that file, and auto-restart the process after a crash.

**Architecture:** A shared `app/logging_config.py` module attaches a `RotatingFileHandler` + stdout `StreamHandler` to the root logger (and reroutes uvicorn's loggers through it) and installs a `sys.excepthook`. `app/main.py` and `bot/main.py` call it once at startup and log explicit STARTUP/CLEAN SHUTDOWN markers. For `dev.ps1` (no OS-level supervisor), `run_dev_server.py` is extended and a new `run_dev_bot.py` is added to detect unexpected process exits, write a CRASH marker, and auto-restart. For `docker-compose`, Docker's own `restart: unless-stopped` policy handles auto-restart, and a `./logs:/app/logs` volume mount plus a `LOG_DIR` env var make the container write into the same host `logs/` directory.

**Tech Stack:** Python 3.12, `logging.handlers.RotatingFileHandler`, FastAPI lifespan, asyncio exception handler, PowerShell, Docker Compose.

---

## File Structure

- Create: `backend/app/logging_config.py` — shared logging setup (rotating file + stdout handlers, uvicorn logger rerouting, excepthook)
- Create: `backend/tests/unit/test_logging_config.py` — unit tests for the above
- Create: `backend/run_dev_bot.py` — crash-detecting supervisor for the bot in `dev.ps1` (mirrors `run_dev_server.py`)
- Modify: `backend/app/main.py` — call `setup_logging`, add STARTUP/CLEAN SHUTDOWN markers + asyncio exception handler in `lifespan`
- Modify: `backend/bot/main.py` — call `setup_logging`, add STARTUP/CLEAN SHUTDOWN markers around `run_polling()`
- Modify: `backend/run_dev_server.py` — detect unexpected exits (crash) separately from intentional file-change restarts, write a CRASH marker, auto-restart
- Modify: `dev.ps1` — launch the bot via `run_dev_bot.py` instead of `python -m bot.main` directly
- Modify: `docker-compose.yml` — add `restart: unless-stopped` + `LOG_DIR` env var + `./logs:/app/logs` mount to `backend`; add the same env var + mount to `telegram-bot`
- Modify: `backend/tests/conftest.py` — add `test_logging_config` to the `misc` area-marker map

---

## Task 1: Shared logging configuration module

**Files:**
- Create: `backend/app/logging_config.py`
- Test: `backend/tests/unit/test_logging_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_logging_config.py
import logging
import sys

import pytest

from app import logging_config


@pytest.fixture(autouse=True)
def _reset_root_logger():
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_excepthook = sys.excepthook
    yield
    for handler in list(root.handlers):
        if handler not in original_handlers:
            root.removeHandler(handler)
            handler.close()
    sys.excepthook = original_excepthook


def test_setup_logging_creates_log_dir_and_writes_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_config, "LOG_DIR", tmp_path / "logs")

    logging_config.setup_logging("backend.log")
    logging.getLogger("app.test").info("hello from test")

    log_file = tmp_path / "logs" / "backend.log"
    assert log_file.exists()
    assert "hello from test" in log_file.read_text(encoding="utf-8")


def test_setup_logging_reroutes_uvicorn_loggers_through_root(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_config, "LOG_DIR", tmp_path / "logs")
    uv_logger = logging.getLogger("uvicorn.error")
    original_handlers = list(uv_logger.handlers)
    original_propagate = uv_logger.propagate
    uv_logger.addHandler(logging.NullHandler())
    uv_logger.propagate = False
    try:
        logging_config.setup_logging("backend.log")
        assert uv_logger.propagate is True
        assert uv_logger.handlers == []
    finally:
        uv_logger.handlers = original_handlers
        uv_logger.propagate = original_propagate


def test_setup_logging_installs_excepthook(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_config, "LOG_DIR", tmp_path / "logs")

    logging_config.setup_logging("backend.log")

    assert sys.excepthook is logging_config._log_uncaught_exception
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`, with venv activated): `pytest tests/unit/test_logging_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.logging_config'` (or `AttributeError`)

- [ ] **Step 3: Write the implementation**

```python
# backend/app/logging_config.py
"""Shared logging setup for the backend API and the Telegram bot process.

Attaches a rotating file handler (so crashes leave a trail on disk) and a
stdout handler (so the existing dev.ps1 / docker compose logs terminal view
keeps working) to the root logger, reroutes uvicorn's own loggers through
it, and installs a sys.excepthook so an uncaught exception in the main
thread is logged before the process dies.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Native (dev.ps1) runs land here by default: backend/app/logging_config.py
# -> app/ -> backend/ -> <project root>/logs. Docker overrides this via the
# LOG_DIR env var (set to /app/logs in docker-compose.yml) since the
# container's filesystem view starts at backend/, with nothing mounted above
# it.
_DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_DIR = Path(os.environ.get("LOG_DIR", str(_DEFAULT_LOG_DIR)))

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _log_uncaught_exception(exc_type, exc_value, exc_tb) -> None:
    logging.getLogger("uncaught").critical(
        "UNCAUGHT EXCEPTION", exc_info=(exc_type, exc_value, exc_tb)
    )
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def setup_logging(log_filename: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_DIR / log_filename, maxBytes=10_000_000, backupCount=5
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    # uvicorn configures its own loggers with propagate=False and its own
    # StreamHandler before our module is imported. Clear those handlers and
    # let the records bubble to root instead, so uvicorn's request/error
    # logs land in the same file without printing twice to stdout.
    for name in _UVICORN_LOGGER_NAMES:
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True

    sys.excepthook = _log_uncaught_exception
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_logging_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Register the test file's area marker**

In `backend/tests/conftest.py`, add to the `misc` section of `_AREA_MARKERS` (around line 92, after `"test_settings_loader": "misc",`):

```python
    "test_logging_config": "misc",
```

- [ ] **Step 6: Run the full fast suite to confirm nothing else broke**

Run: `pytest -q`
Expected: all tests pass (existing baseline + 3 new)

- [ ] **Step 7: Commit**

```bash
git add backend/app/logging_config.py backend/tests/unit/test_logging_config.py backend/tests/conftest.py
git commit -m "feat: add shared rotating-file logging config"
```

---

## Task 2: Wire logging + crash markers into the backend app

**Files:**
- Modify: `backend/app/main.py:1-50`

- [ ] **Step 1: Add the import and module-level `setup_logging` call**

In `backend/app/main.py`, change the top of the file (lines 1-9) from:

```python
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.email_worker import run_email_worker
```

to:

```python
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.email_worker import run_email_worker
from app.logging_config import setup_logging

setup_logging("backend.log")
logger = logging.getLogger(__name__)
```

This runs once, the first time `app.main` is imported (by uvicorn, or by a test importing `create_app`) — Python caches module bodies, so it won't re-run on subsequent `create_app()` calls within the same process.

- [ ] **Step 2: Add STARTUP/CLEAN SHUTDOWN markers and an asyncio exception handler to `lifespan`**

Change (currently lines 45-54):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_email_worker())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

to:

```python
def _handle_async_exception(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    logging.getLogger("asyncio").critical(
        "UNHANDLED ASYNCIO EXCEPTION: %s",
        context.get("message"),
        exc_info=context.get("exception"),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== STARTUP pid=%d ===", os.getpid())
    asyncio.get_running_loop().set_exception_handler(_handle_async_exception)
    task = asyncio.create_task(run_email_worker())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("=== CLEAN SHUTDOWN ===")
```

- [ ] **Step 3: Run the fast test suite**

Run (from `backend/`): `pytest -q`
Expected: all tests pass — `create_app()`/`TestClient` usage across the suite already exercises `lifespan` on startup/shutdown, so this confirms nothing broke.

- [ ] **Step 4: Manually verify log output**

Run: `python -m uvicorn app.main:app --port 8000` (from `backend/`, venv activated), hit `http://localhost:8000/api/health` (check `app/routes/health.py` for the exact path if different), then Ctrl+C.

Expected: `backend/../logs/backend.log` (i.e. `<project root>/logs/backend.log`) exists and contains lines like:
```
... INFO app.main: === STARTUP pid=12345 ===
... INFO uvicorn.error: Application startup complete.
... INFO uvicorn.access: ... "GET /api/health HTTP/1.1" 200 OK
... INFO app.main: === CLEAN SHUTDOWN ===
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: log backend startup/shutdown markers and route logs to file"
```

---

## Task 3: Wire logging + crash markers into the bot

**Files:**
- Modify: `backend/bot/main.py`

- [ ] **Step 1: Add the import, `setup_logging` call, and STARTUP/CRASH/CLEAN SHUTDOWN markers**

Change `backend/bot/main.py` from:

```python
from __future__ import annotations

import asyncio
import logging

from telegram import Bot
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.settings import get_settings
from bot.handlers import (
    callback_query_handler,
    handle_text_message,
    help_command,
    start,
    status,
    unlink,
    verify,
)
from bot.outbox import poll_outbox

logger = logging.getLogger(__name__)
```

to:

```python
from __future__ import annotations

import asyncio
import logging
import os

from telegram import Bot
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.logging_config import setup_logging
from app.settings import get_settings
from bot.handlers import (
    callback_query_handler,
    handle_text_message,
    help_command,
    start,
    status,
    unlink,
    verify,
)
from bot.outbox import poll_outbox

logger = logging.getLogger(__name__)
```

Then change `main()` from:

```python
def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set; bot not starting")
        return

    app = Application.builder().token(settings.telegram_bot_token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("unlink", unlink))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    app.run_polling()
```

to:

```python
def main() -> None:
    setup_logging("bot.log")
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set; bot not starting")
        return

    app = Application.builder().token(settings.telegram_bot_token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("unlink", unlink))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    logger.info("=== STARTUP pid=%d ===", os.getpid())
    try:
        app.run_polling()
    except Exception:
        logger.critical("=== BOT CRASHED ===", exc_info=True)
        raise
    else:
        logger.info("=== CLEAN SHUTDOWN ===")
```

- [ ] **Step 2: Run the fast test suite**

Run (from `backend/`): `pytest -m notifications -q`
Expected: all pass — confirms `test_bot_actions.py` and friends still import/exercise `bot.*` modules fine.

- [ ] **Step 3: Commit**

```bash
git add backend/bot/main.py
git commit -m "feat: log bot startup/crash/shutdown markers and route logs to file"
```

---

## Task 4: Crash detection + auto-restart for the backend in `dev.ps1`

**Files:**
- Modify: `backend/run_dev_server.py`

- [ ] **Step 1: Add imports and crash-marker writer**

At the top of `backend/run_dev_server.py`, change:

```python
import subprocess
import sys
import signal
import atexit
import datetime
import time
import threading
```

to:

```python
import subprocess
import sys
import signal
import atexit
import datetime
import time
import threading
from pathlib import Path
```

After the `WATCH_DIR = "."` line, add:

```python
# backend/run_dev_server.py -> backend/ -> <project root>/logs
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CRASH_LOG = LOG_DIR / "backend.log"


def write_crash_marker(exit_code: int | None) -> None:
    ts = datetime.datetime.now().isoformat()
    with open(CRASH_LOG, "a", encoding="utf-8") as f:
        f.write(f"{ts} CRITICAL run_dev_server: === CRASH DETECTED exit_code={exit_code}, restarting ===\n")
```

- [ ] **Step 2: Add restart-coordination state**

Change the `# ── State ──` section from:

```python
proc: "subprocess.Popen[bytes] | None" = None
stop_event = threading.Event()
```

to:

```python
proc: "subprocess.Popen[bytes] | None" = None
stop_event = threading.Event()
restart_lock = threading.Lock()
expected_exit = threading.Event()  # set while we intentionally stop/restart proc
```

- [ ] **Step 3: Mark intentional restarts as "expected" in `shutdown()`**

Change:

```python
def shutdown(signum=None, frame=None) -> None:
    log(f"Shutdown signal received (signum={signum})")
    stop_event.set()
    stop_server()
    sys.exit(0)
```

to:

```python
def shutdown(signum=None, frame=None) -> None:
    log(f"Shutdown signal received (signum={signum})")
    stop_event.set()
    with restart_lock:
        expected_exit.set()
        stop_server()
    sys.exit(0)
```

- [ ] **Step 4: Replace the watch/run loop at the bottom of the file with a watcher thread + crash monitor**

Change the `# ── Main loop ──` section at the bottom from:

```python
start_server()

if not HAS_WATCHFILES:
    log("watchfiles not installed — running without hot reload; install it with: pip install watchfiles")
    try:
        proc.wait()  # type: ignore[union-attr]
    except KeyboardInterrupt:
        shutdown()
else:
    log(f"Watching {WATCH_DIR!r} for .py changes (watchfiles {__import__('watchfiles').__version__})")
    try:
        for changes in watch(WATCH_DIR, watch_filter=PythonFilter(), stop_event=stop_event):
            if stop_event.is_set():
                break
            changed_files = sorted({str(p) for _, p in changes})
            log(f"Detected changes: {changed_files}")
            stop_server()
            time.sleep(0.15)   # brief pause so the OS releases port 8000
            start_server()
    except KeyboardInterrupt:
        shutdown()
    except Exception as exc:
        log(f"Watcher error: {exc}")
        shutdown()
```

to:

```python
def watch_loop() -> None:
    try:
        for changes in watch(WATCH_DIR, watch_filter=PythonFilter(), stop_event=stop_event):
            if stop_event.is_set():
                break
            changed_files = sorted({str(p) for _, p in changes})
            log(f"Detected changes: {changed_files}")
            with restart_lock:
                expected_exit.set()
                stop_server()
                time.sleep(0.15)   # brief pause so the OS releases port 8000
                start_server()
                expected_exit.clear()
    except Exception as exc:
        log(f"Watcher error: {exc}")


def crash_monitor() -> None:
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
            with restart_lock:
                if proc is not None and proc.poll() is not None and not expected_exit.is_set():
                    code = proc.returncode
                    log(f"CRASH detected: uvicorn exited unexpectedly (exit_code={code})")
                    write_crash_marker(code)
                    time.sleep(1)
                    start_server()
    except KeyboardInterrupt:
        shutdown()


start_server()

if not HAS_WATCHFILES:
    log("watchfiles not installed — running without hot reload; install it with: pip install watchfiles")
else:
    log(f"Watching {WATCH_DIR!r} for .py changes (watchfiles {__import__('watchfiles').__version__})")
    threading.Thread(target=watch_loop, daemon=True).start()

crash_monitor()
```

- [ ] **Step 5: Manually verify hot reload still works**

Run (from `backend/`): `python run_dev_server.py`, then in another terminal touch a `.py` file under `app/` (e.g. add a blank line and save).

Expected: log shows `Detected changes: [...]`, server restarts cleanly, no CRASH marker written to `logs/backend.log`.

- [ ] **Step 6: Manually verify crash detection + auto-restart**

With `run_dev_server.py` still running from Step 5, find the uvicorn child pid from the `Uvicorn started: pid=<pid>` log line and kill it directly (not the supervisor): `taskkill /F /PID <pid>` (PowerShell) or `kill -9 <pid>` (Bash).

Expected: within ~1.5s, `run_dev_server.py`'s terminal output shows `CRASH detected: uvicorn exited unexpectedly (exit_code=...)` and a new `Uvicorn started: pid=<new pid>` line; `logs/backend.log` contains a `=== CRASH DETECTED ... ===` line.

- [ ] **Step 7: Commit**

```bash
git add backend/run_dev_server.py
git commit -m "feat: detect backend crashes in dev.ps1 supervisor and auto-restart"
```

---

## Task 5: Crash detection + auto-restart for the bot in `dev.ps1`

**Files:**
- Create: `backend/run_dev_bot.py`
- Modify: `dev.ps1:123-126`

- [ ] **Step 1: Create the bot supervisor script**

```python
# backend/run_dev_bot.py
"""
Development bot launcher with crash detection and auto-restart.

`python -m bot.main` has no hot-reload (unlike the backend, which manages
its own watcher in run_dev_server.py); this wrapper exists purely so a bot
crash is visible in logs/bot.log and the bot comes back up automatically,
matching the backend's behavior.
"""
import subprocess
import sys
import signal
import atexit
import datetime
import time
from pathlib import Path

CMD = [sys.executable, "-m", "bot.main"]

# backend/run_dev_bot.py -> backend/ -> <project root>/logs
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CRASH_LOG = LOG_DIR / "bot.log"

proc: "subprocess.Popen[bytes] | None" = None
stop_event = False


def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")
    print(f"[dev-bot] [{ts}] {msg}", flush=True)


def write_crash_marker(exit_code: int | None) -> None:
    ts = datetime.datetime.now().isoformat()
    with open(CRASH_LOG, "a", encoding="utf-8") as f:
        f.write(f"{ts} CRITICAL run_dev_bot: === CRASH DETECTED exit_code={exit_code}, restarting ===\n")


def start_bot() -> None:
    global proc
    log(f"Starting bot: {' '.join(CMD)}")
    proc = subprocess.Popen(CMD)
    log(f"Bot started: pid={proc.pid}")


def stop_bot() -> None:
    global proc
    if proc is None or proc.poll() is not None:
        return
    log(f"Stopping bot pid={proc.pid}")
    proc.terminate()
    try:
        proc.wait(timeout=5)
        log(f"Bot stopped (exit={proc.returncode})")
    except subprocess.TimeoutExpired:
        log("Bot did not stop in time, killing")
        proc.kill()
        proc.wait()
    proc = None


def shutdown(signum=None, frame=None) -> None:
    global stop_event
    log(f"Shutdown signal received (signum={signum})")
    stop_event = True
    stop_bot()
    sys.exit(0)


@atexit.register
def _on_exit() -> None:
    stop_bot()


signal.signal(signal.SIGTERM, shutdown)
try:
    signal.signal(signal.SIGBREAK, shutdown)   # Windows Ctrl+Break
except AttributeError:
    pass                                        # not on Windows


start_bot()
try:
    while not stop_event:
        time.sleep(0.5)
        if proc is not None and proc.poll() is not None:
            code = proc.returncode
            log(f"CRASH detected: bot exited unexpectedly (exit_code={code})")
            write_crash_marker(code)
            time.sleep(1)
            start_bot()
except KeyboardInterrupt:
    shutdown()
```

- [ ] **Step 2: Point `dev.ps1` at the new supervisor**

In `dev.ps1`, change (around line 123-126):

```powershell
if (-not $NoBot) {
    $names.Add("bot");  $colors.Add("magenta")
    $cmds.Add("cd /d `"$root\backend`" && `"$venvPy`" -m bot.main")
}
```

to:

```powershell
if (-not $NoBot) {
    $names.Add("bot");  $colors.Add("magenta")
    $cmds.Add("cd /d `"$root\backend`" && `"$venvPy`" run_dev_bot.py")
}
```

- [ ] **Step 3: Manually verify**

Run `.\dev.ps1` (requires a valid `TELEGRAM_BOT_TOKEN` in `.env` to actually start polling — if you don't have one, skip to Task 6 and rely on the docker-compose verification instead, since the bot would just log the "not starting" warning and exit 0 here, which `run_dev_bot.py` would interpret as a normal exit and not restart). With a valid token: find the bot's child pid from the `[bot]` prefixed `Bot started: pid=<pid>` line, kill it directly.

Expected: `[bot]` output shows `CRASH detected: bot exited unexpectedly (...)` and a new `Bot started: pid=<new pid>` line; `logs/bot.log` contains a `=== CRASH DETECTED ... ===` line.

- [ ] **Step 4: Commit**

```bash
git add backend/run_dev_bot.py dev.ps1
git commit -m "feat: add crash-detecting supervisor for the bot in dev.ps1"
```

---

## Task 6: docker-compose — persist logs outside the container, auto-restart on crash

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Update the `backend` service**

Change:

```yaml
  backend:
    build:
      context: ./backend
      args:
        PIP_INDEX_URL: ${PIP_INDEX_URL:-https://pypi.org/simple/}
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./backend:/app
    command: >
      sh -c "alembic upgrade head &&
             uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
```

to:

```yaml
  backend:
    build:
      context: ./backend
      args:
        PIP_INDEX_URL: ${PIP_INDEX_URL:-https://pypi.org/simple/}
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      - LOG_DIR=/app/logs
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./backend:/app
      - ./logs:/app/logs
    command: >
      sh -c "alembic upgrade head &&
             uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
```

- [ ] **Step 2: Update the `telegram-bot` service**

Change:

```yaml
  telegram-bot:
    build:
      context: ./backend
      args:
        PIP_INDEX_URL: ${PIP_INDEX_URL:-https://pypi.org/simple/}
    command: watchfiles --filter python 'python -m bot.main' app/ bot/
    env_file: .env
    volumes:
      - ./backend:/app
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
```

to:

```yaml
  telegram-bot:
    build:
      context: ./backend
      args:
        PIP_INDEX_URL: ${PIP_INDEX_URL:-https://pypi.org/simple/}
    command: watchfiles --filter python 'python -m bot.main' app/ bot/
    env_file: .env
    environment:
      - LOG_DIR=/app/logs
    volumes:
      - ./backend:/app
      - ./logs:/app/logs
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
```

- [ ] **Step 3: Manually verify the mount and rotation work**

Run: `docker compose up -d backend` (from project root; stop any native `dev.ps1` stack first so port 8000 is free), then `curl http://localhost:8000/api/health` (or open it in a browser), then check the host file.

Expected: `./logs/backend.log` on the host (project root, not `backend/logs`) exists and contains the STARTUP marker and the health-check request line.

- [ ] **Step 4: Manually verify auto-restart on crash**

With the backend container running from Step 3: `docker compose exec backend sh -c "kill -9 1"` (kills the container's PID 1, which is the uvicorn process started by the `sh -c "... uvicorn ..."` command).

Expected: `docker compose ps backend` shows the container restarting/running again shortly after (Docker's `restart: unless-stopped` policy); `./logs/backend.log` shows a new `=== STARTUP ===` line after the kill, though note this path doesn't go through a Python-level CRASH marker (the whole container died, not just the Python process) — the absence of a `=== CLEAN SHUTDOWN ===` line before the new `=== STARTUP ===` is the crash signal here, consistent with the design.

- [ ] **Step 5: Bring the stack down cleanly and commit**

```bash
docker compose down
git add docker-compose.yml
git commit -m "feat: persist backend/bot logs outside the container and auto-restart on crash"
```

---

## Task 7: Final full-suite check

- [ ] **Step 1: Run the fast backend suite**

Run (from `backend/`): `pytest -q`
Expected: all tests pass.

- [ ] **Step 2: Run frontend lint/tests if touched** — skip, no frontend files changed in this plan.

- [ ] **Step 3: Confirm `git status` is clean**

Run: `git status`
Expected: working tree clean, all changes committed across Tasks 1-6.
