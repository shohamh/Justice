import { usePublicSettings } from "./usePublicSettings";

/**
 * true/false once public settings have loaded; null while loading or when the flag is
 * missing (the backend always sends it, so a missing key means the fetch failed: unknown).
 */
export function useErrorLogSourceConfigured(): boolean | null {
  const settings = usePublicSettings();
  if (settings === null) return null;
  const value = settings["errors.log_source_configured"];
  return typeof value === "boolean" ? value : null;
}
