import { createContext, useCallback, useContext, useEffect, useMemo, useState, ReactNode } from "react";

import { updateThemePreference, ThemePreference } from "../api/theme";
import { useAuth } from "../auth/AuthContext";

const STORAGE_KEY = "theme";
const ORDER: ThemePreference[] = ["light", "dark", "system"];

function resolveSystemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyThemeClass(theme: ThemePreference) {
  const isDark = theme === "dark" || (theme === "system" && resolveSystemPrefersDark());
  document.documentElement.classList.toggle("dark", isDark);
}

interface ThemeContextValue {
  theme: ThemePreference;
  resolvedTheme: "light" | "dark";
  cycleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [theme, setThemeState] = useState<ThemePreference>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark" || stored === "system" ? stored : "system";
  });

  const setTheme = useCallback((next: ThemePreference, sync: boolean) => {
    setThemeState(next);
    localStorage.setItem(STORAGE_KEY, next);
    applyThemeClass(next);
    if (sync) {
      updateThemePreference(next).catch(() => {
        // Optimistic: choice already persisted locally for this device;
        // a failed sync just means it isn't saved to the profile yet.
      });
    }
  }, []);

  // Adopt the profile's value once known — it's authoritative once loaded;
  // localStorage only bridges the pre-auth/first-paint moment.
  useEffect(() => {
    if (user && user.theme_preference !== theme) {
      setTheme(user.theme_preference, false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.theme_preference]);

  // Live-follow OS changes while in "system" mode.
  useEffect(() => {
    if (theme !== "system") return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => applyThemeClass("system");
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [theme]);

  const cycleTheme = useCallback(() => {
    const next = ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length];
    setTheme(next, true);
  }, [theme, setTheme]);

  const resolvedTheme: "light" | "dark" = useMemo(
    () => (theme === "dark" || (theme === "system" && resolveSystemPrefersDark()) ? "dark" : "light"),
    [theme],
  );

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, resolvedTheme, cycleTheme }),
    [theme, resolvedTheme, cycleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme used outside ThemeProvider");
  return ctx;
}
