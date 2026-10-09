const GUARD_KEY = "chunk-reload-at";
const GUARD_WINDOW_MS = 60_000;

type Marker = { read: () => number; write: (now: number) => void };

// Preferred: sessionStorage. If it is unavailable (private mode / blocked),
// fall back to window.history.state, which also survives a reload.
function getMarker(win: Window): Marker | null {
  try {
    const storage = win.sessionStorage;
    storage.getItem(GUARD_KEY);
    return {
      read: () => Number(storage.getItem(GUARD_KEY)) || 0,
      write: (now) => storage.setItem(GUARD_KEY, String(now)),
    };
  } catch {
    // fall through to history.state
  }
  try {
    const history = win.history;
    void history.state;
    return {
      read: () => Number((history.state as { chunkReloadAt?: number } | null)?.chunkReloadAt) || 0,
      write: (now) =>
        history.replaceState({ ...((history.state as object | null) ?? {}), chunkReloadAt: now }, ""),
    };
  } catch {
    return null;
  }
}

/**
 * After a deploy, a stale tab may request a deleted hashed chunk. Vite fires
 * `vite:preloadError`; reload once to pick up the new build instead of letting
 * the error reach the ErrorBoundary. A timestamp guard prevents reload loops.
 * If no reload marker can be read and written, we do not reload automatically
 * and let the error surface.
 */
export function installChunkLoadRecovery(win: Window = window): void {
  win.addEventListener("vite:preloadError", (event) => {
    const marker = getMarker(win);
    if (!marker) return;
    const now = Date.now();
    try {
      if (now - marker.read() < GUARD_WINDOW_MS) return; // already reloaded recently
      marker.write(now);
    } catch {
      return; // cannot record the reload, so do not risk a loop
    }
    event.preventDefault();
    win.location.reload();
  });
}
