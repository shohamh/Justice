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
  is_commander: boolean;
  is_duty_manager: boolean;
  must_change_password: boolean;
  hierarchy_node_id: string | null;
  telegram_linked: boolean;
  telegram_required: boolean;
  enrollment_pending: boolean;
  theme_preference: "light" | "dark" | "system";
  phone?: string | null;
  gender?: string | null;
  is_officer?: boolean | null;
  rank?: string | null;
  bahad1_graduate?: boolean;
  has_military_driving_license?: boolean | null;
  military_driving_license_expiry?: string | null;
  enlistment_date?: string | null;
  mandatory_end_date?: string | null;
  discharge_date?: string | null;
  last_mitvahim_date?: string | null;
  last_alal_date?: string | null;
  email?: string | null;
  email_verified?: boolean;
  direct_commander_id?: string | null;
  direct_commander_name?: string | null;
  profile_picture_url?: string | null;
  is_career?: boolean;
  can_view_transparency?: boolean;
}

export interface NodeOut {
  id: string;
  name: string;
  level: string;
  path_ids: string[];
  commander_name: string | null;
  parent_id: string | null;
}

export interface RegisterExemptionRow {
  exemption_type_id: string;
  start_date: string | null;
  end_date: string | null;
  reason: string;
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
  enlistment_date: string | null;
  mandatory_end_date: string | null;
  discharge_date: string | null;
  last_mitvahim_date: string | null;
  last_alal_date: string | null;
  has_military_driving_license: boolean;
  military_driving_license_expiry: string | null;
  requested_node_id: string;
  exemption_requests: RegisterExemptionRow[];
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

export async function register(payload: RegisterPayload, exemptionFiles: File[][] = []): Promise<LoginResponse> {
  const formData = new FormData();
  formData.append("payload", JSON.stringify(payload));
  exemptionFiles.forEach((files, i) => {
    for (const f of files) formData.append(`exemption_files_${i}`, f);
  });
  const r = await api.post<LoginResponse>("/auth/register", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return r.data;
}

export async function fetchRegisterNodes(inviteCode: string): Promise<NodeOut[]> {
  const r = await api.get<NodeOut[]>(`/auth/register/nodes?invite_code=${encodeURIComponent(inviteCode)}`);
  return r.data;
}

export async function validateInviteCode(code: string): Promise<boolean> {
  const r = await api.get<{ valid: boolean }>(`/auth/register/validate-code?code=${encodeURIComponent(code)}`);
  return r.data.valid;
}

export interface PublicExemptionType {
  id: string;
  name: string;
  description: string | null;
  is_medical: boolean;
}

export async function listPublicExemptionTypes(): Promise<PublicExemptionType[]> {
  const r = await api.get<PublicExemptionType[]>("/auth/exemption-types");
  return r.data;
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
