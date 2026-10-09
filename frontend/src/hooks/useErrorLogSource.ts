import { usePublicSettings } from "./usePublicSettings";

/** true/false once public settings have loaded; null while they are loading. */
export function useErrorLogSourceConfigured(): boolean | null {
  const settings = usePublicSettings();
  if (settings === null) return null;
  return settings["errors.log_source_configured"] === true;
}
