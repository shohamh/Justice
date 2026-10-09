const GUARD_KEY = "chunk-reload-at";
const GUARD_WINDOW_MS = 60_000;

/**
 * After a deploy, a stale tab may request a deleted hashed chunk. Vite fires
 * `vite:preloadError`; reload once to pick up the new build instead of letting
 * the error reach the ErrorBoundary. A timestamp guard prevents reload loops.
 */
export function installChunkLoadRecovery(win: Window = window): void {
  win.addEventListener("vite:preloadError", (event) => {
    event.preventDefault();
    const now = Date.now();
    let last = 0;
    try {
      last = Number(win.sessionStorage.getItem(GUARD_KEY)) || 0;
    } catch {
      // storage unavailable: fall through and reload once
    }
    if (now - last < GUARD_WINDOW_MS) return;
    try {
      win.sessionStorage.setItem(GUARD_KEY, String(now));
    } catch {
      // ignore
    }
    win.location.reload();
  });
}
