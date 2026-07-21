import { useEffect, useState } from "react";
import { getPublicSettings, SettingsMap } from "../api/publicSettings";

// Module-level cache so every component using this hook shares a single
// underlying request instead of each firing its own /settings/public call.
let cache: SettingsMap | null = null;
let inflight: Promise<SettingsMap> | null = null;

export function usePublicSettings(): SettingsMap | null {
  const [settings, setSettings] = useState<SettingsMap | null>(cache);

  useEffect(() => {
    if (cache) {
      setSettings(cache);
      return;
    }
    if (!inflight) {
      inflight = getPublicSettings()
        .then((s) => {
          cache = s;
          return s;
        })
        .catch(() => {
          // Don't poison the cache: a failure (e.g. unauthenticated fetch from
          // the login page) shouldn't be remembered as "settings are {}" for the
          // lifetime of the page. Reset inflight so the next caller retries.
          inflight = null;
          return {} as SettingsMap;
        });
    }
    let cancelled = false;
    inflight.then((s) => {
      if (!cancelled) setSettings(s);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return settings;
}
