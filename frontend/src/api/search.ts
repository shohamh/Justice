import { api } from "./client";

export interface SoldierResultDTO {
  id: string;
  full_name: string;
  personal_number: string;
  subtitle: string | null;
}

export interface DutyResultDTO {
  id: string;
  duty_type_name: string;
  start_date: string;
  end_date: string;
  location_name: string;
}

export interface UnitResultDTO {
  id: string;
  name: string;
  level: string;
}

export interface SearchResponseDTO {
  soldiers: SoldierResultDTO[];
  duties: DutyResultDTO[];
  units: UnitResultDTO[];
}

export async function search(q: string): Promise<SearchResponseDTO> {
  return (await api.get<SearchResponseDTO>("/search", { params: { q } })).data;
}
