import { api } from "./client";

export interface RangeLocation {
  id: string;
  name: string;
  active: boolean;
}

export async function listRangeLocations(): Promise<RangeLocation[]> {
  return (await api.get<RangeLocation[]>("/range-locations")).data;
}

export async function createRangeLocation(input: { name: string }): Promise<RangeLocation> {
  return (await api.post<RangeLocation>("/range-locations", input)).data;
}
