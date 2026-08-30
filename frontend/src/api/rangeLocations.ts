import { api } from "./client";
import { optionalArrayResponse } from "./responseGuards";

export interface RangeLocation {
  id: string;
  name: string;
  active: boolean;
  usage_count?: number;
  can_delete?: boolean;
}

export async function listRangeLocations(): Promise<RangeLocation[]> {
  const r = await api.get<unknown>("/range-locations");
  return optionalArrayResponse<RangeLocation>(r.data);
}

export async function createRangeLocation(input: { name: string }): Promise<RangeLocation> {
  return (await api.post<RangeLocation>("/range-locations", input)).data;
}

export async function updateRangeLocation(
  id: string,
  input: { name?: string; active?: boolean },
): Promise<RangeLocation> {
  return (await api.patch<RangeLocation>(`/range-locations/${id}`, input)).data;
}

export async function deleteRangeLocation(id: string): Promise<void> {
  await api.delete(`/range-locations/${id}`);
}
