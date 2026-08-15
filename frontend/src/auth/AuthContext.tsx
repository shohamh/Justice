import { createContext, useCallback, useContext, useEffect, useMemo, useState, ReactNode } from "react";

import { changePassword as apiChangePassword, fetchMe, login as apiLogin, logout as apiLogout, Me } from "../api/auth";
import { api, setAccessToken } from "../api/client";

interface AuthContextValue {
  user: Me | null;
  loggedIn: boolean;
  authLoading: boolean;
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
  const hasUser = user !== null;

  useEffect(() => {
    api.post<{ access_token: string }>("/auth/refresh")
      .then((r) => { setAccessToken(r.data.access_token); return fetchMe(); })
      .then(setUser)
      .catch(() => {})
      .finally(() => setAuthLoading(false));
  }, []);

  useEffect(() => {
    const handler = () => { setAccessToken(null); setUser(null); };
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
    const interval = setInterval(() => { fetchMe().then(setUser).catch(() => {}); }, 60000);
    return () => clearInterval(interval);
  }, [hasUser]);

  const login = useCallback(async (personal_number: string, password: string, remember_me = false) => {
    const r = await apiLogin(personal_number, password, remember_me);
    setAccessToken(r.access_token);
    setUser(await fetchMe());
  }, []);

  const loginWithToken = useCallback(async (token: string) => {
    setAccessToken(token);
    setUser(await fetchMe());
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setAccessToken(null);
      setUser(null);
    }
  }, []);

  const changePassword = useCallback(async (current: string, next: string) => {
    await apiChangePassword(current, next);
    setUser(await fetchMe());
  }, []);

  const refreshMe = useCallback(async () => {
    setUser(await fetchMe());
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loggedIn: user !== null,
      authLoading,
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
    [user, authLoading, login, loginWithToken, logout, changePassword, refreshMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth used outside AuthProvider");
  return ctx;
}
