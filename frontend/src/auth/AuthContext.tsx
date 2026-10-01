import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, ReactNode } from "react";

import { changePassword as apiChangePassword, fetchMe, login as apiLogin, logout as apiLogout, Me } from "../api/auth";
import { api, setAccessToken } from "../api/client";

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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authScopeReady, setAuthScopeReady] = useState(false);
  const authGeneration = useRef(0);
  const scopeTransitioning = useRef(true);
  const hasUser = user !== null;

  useEffect(() => {
    const generation = ++authGeneration.current;
    api.post<{ access_token: string }>("/auth/refresh")
      .then(async (r) => {
        if (generation !== authGeneration.current) return;
        setAccessToken(r.data.access_token);
        const nextUser = await fetchMe();
        if (generation !== authGeneration.current) return;
        setUser(nextUser);
        setAuthScopeReady(true);
        scopeTransitioning.current = false;
      })
      .catch(() => {
        if (generation !== authGeneration.current) return;
        setUser(null);
        setAuthScopeReady(false);
        scopeTransitioning.current = false;
      })
      .finally(() => {
        if (generation === authGeneration.current) setAuthLoading(false);
      });
  }, []);

  useEffect(() => {
    const handler = () => {
      authGeneration.current += 1;
      setAuthLoading(false);
      scopeTransitioning.current = false;
      setAccessToken(null);
      setUser(null);
      setAuthScopeReady(false);
    };
    window.addEventListener("auth:session-expired", handler);
    return () => window.removeEventListener("auth:session-expired", handler);
  }, []);

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
  }, [hasUser]);

  const login = useCallback(async (personal_number: string, password: string, remember_me = false) => {
    const generation = ++authGeneration.current;
    setAuthLoading(false);
    scopeTransitioning.current = true;
    let tokenChanged = false;
    try {
      const r = await apiLogin(personal_number, password, remember_me);
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
  }, []);

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
  }, []);

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
  }, []);

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
  }, []);

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
  }, []);

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
