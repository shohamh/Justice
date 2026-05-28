import { createContext, useCallback, useContext, useMemo, useState, ReactNode } from "react";

import { changePassword as apiChangePassword, fetchMe, login as apiLogin, logout as apiLogout, Me } from "../api/auth";
import { setAccessToken } from "../api/client";

interface AuthContextValue {
  user: Me | null;
  loggedIn: boolean;
  mustChangePassword: boolean;
  login: (personal_number: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  changePassword: (current: string, next: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);

  const login = useCallback(async (personal_number: string, password: string) => {
    const r = await apiLogin(personal_number, password);
    setAccessToken(r.access_token);
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

  const value = useMemo<AuthContextValue>(
    () => ({ user, loggedIn: user !== null, mustChangePassword: user?.must_change_password ?? false, login, logout, changePassword }),
    [user, login, logout, changePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth used outside AuthProvider");
  return ctx;
}
