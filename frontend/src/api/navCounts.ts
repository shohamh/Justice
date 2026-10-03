import { api } from "./client";
import { requiredNumberField, requiredObjectResponse } from "./responseGuards";

export interface NavCounts {
  approvals: number;
  hakpaza: number;
  incoming_swaps: number;
}

export async function getNavCounts(): Promise<NavCounts> {
  const { data } = await api.get<unknown>("/nav/counts");
  const response = requiredObjectResponse(data, "Invalid navigation counts response");
  return {
    approvals: requiredNumberField(response.approvals, "Invalid navigation approvals count"),
    hakpaza: requiredNumberField(response.hakpaza, "Invalid navigation Hakpaza count"),
    incoming_swaps: requiredNumberField(response.incoming_swaps, "Invalid navigation incoming swaps count"),
  };
}
