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
  status: "active" | "cancelled";
  reserve_count_override?: number | null;
  calculated_reserve_count?: number | null;
  eligible_node_ids?: string[] | null;
  generated_from_template_id?: string | null;
  generated_from_template_name?: string | null;
  node_quotas?: NodeQuota[];
  ineligible_count: number;
}

export interface NodeQuota {
  hierarchy_node_id: string;
  node_name: string;
  count: number;
}

export interface QuotaSplitEntry {
  hierarchy_node_id: string;
  node_name: string;
  count: number;
  weight: number;
}

export interface CreateShiftInput {
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  start_time?: string | null;
  end_time?: string | null;
  required_count: number;
  notes?: string | null;
  reserve_count_override?: number | null;
  eligible_node_ids?: string[] | null;
}

export interface UpdateShiftInput {
  start_date?: string;
  end_date?: string;
  required_count?: number;
  notes?: string | null;
  reserve_count_override?: number | null;
  eligible_node_ids?: string[] | null;
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

export async function setShiftQuotas(
  shiftId: string,
  quotas: { hierarchy_node_id: string; count: number }[]
): Promise<{ quotas: NodeQuota[] }> {
  return (await api.put<{ quotas: NodeQuota[] }>(`/shifts/${shiftId}/quotas`, { quotas })).data;
}

export async function getQuotaSplitPreview(
  parentNodeId: string,
  requiredCount: number
): Promise<QuotaSplitEntry[]> {
  const r = await api.get<{ entries: QuotaSplitEntry[] }>("/shifts/quota-split-preview", {
    params: { parent_node_id: parentNodeId, required_count: requiredCount },
  });
  return r.data.entries;
}

export interface TwoLevelSplitEntry {
  hierarchy_node_id: string;
  node_name: string;
  count: number;
  weight: number;
  parent_responsible_node_id: string;
}

export async function getTwoLevelSplitPreview(shiftId: string): Promise<TwoLevelSplitEntry[]> {
  const r = await api.get<{ entries: TwoLevelSplitEntry[] }>(`/shifts/${shiftId}/quota-split-preview-two-level`);
  return r.data.entries;
}

export interface ResponsibilityAssignment {
  shift_id: string;
  hierarchy_node_id: string;
  node_name: string;
}

export async function getAutoAssignResponsibilityPreview(shiftIds: string[]): Promise<ResponsibilityAssignment[]> {
  const r = await api.post<{ assignments: ResponsibilityAssignment[] }>(
    "/shifts/auto-assign-responsibility/preview",
    { shift_ids: shiftIds }
  );
  return r.data.assignments;
}

export async function assignBatch(
  shiftId: string,
  input: { primaries: string[]; reserves: string[] },
): Promise<{ primary_assignment_ids: string[]; reserve_assignment_ids: string[]; reserve_links_created: number }> {
  return (await api.post(`/shifts/${shiftId}/assign-batch`, input)).data;
}

export async function removeShiftAssignment(shiftId: string, assignmentId: string): Promise<void> {
  await api.delete(`/shifts/${shiftId}/assignments/${assignmentId}`);
}

export async function clearShiftAssignments(id: string): Promise<void> {
  await api.delete(`/shifts/${id}/assignments`);
}

export async function cancelShift(id: string): Promise<DutyShift> {
  return (await api.post<DutyShift>(`/shifts/${id}/cancel`)).data;
}

export async function activateShift(id: string): Promise<DutyShift> {
  return (await api.post<DutyShift>(`/shifts/${id}/activate`)).data;
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

export async function getWeaponIneligibleCount(): Promise<number> {
  const r = await api.get<{ count: number }>("/shifts/weapon-ineligible/count");
  return r.data.count;
}
