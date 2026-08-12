import type { RangeType } from "./ranges";
import { api } from "./client";

export interface RangeStatus {
  required_range_type: RangeType;
  eligible: boolean;
  qualification_source: string | null;
  covered_by_range_date: string | null;
  covering_range_type: RangeType | null;
  projected_valid_until: string | null;
  last_qualification_type: RangeType | null;
  last_qualification_date: string | null;
}

export interface SoldierRangeStatusResponse {
  soldier_id: string;
  statuses: RangeStatus[];
}

export function getSoldierRangeStatus(soldierId: string): Promise<SoldierRangeStatusResponse> {
  return api
    .get<SoldierRangeStatusResponse>(`/soldiers/${soldierId}/range-status`)
    .then((response) => response.data);
}
