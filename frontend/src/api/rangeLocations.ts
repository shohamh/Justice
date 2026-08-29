import { api } from "./client";

export interface RangeLocation {
  id: string;
  name: string;
  active: boolean;
  usage_count?: number;
  can_delete?: boolean;
}

export async function listRangeLocations(): Promise<RangeLocation[]> {
  return (await api.get<RangeLocation[]>("/range-locations")).data;
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
