import { safeInternalReturnPath } from "./returnPath";

export const AUTH_RETURN_PATH_STORAGE_KEY = "justice.auth.return-to";

/** Store a validated same-origin return path for the current browser tab. */
export function storeAuthReturnPath(candidate: unknown): void {
  try {
    const storage = window.sessionStorage;
    const target = safeInternalReturnPath(candidate);
    if (target) storage.setItem(AUTH_RETURN_PATH_STORAGE_KEY, target);
    else storage.removeItem(AUTH_RETURN_PATH_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in restricted browser contexts; login must still work.
  }
}

/** Read a return path without consuming it so password login can retain an SSO target. */
export function readAuthReturnPath(): string | null {
  try {
    return safeInternalReturnPath(window.sessionStorage.getItem(AUTH_RETURN_PATH_STORAGE_KEY));
  } catch {
    return null;
  }
}

/** Consume a validated target once app gates are open; invalid values are discarded. */
export function consumeAuthReturnPath(): string | null {
  try {
    const storage = window.sessionStorage;
    const target = safeInternalReturnPath(storage.getItem(AUTH_RETURN_PATH_STORAGE_KEY));
    storage.removeItem(AUTH_RETURN_PATH_STORAGE_KEY);
    return target;
  } catch {
    return null;
  }
}
