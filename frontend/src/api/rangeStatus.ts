import type { RangeType } from "./ranges";
import { api } from "./client";
import { optionalArrayResponse, requiredObjectResponse } from "./responseGuards";

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
  return api.get<unknown>(`/soldiers/${soldierId}/range-status`).then((response) => {
    const data = requiredObjectResponse(response.data, "Invalid range status response");
    if (typeof data.soldier_id !== "string") {
      throw new Error("Invalid range status response");
    }
    return {
      ...(data as unknown as SoldierRangeStatusResponse),
      statuses: optionalArrayResponse<RangeStatus>(data.statuses),
    };
  });
}
