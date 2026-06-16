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

# ── State ─────────────────────────────────────────────────────────────────────

proc: "subprocess.Popen[bytes] | None" = None
stop_event = threading.Event()


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
