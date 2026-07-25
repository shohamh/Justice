import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

export interface NavHistoryEntry {
  path: string;
  timestamp: string;
}

const MAX_ENTRIES = 15;

interface NavigationHistoryContextValue {
  history: NavHistoryEntry[];
}

const NavigationHistoryContext = createContext<NavigationHistoryContextValue | null>(null);

export function NavigationHistoryProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [history, setHistory] = useState<NavHistoryEntry[]>([]);

  useEffect(() => {
    setHistory((prev) => {
      const entry: NavHistoryEntry = { path: location.pathname, timestamp: new Date().toISOString() };
      const next = [...prev, entry];
      return next.length > MAX_ENTRIES ? next.slice(next.length - MAX_ENTRIES) : next;
    });
  }, [location.pathname]);

  return (
    <NavigationHistoryContext.Provider value={{ history }}>
      {children}
    </NavigationHistoryContext.Provider>
  );
}

export function useNavigationHistory(): NavHistoryEntry[] {
  const ctx = useContext(NavigationHistoryContext);
  if (!ctx) throw new Error("useNavigationHistory must be used inside NavigationHistoryProvider");
  return ctx.history;
}
