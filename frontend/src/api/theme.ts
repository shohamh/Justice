import { api } from "./client";

export type ThemePreference = "light" | "dark" | "system";

export async function updateThemePreference(theme: ThemePreference): Promise<ThemePreference> {
  const r = await api.patch<{ theme_preference: ThemePreference }>("/me/theme-preference", {
    theme_preference: theme,
  });
  return r.data.theme_preference;
}
