import { api } from "./client";

export interface InviteCodeDTO {
  id: string;
  code: string;
  uses_left: number;
  created_by: string | null;
}

export async function listInviteCodes(): Promise<InviteCodeDTO[]> {
  const r = await api.get<unknown>("/admin/invite-codes");
  if (!Array.isArray(r.data)) {
    throw new Error("Invalid invite-code list response");
  }
  return r.data as InviteCodeDTO[];
}

export async function createInviteCode(uses_left: number): Promise<InviteCodeDTO> {
  const r = await api.post<InviteCodeDTO>("/admin/invite-codes", { uses_left });
  return r.data;
}

export async function revokeInviteCode(id: string): Promise<void> {
  await api.delete(`/admin/invite-codes/${id}`);
}
