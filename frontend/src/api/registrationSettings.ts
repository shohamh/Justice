import { api } from "./client";

export interface RegistrationPublicSettings {
  email_domain_hint: string | null;
}

export async function getRegistrationPublicSettings(): Promise<RegistrationPublicSettings> {
  const r = await api.get<RegistrationPublicSettings>("/settings/public/registration");
  return r.data;
}
