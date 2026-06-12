import { api } from "./client";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  must_change_password: boolean;
}

export interface Me {
  id: string;
  personal_number: string;
  full_name: string;
  role: "soldier" | "commander" | "duty_manager" | "admin";
  must_change_password: boolean;
  hierarchy_node_id: string | null;
  telegram_linked: boolean;
  telegram_required: boolean;
  phone?: string | null;
  gender?: string | null;
  is_officer?: boolean | null;
  rank?: string | null;
  bahad1_graduate?: boolean;
  enlistment_date?: string | null;
  mandatory_end_date?: string | null;
  discharge_date?: string | null;
  last_mitvahim_date?: string | null;
  last_alal_date?: string | null;
  email?: string | null;
  email_verified?: boolean;
  direct_commander_id?: string | null;
  direct_commander_name?: string | null;
}

export interface NodeOut {
  id: string;
  name: string;
  level: string;
  path_ids: string[];
  commander_name: string | null;
  parent_id: string | null;
}

export interface RegisterPayload {
  invite_code: string;
  personal_number: string;
  full_name: string;
  password: string;
  phone: string | null;
  email?: string | null;
  gender: string | null;
  is_officer: boolean | null;
  rank: string | null;
  bahad1_graduate: boolean;
  enlistment_date: string | null;
  mandatory_end_date: string | null;
  discharge_date: string | null;
  last_mitvahim_date: string | null;
  last_alal_date: string | null;
  requested_node_id: string;
  exemption_requests: object[];
  personal_constraints: object[];
}

export async function login(personal_number: string, password: string, remember_me = false): Promise<LoginResponse> {
  const r = await api.post<LoginResponse>("/auth/login", { personal_number, password, remember_me });
  return r.data;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout");
}

export async function fetchMe(): Promise<Me> {
  const r = await api.get<Me>("/me");
  return r.data;
}

export async function changePassword(current_password: string, new_password: string): Promise<void> {
  await api.post("/auth/change-password", { current_password, new_password });
}

export async function register(payload: RegisterPayload): Promise<LoginResponse> {
  const r = await api.post<LoginResponse>("/auth/register", payload);
  return r.data;
}

export async function fetchRegisterNodes(): Promise<NodeOut[]> {
  const r = await api.get<NodeOut[]>("/auth/register/nodes");
  return r.data;
}

export async function validateInviteCode(code: string): Promise<boolean> {
  const r = await api.get<{ valid: boolean }>(`/auth/register/validate-code?code=${encodeURIComponent(code)}`);
  return r.data.valid;
}

export async function checkForgotPasswordChannels(personal_number: string): Promise<string[]> {
  const r = await api.post<{ channels: string[] }>("/auth/forgot-password", { personal_number });
  return r.data.channels;
}

export async function sendForgotPassword(personal_number: string, channel: string): Promise<void> {
  await api.post("/auth/forgot-password/send", { personal_number, channel });
}

export async function resetPassword(token: string, new_password: string): Promise<void> {
  await api.post("/auth/reset-password", { token, new_password });
}

export async function setEmail(email: string | null): Promise<{ email_verified: boolean }> {
  const r = await api.patch<{ email_verified: boolean }>("/me/email", { email });
  return r.data;
}

export async function verifyEmail(token: string): Promise<void> {
  await api.post("/auth/verify-email", { token });
}
