import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, ReactNode } from "react";

import { changePassword as apiChangePassword, fetchMe, login as apiLogin, logout as apiLogout, Me } from "../api/auth";
import { RefreshTimeoutError, refreshAccessToken, setAccessToken, StaleRefreshError } from "../api/client";

export interface AuthContextValue {
  user: Me | null;
  loggedIn: boolean;
  authLoading: boolean;
  authScopeReady: boolean;
  mustChangePassword: boolean;
  telegramLinked: boolean;
  telegramRequired: boolean;
  enrollmentPending: boolean;
  login: (personal_number: string, password: string, remember_me?: boolean) => Promise<void>;
  loginWithToken: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  changePassword: (current: string, next: string) => Promise<void>;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const RESTORE_MAX_ATTEMPTS = 4;
const RESTORE_RETRY_DELAY_MS = 400;

/**
 * Restores the session from the refresh cookie on mount. Only a definite client-side
 * answer (401/403 etc.) means "no session"; a transient failure (network error, proxy
 * 5xx/429 while the backend is slow or restarting) is retried briefly instead of
 * silently logging the user out and bouncing them to /login on a full page reload.
 * A refresh timeout is not retried (see below).
 */
async function restoreSession(): Promise<Me | null> {
  for (let attempt = 1; ; attempt++) {
    try {
      // Shared with the 401 handler in the API client, so requests that start
      // while the session is being restored wait for this refresh instead of
      // starting their own.
      await refreshAccessToken();
      return await fetchMe();
    } catch (err) {
      // Login/logout replaced the token mid-restore; the generation check discards this result.
      if (err instanceof StaleRefreshError) return null;
      // The refresh already waited REFRESH_TIMEOUT_MS with no answer; retrying would
      // keep the app on its loading screen for a minute. Fall into "not logged in".
      if (err instanceof RefreshTimeoutError) return null;
      const status = (err as { response?: { status?: number } })?.response?.status;
      const transient = status === undefined || status >= 500 || status === 429;
      if (!transient || attempt >= RESTORE_MAX_ATTEMPTS) return null;
      await new Promise((resolve) => setTimeout(resolve, RESTORE_RETRY_DELAY_MS * attempt));
    }
  }
}

/** The provider may be mounted without a QueryClient (unit tests); then there is no cache to clear. */
function useOptionalQueryClient(): QueryClient | null {
  try {
    // eslint-disable-next-line react-hooks/rules-of-hooks -- useQueryClient is a plain context read; it throws without a provider
    return useQueryClient();
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useOptionalQueryClient();
  const [user, setUserState] = useState<Me | null>(null);
  const userIdRef = useRef<string | null>(null);
  // Cached query data belongs to one identity: drop it on logout and when a
  // different user signs in. Refreshing the same user keeps the cache.
  const setUser = useCallback((next: Me | null) => {
    const previousId = userIdRef.current;
    const nextId = next?.id ?? null;
    if (previousId !== null && previousId !== nextId) queryClient?.clear();
    userIdRef.current = nextId;
    setUserState(next);
  }, [queryClient]);
  const [authLoading, setAuthLoading] = useState(true);
  const [authScopeReady, setAuthScopeReady] = useState(false);
  const authGeneration = useRef(0);
  // Generation of a login whose credentials are still with the server (no token of
  // its own installed yet); null otherwise.
  const loginAwaitingToken = useRef<number | null>(null);
  const scopeTransitioning = useRef(true);
  const hasUser = user !== null;

  useEffect(() => {
    const generation = ++authGeneration.current;
    restoreSession()
      .then((nextUser) => {
        if (generation !== authGeneration.current) return;
        setUser(nextUser);
        setAuthScopeReady(nextUser !== null);
        scopeTransitioning.current = false;
      })
      .finally(() => {
        if (generation === authGeneration.current) setAuthLoading(false);
      });
  }, [setUser]);

  useEffect(() => {
    const handler = () => {
      // While signed out, a login waiting for its token makes this event moot: it
      // comes from an anonymous request (e.g. a startup request that waited on the
      // session restore, went out without a token and 401'd). Handling it would bump
      // the generation and silently drop the login's result. A login that installed
      // its token is no longer "awaiting", and a signed-in user is always handled.
      if (
        userIdRef.current === null
        && loginAwaitingToken.current !== null
        && loginAwaitingToken.current === authGeneration.current
      ) return;
      authGeneration.current += 1;
      setAuthLoading(false);
      scopeTransitioning.current = false;
      setAccessToken(null);
      setUser(null);
      setAuthScopeReady(false);
    };
    window.addEventListener("auth:session-expired", handler);
    return () => window.removeEventListener("auth:session-expired", handler);
  }, [setUser]);

  // `user` is otherwise only refreshed on login/mount — any server-side change to
  // this soldier's own record (enrollment approved, a profile field-update request
  // approved by a commander/duty manager, etc.) would stay stale for the rest of
  // the session with no way to pick it up short of logging out and back in. Poll
  // periodically so pages reading `user` (enrollment gates, last-range-date
  // banners, profile display) reflect approvals without requiring a re-login.
  useEffect(() => {
    if (!hasUser) return;
    const interval = setInterval(() => {
      if (scopeTransitioning.current) return;
      const generation = ++authGeneration.current;
      fetchMe().then((nextUser) => {
        if (generation !== authGeneration.current) return;
        setUser(nextUser);
        setAuthScopeReady(true);
      }).catch(() => {});
    }, 60000);
    return () => clearInterval(interval);
  }, [hasUser, setUser]);

  const login = useCallback(async (personal_number: string, password: string, remember_me = true) => {
    const generation = ++authGeneration.current;
    setAuthLoading(false);
    scopeTransitioning.current = true;
    let tokenChanged = false;
    loginAwaitingToken.current = generation;
    try {
      let r: Awaited<ReturnType<typeof apiLogin>>;
      try {
        r = await apiLogin(personal_number, password, remember_me);
      } finally {
        if (loginAwaitingToken.current === generation) loginAwaitingToken.current = null;
      }
      if (generation !== authGeneration.current) return;
      setAuthScopeReady(false);
      setAccessToken(r.access_token);
      tokenChanged = true;
      const nextUser = await fetchMe();
      if (generation !== authGeneration.current) return;
      setUser(nextUser);
      setAuthScopeReady(true);
      scopeTransitioning.current = false;
    } catch (error) {
      if (generation === authGeneration.current) {
        scopeTransitioning.current = false;
        if (tokenChanged) setAuthScopeReady(false);
      }
      throw error;
    }
  }, [setUser]);

  const loginWithToken = useCallback(async (token: string) => {
    const generation = ++authGeneration.current;
    setAuthLoading(false);
    scopeTransitioning.current = true;
    setAuthScopeReady(false);
    setAccessToken(token);
    try {
      const nextUser = await fetchMe();
      if (generation !== authGeneration.current) return;
      setUser(nextUser);
      setAuthScopeReady(true);
      scopeTransitioning.current = false;
    } catch (error) {
      if (generation === authGeneration.current) {
        setAuthScopeReady(false);
        scopeTransitioning.current = false;
      }
      throw error;
    }
  }, [setUser]);

  const logout = useCallback(async () => {
    const generation = ++authGeneration.current;
    setAuthLoading(false);
    scopeTransitioning.current = true;
    setAuthScopeReady(false);
    try {
      await apiLogout();
    } finally {
      if (generation === authGeneration.current) {
        setAccessToken(null);
        setUser(null);
        scopeTransitioning.current = false;
      }
    }
  }, [setUser]);

  const changePassword = useCallback(async (current: string, next: string) => {
    const generation = ++authGeneration.current;
    setAuthLoading(false);
    scopeTransitioning.current = true;
    let passwordChanged = false;
    try {
      await apiChangePassword(current, next);
      if (generation !== authGeneration.current) return;
      passwordChanged = true;
      setAuthScopeReady(false);
      const nextUser = await fetchMe();
      if (generation !== authGeneration.current) return;
      setUser(nextUser);
      setAuthScopeReady(true);
      scopeTransitioning.current = false;
    } catch (error) {
      if (generation === authGeneration.current) {
        scopeTransitioning.current = false;
        if (passwordChanged) setAuthScopeReady(false);
      }
      throw error;
    }
  }, [setUser]);

  const refreshMe = useCallback(async () => {
    const generation = ++authGeneration.current;
    setAuthLoading(false);
    scopeTransitioning.current = true;
    setAuthScopeReady(false);
    try {
      const nextUser = await fetchMe();
      if (generation !== authGeneration.current) return;
      setUser(nextUser);
      setAuthScopeReady(true);
      scopeTransitioning.current = false;
    } catch (error) {
      if (generation === authGeneration.current) {
        setAuthScopeReady(false);
        scopeTransitioning.current = false;
      }
      throw error;
    }
  }, [setUser]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loggedIn: user !== null,
      authLoading,
      authScopeReady,
      mustChangePassword: user?.must_change_password ?? false,
      telegramLinked: user?.telegram_linked ?? false,
      telegramRequired: user?.telegram_required ?? false,
      enrollmentPending: user?.enrollment_pending ?? false,
      login,
      loginWithToken,
      logout,
      changePassword,
      refreshMe,
    }),
    [user, authLoading, authScopeReady, login, loginWithToken, logout, changePassword, refreshMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth used outside AuthProvider");
  return ctx;
}
