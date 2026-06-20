import { api } from "./client";

export type RecurrenceType = "daily" | "weekdays" | "weekly";

export interface ShiftTemplate {
  id: string;
  name: string;
  duty_type_id: string;
  duty_location_id: string;
  recurrence_type: RecurrenceType;
  weekdays: number[];
  duration_days: number;
  start_time: string;
  end_time: string;
  required_count: number;
  active: boolean;
  auto_roll: boolean;
  auto_roll_until: string | null;
  notes: string | null;
}

export interface CreateTemplateInput {
  name: string;
  duty_type_id: string;
  duty_location_id: string;
  recurrence_type: RecurrenceType;
  weekdays: number[];
  duration_days?: number;
  start_time?: string;
  end_time?: string;
  required_count?: number;
  auto_roll?: boolean;
  auto_roll_until?: string | null;
  notes?: string | null;
}

export type UpdateTemplateInput = Partial<
  Omit<CreateTemplateInput, "duty_type_id" | "duty_location_id"> & { active: boolean }
>;

export interface PreviewRow {
  date: string;
  exists: boolean;
}

export async function listTemplates(includeInactive = false): Promise<ShiftTemplate[]> {
  return (await api.get<ShiftTemplate[]>("/shift-templates", { params: { include_inactive: includeInactive } })).data;
}

export async function createTemplate(input: CreateTemplateInput): Promise<ShiftTemplate> {
  return (await api.post<ShiftTemplate>("/shift-templates", input)).data;
}

export async function updateTemplate(id: string, input: UpdateTemplateInput): Promise<ShiftTemplate> {
  return (await api.patch<ShiftTemplate>(`/shift-templates/${id}`, input)).data;
}

export async function deleteTemplate(id: string): Promise<void> {
  await api.delete(`/shift-templates/${id}`);
}

export async function previewGeneration(
  id: string,
  range_start: string,
  range_end: string,
): Promise<PreviewRow[]> {
  return (await api.post<PreviewRow[]>(`/shift-templates/${id}/preview`, { range_start, range_end })).data;
}

export async function generateShifts(
  id: string,
  range_start: string,
  range_end: string,
): Promise<{ created_count: number }> {
  return (await api.post<{ created_count: number }>(`/shift-templates/${id}/generate`, { range_start, range_end })).data;
}
