import type { RangeType } from "./ranges";
import { api } from "./client";

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

export interface UpcomingWeaponDuty {
  assignment_id: string;
  duty_type_id: string;
  duty_type_name: string;
  start_date: string;
  end_date: string;
  required_range_type: RangeType;
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

export function getIneligibleSoldiers(
  audience: IneligibleSoldiersAudience,
): Promise<IneligibleSoldiersResponse> {
  return api
    .get<IneligibleSoldiersResponse>("/ranges/ineligible-soldiers", { params: { audience } })
    .then((response) => response.data);
}

export function getIneligibleSoldierCount(): Promise<{ count: number }> {
  return api
    .get<{ count: number }>("/ranges/ineligible-soldiers/count")
    .then((response) => response.data);
}
