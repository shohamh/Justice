import { createContext, useCallback, useContext, useMemo, useState, ReactNode } from "react";

import { login as apiLogin, logout as apiLogout, LoginResponse } from "../api/auth";
import { setAccessToken } from "../api/client";

interface AuthState {
  loggedIn: boolean;
  mustChangePassword: boolean;
}

interface AuthContextValue extends AuthState {
  login: (personal_number: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ loggedIn: false, mustChangePassword: false });

  const login = useCallback(async (personal_number: string, password: string) => {
    const r: LoginResponse = await apiLogin(personal_number, password);
    setAccessToken(r.access_token);
    setState({ loggedIn: true, mustChangePassword: r.must_change_password });
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setAccessToken(null);
      setState({ loggedIn: false, mustChangePassword: false });
    }
  }, []);

  const value = useMemo(() => ({ ...state, login, logout }), [state, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth used outside AuthProvider");
  return ctx;
}
