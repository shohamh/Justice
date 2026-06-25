"""
Development server launcher with self-managed hot reload.

Instead of relying on uvicorn --reload (which uses CTRL_BREAK_EVENT on Windows
and kills the entire concurrently process tree), we:
  1. Start uvicorn WITHOUT --reload
  2. Watch for .py file changes via the watchfiles Python API
  3. Restart uvicorn by calling proc.terminate() + Popen() ourselves

proc.terminate() on Windows = targeted TerminateProcess(pid) — it does NOT
broadcast a console control event, so node/concurrently/PowerShell are unaffected.
"""
import subprocess
import sys
import signal
import atexit
import datetime
import time
import threading
from pathlib import Path

try:
    from watchfiles import watch, PythonFilter  # type: ignore[import]
    HAS_WATCHFILES = True
except ImportError:
    HAS_WATCHFILES = False

# ── Configuration ─────────────────────────────────────────────────────────────

CMD = [
    sys.executable, "-m", "uvicorn",
    "app.main:app",
    "--host", "0.0.0.0",
    "--port", "8000",
    # No --reload here! We manage restarts ourselves.
]

WATCH_DIR = "."   # watch relative to CWD (backend/)

# backend/run_dev_server.py -> backend/ -> <project root>/logs
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CRASH_LOG = LOG_DIR / "backend.log"


def write_crash_marker(exit_code: int | None) -> None:
    # Appends to the same logs/backend.log that the app process's RotatingFileHandler
    # (app/logging_config.py, running inside uvicorn — a separate OS process) writes/rotates.
    # No file locking between the two writers; accepted tradeoff since this script is
    # dev-only (never used in Docker/production, just the native dev.ps1 workflow).
    ts = datetime.datetime.now().isoformat()
    with open(CRASH_LOG, "a", encoding="utf-8") as f:
        f.write(f"{ts} CRITICAL run_dev_server: === CRASH DETECTED exit_code={exit_code}, restarting ===\n")

# ── State ─────────────────────────────────────────────────────────────────────

proc: "subprocess.Popen[bytes] | None" = None
stop_event = threading.Event()
restart_lock = threading.Lock()
expected_exit = threading.Event()  # set while we intentionally stop/restart proc


def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")
    print(f"[dev] [{ts}] {msg}", flush=True)


# ── Uvicorn lifecycle ─────────────────────────────────────────────────────────

def start_server() -> None:
    global proc
    log(f"Starting uvicorn: {' '.join(CMD)}")
    proc = subprocess.Popen(CMD)
    log(f"Uvicorn started: pid={proc.pid}")


def stop_server() -> None:
    global proc
    if proc is None or proc.poll() is not None:
        return
    log(f"Stopping uvicorn pid={proc.pid}")
    proc.terminate()
    try:
        proc.wait(timeout=5)
        log(f"Uvicorn stopped (exit={proc.returncode})")
    except subprocess.TimeoutExpired:
        log("Uvicorn did not stop in time, killing")
        proc.kill()
        proc.wait()
    proc = None


# ── Signal / atexit handling ──────────────────────────────────────────────────

def shutdown(signum=None, frame=None) -> None:
    log(f"Shutdown signal received (signum={signum})")
    stop_event.set()
    with restart_lock:
        expected_exit.set()
        stop_server()
    sys.exit(0)


@atexit.register
def _on_exit() -> None:
    stop_server()


signal.signal(signal.SIGTERM, shutdown)
try:
    signal.signal(signal.SIGBREAK, shutdown)   # Windows Ctrl+Break
except AttributeError:
    pass                                        # not on Windows


# ── Main loop ─────────────────────────────────────────────────────────────────

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
                # expected_exit distinguishes a deliberate stop/restart (watch_loop or
                # shutdown()) from an actual uvicorn crash — without it, every normal
                # reload would falsely trigger a crash-marker write.
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
