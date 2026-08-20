import { api } from "./client";

export interface DeputyDTO {
  id: string;
  principal_id: string;
  principal_name: string;
  deputy_id: string;
  deputy_name: string;
  role: "commander" | "duty_manager";
  start_date: string;
  end_date: string;
}

export interface CreateDeputyInput {
  principal_id: string;
  deputy_id: string;
  role: "commander" | "duty_manager";
  start_date: string;
  end_date: string;
}

export async function listDeputies(principalId: string): Promise<DeputyDTO[]> {
  return (await api.get<DeputyDTO[]>("/deputies", { params: { principal_id: principalId } })).data;
}

export async function createDeputy(input: CreateDeputyInput): Promise<DeputyDTO> {
  return (await api.post<DeputyDTO>("/deputies", input)).data;
}

export async function revokeDeputy(id: string): Promise<void> {
  await api.delete(`/deputies/${id}`);
}
