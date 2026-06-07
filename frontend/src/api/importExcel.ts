import { api } from "./client";

export interface SoldierRowPreview {
  row: number;
  action: "new" | "update" | "error";
  personal_number: string;
  full_name: string;
  rank: string | null;
  gender: string | null;
  is_officer: boolean | null;
  hierarchy_node_id: string | null;
  hierarchy_node_name: string | null;
  enrolled_at: string | null;
  enlistment_date: string | null;
  phone: string | null;
  email: string | null;
  existing_id: string | null;
  errors: string[];
}

export interface AssignmentRowPreview {
  row: number;
  action: "new" | "error";
  personal_number: string;
  duty_type_name: string;
  start_date: string;
  end_date: string;
  is_reserve: boolean;
  resolved_soldier_id: string | null;
  resolved_duty_type_id: string | null;
  errors: string[];
}

export interface TemplateRowPreview {
  row: number;
  action: "new" | "error";
  name: string;
  duty_type_name: string;
  days_of_week: number[];
  required_primary: number;
  required_reserve: number;
  resolved_duty_type_id: string | null;
  errors: string[];
}

export interface PreviewResult {
  soldiers: SoldierRowPreview[];
  assignments: AssignmentRowPreview[];
  shift_templates: TemplateRowPreview[];
}

export interface ApplySoldierRow {
  row: number;
  action: "new" | "update" | "skip";
  personal_number: string;
  full_name: string;
  rank: string | null;
  gender: string | null;
  is_officer: boolean | null;
  hierarchy_node_id: string | null;
  hierarchy_node_name: string | null;
  enrolled_at: string | null;
  enlistment_date: string | null;
  phone: string | null;
  email: string | null;
  existing_id: string | null;
}

export interface ApplyAssignmentRow {
  row: number;
  action: "new" | "skip";
  resolved_soldier_id: string;
  resolved_duty_type_id: string;
  start_date: string;
  end_date: string;
  is_reserve: boolean;
}

export interface ApplyTemplateRow {
  row: number;
  action: "new" | "skip";
  name: string;
  resolved_duty_type_id: string;
  days_of_week: number[];
  required_primary: number;
  required_reserve: number;
}

export interface ApplyRequest {
  soldiers: ApplySoldierRow[];
  assignments: ApplyAssignmentRow[];
  shift_templates: ApplyTemplateRow[];
}

export interface ApplyResult {
  created: number;
  updated: number;
  skipped: number;
  errors: string[];
}

export async function previewImport(file: File): Promise<PreviewResult> {
  const form = new FormData();
  form.append("file", file);
  return (
    await api.post<PreviewResult>("/import/preview", form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
  ).data;
}

export async function applyImport(req: ApplyRequest): Promise<ApplyResult> {
  return (await api.post<ApplyResult>("/import/apply", req)).data;
}
