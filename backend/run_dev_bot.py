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
    # Appends to the same logs/bot.log that the bot process's own RotatingFileHandler
    # (app/logging_config.py, running inside the bot — a separate OS process) writes/rotates.
    # No file locking between the two writers; accepted tradeoff since this script is
    # dev-only (never used in Docker/production, just the native dev.ps1 workflow).
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
            if code == 0:
                # A clean exit (code 0) means bot.main() deliberately returned early
                # (e.g. TELEGRAM_BOT_TOKEN not configured) rather than crashed — restarting
                # forever in that case would just spam false CRASH markers. Stop supervising.
                log("Bot exited cleanly (exit_code=0) — not restarting. Check TELEGRAM_BOT_TOKEN if this is unexpected.")
                break
            log(f"CRASH detected: bot exited unexpectedly (exit_code={code})")
            write_crash_marker(code)
            time.sleep(1)
            start_bot()
except KeyboardInterrupt:
    shutdown()
