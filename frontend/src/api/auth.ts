import { api } from "./client";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  must_change_password: boolean;
}

export async function login(personal_number: string, password: string): Promise<LoginResponse> {
  const r = await api.post<LoginResponse>("/auth/login", { personal_number, password });
  return r.data;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout");
}
