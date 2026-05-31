import { api } from "./client";

export interface DutyShift {
  id: string;
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  required_count: number;
  notes: string | null;
  assigned_count: number;
  fill_status: "empty" | "partial" | "full";
  reserve_count_override?: number | null;
  calculated_reserve_count?: number | null;
}

export interface CreateShiftInput {
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  required_count: number;
  notes?: string | null;
  reserve_count_override?: number | null;
}

export interface UpdateShiftInput {
  start_date?: string;
  end_date?: string;
  required_count?: number;
  notes?: string | null;
  reserve_count_override?: number | null;
}

export async function listShifts(params?: {
  date_from?: string;
  date_to?: string;
  duty_type_id?: string;
}): Promise<DutyShift[]> {
  return (await api.get<DutyShift[]>("/shifts", { params })).data;
}

export async function createShift(input: CreateShiftInput): Promise<DutyShift> {
  return (await api.post<DutyShift>("/shifts", input)).data;
}

export async function updateShift(id: string, input: UpdateShiftInput): Promise<DutyShift> {
  return (await api.patch<DutyShift>(`/shifts/${id}`, input)).data;
}

export async function deleteShift(id: string): Promise<void> {
  await api.delete(`/shifts/${id}`);
}
