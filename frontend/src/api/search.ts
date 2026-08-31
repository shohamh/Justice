import { api } from "./client";
import { isRecord, optionalArrayResponse } from "./responseGuards";

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
  const r = await api.get<unknown>("/search", { params: { q } });
  const data = isRecord(r.data) ? r.data : {};
  return {
    soldiers: optionalArrayResponse<SoldierResultDTO>(data.soldiers),
    duties: optionalArrayResponse<DutyResultDTO>(data.duties),
    units: optionalArrayResponse<UnitResultDTO>(data.units),
  };
}
