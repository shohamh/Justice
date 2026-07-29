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
  _field_overrides?: Record<string, Record<string, Record<string, unknown>>>;
  [group: string]: Record<string, string> | NameMappings | Record<string, Record<string, Record<string, unknown>>> | undefined;
}

export interface RowBase {
  row: number;
  action: "new" | "update" | "error" | "out_of_scope" | "skip";
  errors: string[];
  warnings?: string[];
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
  is_career: boolean | null;
  next_rank_date: string | null;
  bahad1_graduate: boolean | null;
  has_military_driving_license: boolean | null;
  military_driving_license_expiry: string | null;
  mandatory_end_date: string | null;
  discharge_date: string | null;
  last_mitvahim_date: string | null;
  last_alal_date: string | null;
  left_at: string | null;
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
  duty_location_name: string;
  resolved_duty_location_id: string | null;
  recurrence_type: string;
  weekdays: number[];
  start_time: string | null;
  end_time: string | null;
  required_count: number;
  auto_roll: boolean;
  auto_roll_until: string | null;
  duration_days: number;
  notes: string | null;
  resolved_eligible_node_ids: string[];
  existing_id: string | null;
}

export interface AssignmentRow extends RowBase {
  personal_number: string;
  full_name: string;
  duty_type_name: string;
  duty_location_name: string;
  start_date: string;
  end_date: string;
  start_time: string | null;
  end_time: string | null;
  is_reserve: boolean;
  notes: string | null;
  resolved_soldier_id: string | null;
  resolved_duty_shift_id: string | null;
  matched_session_row: number | null;
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
  description: string | null;
  active: boolean | null;
  reserve_ratio: string | null;
  reserve_minimum: number | null;
  is_external: boolean | null;
  contact_name: string | null;
  contact_phone: string | null;
  start_time: string | null;
  end_time: string | null;
  instructions: string | null;
  resolved_eligible_node_ids: string[];
  requirements: Record<string, unknown> | null;
  existing_id: string | null;
}

export interface ExemptionTypeImportRow extends RowBase {
  name: string;
  description: string | null;
  is_global: boolean;
  is_medical: boolean;
  is_commander_exemption: boolean;
  resolved_duty_type_ids: string[];
  existing_id: string | null;
}

export interface SystemSettingImportRow extends RowBase {
  key: string;
  value_json: string;
  parsed_value: unknown;
}

export interface BugReportImportRow extends RowBase {
  id: string | null;
  reporter_personal_number: string;
  resolved_reporter_id: string | null;
  description: string;
  severity: string;
  route: string;
  status: string;
  created_at: string | null;
  nav_history: unknown;
  audit_snapshot: unknown;
  user_snapshot: unknown;
  existing_id: string | null;
}

export interface PersonalConstraintImportRow extends RowBase {
  id: string | null;
  soldier_personal_number: string;
  resolved_soldier_id: string | null;
  start_date: string;
  end_date: string;
  reason: string;
  status: string;
  decided_by_personal_number: string | null;
  resolved_decided_by_id: string | null;
  decision_note: string | null;
  existing_id: string | null;
}

export interface SoldierFieldUpdateImportRow extends RowBase {
  id: string | null;
  soldier_personal_number: string;
  resolved_soldier_id: string | null;
  field_name: string;
  new_value: string;
  previous_value: string | null;
  status: string;
  decided_by_personal_number: string | null;
  resolved_decided_by_id: string | null;
  decision_note: string | null;
  existing_id: string | null;
}

export interface SoldierEnrollmentRequestImportRow extends RowBase {
  id: string | null;
  soldier_personal_number: string;
  resolved_soldier_id: string | null;
  requested_node_name: string;
  resolved_node_id: string | null;
  status: string;
  decided_by_personal_number: string | null;
  resolved_decided_by_id: string | null;
  decision_note: string | null;
  existing_id: string | null;
}

export interface SoldierExemptionImportRow extends RowBase {
  id: string | null;
  soldier_personal_number: string;
  resolved_soldier_id: string | null;
  exemption_type_name: string;
  resolved_exemption_type_id: string | null;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  granted_by_personal_number: string | null;
  resolved_granted_by_id: string | null;
  revoked: boolean;
  revoke_reason: string | null;
  existing_id: string | null;
}

export interface ExemptionRequestImportRow extends RowBase {
  id: string | null;
  soldier_personal_number: string;
  resolved_soldier_id: string | null;
  exemption_type_name: string;
  resolved_exemption_type_id: string | null;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  status: string;
  commander_approved_by_personal_number: string | null;
  resolved_commander_approved_by_id: string | null;
  decided_by_personal_number: string | null;
  resolved_decided_by_id: string | null;
  decision_note: string | null;
  files: string | null;
  existing_id: string | null;
}

export interface SwapRequestApprovalLogEntry {
  side: "requester" | "covering";
  kind: "commander" | "duty_manager";
  person_pn: string;
  outcome: "approved" | "rejected";
  at: string;
  resolved_person_id: string;
}

export interface SwapRequestImportRow extends RowBase {
  id: string | null;
  requesting_personal_number: string;
  resolved_requesting_soldier_id: string | null;
  target_personal_number: string | null;
  resolved_target_soldier_id: string | null;
  covering_personal_number: string | null;
  resolved_covering_soldier_id: string | null;
  duty_date: string;
  status: string;
  reason: string | null;
  requester_side_approved: boolean | null;
  covering_side_approved: boolean | null;
  rejected_by_personal_number: string | null;
  resolved_rejected_by_id: string | null;
  decision_note: string | null;
  approval_log: SwapRequestApprovalLogEntry[];
  existing_id: string | null;
}

export interface ParsedState {
  soldiers: SoldierRow[];
  duty_shifts: DutyShiftRow[];
  shift_templates: ShiftTemplateRow[];
  assignments: AssignmentRow[];
  duty_locations: DutyLocationRow[];
  hierarchy: HierarchyImportRow[];
  duty_types: DutyTypeImportRow[];
  exemption_types: ExemptionTypeImportRow[];
  system_settings: SystemSettingImportRow[];
  bug_reports: BugReportImportRow[];
  personal_constraints: PersonalConstraintImportRow[];
  soldier_field_updates: SoldierFieldUpdateImportRow[];
  soldier_enrollment_requests: SoldierEnrollmentRequestImportRow[];
  soldier_exemptions: SoldierExemptionImportRow[];
  exemption_requests: ExemptionRequestImportRow[];
  swap_requests: SwapRequestImportRow[];
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
    assignments: number;
    duty_locations: number;
    hierarchy: number;
    duty_types: number;
    exemption_types: number;
    personal_constraints: number;
    soldier_field_updates: number;
    soldier_enrollment_requests: number;
    soldier_exemptions: number;
    exemption_requests: number;
    swap_requests: number;
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
