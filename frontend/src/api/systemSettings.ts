import { api } from "./client";

export type SettingsMap = Record<string, string | number | boolean | null>;

export async function getSystemSettings(): Promise<SettingsMap> {
  const r = await api.get<{ settings: SettingsMap }>("/admin/system-settings");
  return r.data.settings;
}

export async function updateSystemSettings(settings: SettingsMap): Promise<SettingsMap> {
  const r = await api.put<{ settings: SettingsMap }>("/admin/system-settings", { settings });
  return r.data.settings;
}
