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

export interface Me {
  id: string;
  personal_number: string;
  full_name: string;
  role: "soldier" | "commander" | "duty_manager" | "admin";
  must_change_password: boolean;
  hierarchy_node_id: string | null;
  phone: string | null;
  left_at: string | null;
  gender: string | null;
  is_officer: boolean | null;
  rank: string | null;
  bahad1_graduate: boolean;
  enlistment_date: string | null;
  mandatory_end_date: string | null;
  discharge_date: string | null;
  last_mitvahim_date: string | null;
  last_alal_date: string | null;
}

export async function fetchMe(): Promise<Me> {
  const r = await api.get<Me>("/me");
  return r.data;
}

export async function changePassword(current_password: string, new_password: string): Promise<void> {
  await api.post("/auth/change-password", { current_password, new_password });
}
