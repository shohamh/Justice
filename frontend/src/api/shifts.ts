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
  reserve_assigned_count: number;
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

export async function clearShiftAssignments(id: string): Promise<void> {
  await api.delete(`/shifts/${id}/assignments`);
}

export interface BulkDeletePreviewShift {
  id: string;
  duty_type_name: string;
  duty_location_name: string;
  start_date: string;
  end_date: string;
  required_count: number;
}

export interface BulkDeletePreview {
  shift_count: number;
  assignment_count: number;
  swap_count: number;
  dismissal_count: number;
  reserve_link_count: number;
  shifts: BulkDeletePreviewShift[];
}

export async function getBulkDeletePreview(dateFrom: string, dateTo: string): Promise<BulkDeletePreview> {
  return (await api.get<BulkDeletePreview>("/shifts/bulk-delete/preview", { params: { date_from: dateFrom, date_to: dateTo } })).data;
}

export async function bulkDeleteShifts(dateFrom: string, dateTo: string): Promise<{ deleted_shifts: number; deleted_assignments: number }> {
  return (await api.delete<{ deleted_shifts: number; deleted_assignments: number }>("/shifts/bulk-delete", { params: { date_from: dateFrom, date_to: dateTo } })).data;
}

export async function bulkClearAssignments(dateFrom: string, dateTo: string): Promise<{ cleared_assignments: number }> {
  return (await api.delete<{ cleared_assignments: number }>("/shifts/bulk-clear-assignments", { params: { date_from: dateFrom, date_to: dateTo } })).data;
}
