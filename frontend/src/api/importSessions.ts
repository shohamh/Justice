import { api } from "./client";

export interface NameMappings {
  duty_type?: {
    by_name?: Record<string, string>;
    by_row?: Record<string, string>;
  };
  hierarchy_node?: {
    by_name?: Record<string, string>;
    by_row?: Record<string, string>;
  };
}

export interface Selections {
  _name_mappings?: NameMappings;
  [group: string]: Record<string, string> | NameMappings | undefined;
}

export interface RowBase {
  row: number;
  action: "new" | "update" | "error" | "out_of_scope" | "skip";
  errors: string[];
}

export interface NodeQuotaRow {
  node_name: string;
  node_id: string | null;
  count: number;
  resolved: boolean;
}

export interface SoldierRow extends RowBase {
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

export interface DutyShiftRow extends RowBase {
  duty_type_name: string;
  resolved_duty_type_id: string | null;
  duty_location_name: string;
  resolved_duty_location_id: string | null;
  start_date: string;
  end_date: string;
  start_time: string | null;
  end_time: string | null;
  required_count: number;
  node_quotas: NodeQuotaRow[];
  notes: string | null;
}

export interface ShiftTemplateRow extends RowBase {
  name: string;
  duty_type_name: string;
  resolved_duty_type_id: string | null;
  days_of_week: number[];
  required_primary: number;
  required_reserve: number;
}

export interface DutyLocationRow extends RowBase {
  name: string;
  base: string | null;
  active: boolean | null;
  existing_id: string | null;
}

export interface DutyManagerRefRow {
  ref: string;
  resolved_soldier_id: string | null;
}

export interface HierarchyImportRow extends RowBase {
  name: string;
  level: string;
  parent_name: string | null;
  resolved_parent_id: string | null;
  commander_personal_number: string | null;
  commander_name: string | null;
  resolved_commander_id: string | null;
  duty_manager_refs: DutyManagerRefRow[];
  existing_id: string | null;
}

export interface DutyTypeImportRow extends RowBase {
  name: string;
  score_per_day: string | null;
  resolved_eligible_node_ids: string[];
  requirements: Record<string, unknown> | null;
  existing_id: string | null;
}

export interface ExemptionTypeImportRow extends RowBase {
  name: string;
  resolved_duty_type_ids: string[];
  existing_id: string | null;
}

export interface ParsedState {
  soldiers: SoldierRow[];
  duty_shifts: DutyShiftRow[];
  shift_templates: ShiftTemplateRow[];
  duty_locations: DutyLocationRow[];
  hierarchy: HierarchyImportRow[];
  duty_types: DutyTypeImportRow[];
  exemption_types: ExemptionTypeImportRow[];
  parser_id: string;
  parser_warnings: string[];
}

export interface SessionSummary {
  id: string;
  status: "draft" | "confirmed" | "cancelled" | "done";
  filename: string;
  created_at: string;
  row_summary: {
    soldiers: number;
    duty_shifts: number;
  };
}

export interface SessionDetail {
  id: string;
  status: string;
  filename: string;
  parsed_state: ParsedState;
  user_selections: Selections;
  created_links: Record<string, string[]>;
}

export interface ConfirmSessionResult {
  created: number;
  updated: number;
  skipped: number;
  errors: { row: number; type: string; error: string }[];
}

export async function uploadSession(
  file: File,
  parserId?: string,
): Promise<{ session_id: string; preview: ParsedState }> {
  const form = new FormData();
  form.append("file", file);
  return (
    await api.post<{ session_id: string; preview: ParsedState }>(
      "/import/sessions",
      form,
      {
        headers: { "Content-Type": "multipart/form-data" },
        params: parserId ? { parser_id: parserId } : undefined,
      },
    )
  ).data;
}

export async function listSessions(
  statusFilter?: string,
): Promise<SessionSummary[]> {
  return (
    await api.get<SessionSummary[]>("/import/sessions", {
      params: statusFilter ? { status_filter: statusFilter } : undefined,
    })
  ).data;
}

export async function getSession(id: string): Promise<SessionDetail> {
  return (await api.get<SessionDetail>(`/import/sessions/${id}`)).data;
}

export async function reparseSession(id: string): Promise<SessionDetail> {
  return (await api.post<SessionDetail>(`/import/sessions/${id}/reparse`))
    .data;
}

export async function saveSelections(
  id: string,
  selections: Selections,
): Promise<void> {
  await api.patch(`/import/sessions/${id}/selections`, { selections });
}

export async function confirmSession(
  id: string,
): Promise<ConfirmSessionResult> {
  return (
    await api.post<ConfirmSessionResult>(`/import/sessions/${id}/confirm`)
  ).data;
}

export async function cancelSession(id: string): Promise<void> {
  await api.post(`/import/sessions/${id}/cancel`);
}

export async function markSessionDone(id: string): Promise<void> {
  await api.post(`/import/sessions/${id}/done`);
}

export async function listDutyTypesForImport(): Promise<{ id: string; name: string }[]> {
  return (
    await api.get<{ id: string; name: string }[]>("/import-lookup/duty-types")
  ).data;
}

export async function listNodesForImport(): Promise<
  { id: string; name: string; parent_id: string | null; level: string }[]
> {
  return (
    await api.get<{ id: string; name: string; parent_id: string | null; level: string }[]>(
      "/import-lookup/hierarchy",
    )
  ).data.map((n) => ({ id: n.id, name: n.name, parent_id: n.parent_id, level: n.level }));
}
