import type { RangeType } from "./ranges";
import { api } from "./client";
import { isRecord, optionalArrayResponse, requiredObjectResponse } from "./responseGuards";

export type IneligibleSoldiersAudience = "planning" | "commander";

export interface IneligibleHierarchyNode {
  id: string;
  name: string;
  level: string;
  parent_id: string | null;
  path_ids: string[];
}

export interface QualificationSummary {
  range_type: RangeType;
  valid_until: string;
}

export interface DutyEligibilityFact {
  eligible: boolean;
  required_range_type: RangeType | null;
  qualification_source: string | null;
  covered_by_range_date: string | null;
  covering_range_type: RangeType | null;
  projected_valid_until: string | null;
  reason: string | null;
  duty_type_name: string;
  start_date: string;
  last_qualification_type: RangeType | null;
  last_qualification_date: string | null;
}

export interface UpcomingWeaponDuty extends DutyEligibilityFact {
  assignment_id: string;
  duty_type_id: string;
  duty_type_name: string;
  start_date: string;
  end_date: string;
}

export interface UpcomingMatchingRange {
  event_id: string;
  range_type: RangeType;
  date: string;
}

export interface IneligibleSoldier {
  soldier_id: string;
  soldier_name: string;
  personal_number: string;
  hierarchy_node_id: string;
  hierarchy_node_name: string;
  hierarchy_path_ids: string[];
  valid_qualifications: QualificationSummary[];
  has_upcoming_weapon_duty: boolean;
  has_upcoming_matching_range: boolean;
  upcoming_weapon_duties: UpcomingWeaponDuty[];
  upcoming_matching_ranges: UpcomingMatchingRange[];
}

export interface IneligibleSoldiersResponse {
  count: number;
  nodes: IneligibleHierarchyNode[];
  soldiers: IneligibleSoldier[];
}

/**
 * Normalizes one raw hierarchy-node row: drops it if the row itself isn't an
 * object, otherwise coerces the nested `path_ids` array so hierarchyRows()'s
 * traversal in IneligibleSoldiersTable can't throw on a malformed row.
 */
function sanitizeIneligibleHierarchyNode(raw: unknown): IneligibleHierarchyNode | null {
  if (!isRecord(raw)) return null;
  return {
    ...(raw as unknown as IneligibleHierarchyNode),
    path_ids: optionalArrayResponse<string>(raw.path_ids),
  };
}

/**
 * Normalizes one raw soldier row: drops it if the row itself isn't an
 * object, otherwise coerces every nested collection so
 * IneligibleSoldiersTable's `.filter`/`.map`/`.includes` calls over a row's
 * qualifications and upcoming duties/ranges can't throw and take the whole
 * table down.
 */
function sanitizeIneligibleSoldier(raw: unknown): IneligibleSoldier | null {
  if (!isRecord(raw)) return null;
  return {
    ...(raw as unknown as IneligibleSoldier),
    hierarchy_path_ids: optionalArrayResponse<string>(raw.hierarchy_path_ids),
    valid_qualifications: optionalArrayResponse<QualificationSummary>(raw.valid_qualifications),
    upcoming_weapon_duties: optionalArrayResponse<UpcomingWeaponDuty>(raw.upcoming_weapon_duties),
    upcoming_matching_ranges: optionalArrayResponse<UpcomingMatchingRange>(raw.upcoming_matching_ranges),
  };
}

export async function getIneligibleSoldiers(
  audience: IneligibleSoldiersAudience,
): Promise<IneligibleSoldiersResponse> {
  const r = await api.get<unknown>("/ranges/ineligible-soldiers", { params: { audience } });
  const data = requiredObjectResponse(r.data, "Invalid ineligible soldiers response");
  return {
    ...(data as unknown as IneligibleSoldiersResponse),
    nodes: optionalArrayResponse<unknown>(data.nodes)
      .map(sanitizeIneligibleHierarchyNode)
      .filter((n): n is IneligibleHierarchyNode => n !== null),
    soldiers: optionalArrayResponse<unknown>(data.soldiers)
      .map(sanitizeIneligibleSoldier)
      .filter((s): s is IneligibleSoldier => s !== null),
  };
}

export function getIneligibleSoldierCount(): Promise<{ count: number }> {
  return api
    .get<{ count: number }>("/ranges/ineligible-soldiers/count")
    .then((response) => response.data);
}
