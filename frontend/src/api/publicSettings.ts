import { api } from "./client";

export type SettingsMap = Record<string, string | number | boolean | null>;

export async function getPublicSettings(): Promise<SettingsMap> {
  const r = await api.get<{ settings: SettingsMap }>("/settings/public");
  return r.data.settings;
}
