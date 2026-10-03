import { useEffect, useRef, useState } from "react";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";

const IDLE_DELAY_MS = 400;
const MAX_WAIT_MS = 1200;

/** Opens after the app has been idle for a short window, with a bounded wait. */
export function useDashboardIdleGate(enabled: boolean, scope: string | null): boolean {
  const isFetching = useIsFetching();
  const queryClient = useQueryClient();
  const [openFor, setOpenFor] = useState<string | null>(null);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const maximumTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const gateKey = enabled && scope !== null ? scope : null;
  const opened = gateKey !== null && openFor === gateKey;

  useEffect(() => {
    if (idleTimer.current) clearTimeout(idleTimer.current);
    if (maximumTimer.current) clearTimeout(maximumTimer.current);
    idleTimer.current = null;
    maximumTimer.current = null;
    if (gateKey === null) {
      setOpenFor(null);
      return;
    }

    setOpenFor(null);
    maximumTimer.current = setTimeout(() => setOpenFor(gateKey), MAX_WAIT_MS);
    return () => {
      if (idleTimer.current) clearTimeout(idleTimer.current);
      if (maximumTimer.current) clearTimeout(maximumTimer.current);
    };
  }, [gateKey]);

  useEffect(() => {
    if (gateKey === null || opened) return;
    if (idleTimer.current) clearTimeout(idleTimer.current);
    idleTimer.current = null;
    if (isFetching === 0) {
      idleTimer.current = setTimeout(() => {
        if (queryClient.isFetching() === 0) setOpenFor(gateKey);
      }, IDLE_DELAY_MS);
    }
    return () => {
      if (idleTimer.current) clearTimeout(idleTimer.current);
    };
  }, [gateKey, isFetching, opened, queryClient]);

  return opened;
}
