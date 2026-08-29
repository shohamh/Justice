import { api } from "./client";

export interface DutyType {
  id: string;
  name: string;
  score_per_day: string;
  description: string | null;
  active: boolean;
  reserve_ratio?: string;
  reserve_minimum?: number;
  requirements?: {
    allowed_genders?: string[];
    requires_mitvahim?: boolean;
    requires_alal?: boolean;
    allowed_ranks?: string[];
    allowed_service_types?: string[];
    rank_service_types?: Record<string, string[]>;
    officers_allowed?: boolean;
    enlisted_allowed?: boolean;
    requires_bahad1?: boolean;
    requires_military_driving_license?: boolean;
    rest_hours?: number;
  };
  contact_name: string | null;
  contact_phone: string | null;
  start_time: string | null;   // "HH:MM:SS" from API
  end_time: string | null;     // "HH:MM:SS" from API
  instructions: string | null;
  is_external: boolean;
  required_range_type: string | null;
  eligible_node_ids: string[] | null;

}

export interface DutyLocation {
  id: string;
  name: string;
  base: string | null;
  active: boolean;
}

export interface ExemptionType {
  id: string;
  name: string;
  description: string | null;
  is_global?: boolean;
  is_medical?: boolean;
  is_commander_exemption?: boolean;
  active: boolean;
}

export async function listDutyTypes(): Promise<DutyType[]> {
  const data = (await api.get<DutyType[]>("/duty-config/duty-types")).data;
  return Array.isArray(data) ? data : [];
}
export async function createDutyType(input: {
  name: string;
  score_per_day: string;
  description?: string | null;
  reserve_ratio?: string;
  reserve_minimum?: number;
  contact_name?: string | null;
  contact_phone?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  instructions?: string | null;
  is_external: boolean;
  required_range_type?: string | null;
  eligible_node_ids?: string[] | null;
}): Promise<DutyType> {
  return (await api.post<DutyType>("/duty-config/duty-types", input)).data;
}
export async function updateDutyType(
  id: string,
  input: Partial<{
    name: string;
    score_per_day: string;
    description: string | null;
    active: boolean;
    reserve_ratio: string;
    reserve_minimum: number;
    contact_name: string | null;
    contact_phone: string | null;
    start_time: string | null;
    end_time: string | null;
    instructions: string | null;
    is_external: boolean;
    required_range_type: string | null;
    eligible_node_ids: string[] | null;
    requirements: DutyType["requirements"];
  }>
): Promise<DutyType> {
  return (await api.patch<DutyType>(`/duty-config/duty-types/${id}`, input)).data;
}

export async function deleteDutyType(id: string): Promise<void> {
  await api.delete(`/duty-config/duty-types/${id}`);
}

export interface DutyTypeUsage {
  past_count: number;
  future_count: number;
  template_count: number;
  shift_count: number;
  exemption_map_count: number;
}

export async function getDutyTypeUsage(id: string): Promise<DutyTypeUsage> {
  return (await api.get<DutyTypeUsage>(`/duty-config/duty-types/${id}/usage`)).data;
}

export async function listLocations(): Promise<DutyLocation[]> {
  const data = (await api.get<DutyLocation[]>("/duty-config/locations")).data;
  return Array.isArray(data) ? data : [];
}
export async function createLocation(input: { name: string; base?: string | null }): Promise<DutyLocation> {
  return (await api.post<DutyLocation>("/duty-config/locations", input)).data;
}
export async function updateLocation(id: string, input: Partial<{ name: string; base: string | null; active: boolean }>): Promise<DutyLocation> {
  return (await api.patch<DutyLocation>(`/duty-config/locations/${id}`, input)).data;
}

export async function deleteLocation(id: string): Promise<void> {
  await api.delete(`/duty-config/locations/${id}`);
}

export async function listExemptionTypes(): Promise<ExemptionType[]> {
  return (await api.get<ExemptionType[]>("/duty-config/exemption-types")).data;
}
export async function createExemptionType(input: { name: string; description?: string | null; is_global?: boolean; is_medical?: boolean; is_commander_exemption?: boolean }): Promise<ExemptionType> {
  return (await api.post<ExemptionType>("/duty-config/exemption-types", input)).data;
}
export async function updateExemptionType(id: string, input: { is_medical?: boolean; is_global?: boolean; is_commander_exemption?: boolean; name?: string; active?: boolean }): Promise<ExemptionType> {
  return (await api.patch<ExemptionType>(`/duty-config/exemption-types/${id}`, input)).data;
}
export async function deleteExemptionType(id: string): Promise<void> {
  await api.delete(`/duty-config/exemption-types/${id}`);
}
export async function disableExemptionType(id: string, reason: string): Promise<{ revoked_count: number }> {
  return (await api.post<{ revoked_count: number }>(`/duty-config/exemption-types/${id}/disable`, { reason })).data;
}
export async function getExemptionDutyTypes(id: string): Promise<string[]> {
  return (await api.get<string[]>(`/duty-config/exemption-types/${id}/duty-types`)).data;
}
export async function getAllExemptionDutyTypeMaps(): Promise<Record<string, string[]>> {
  return (await api.get<Record<string, string[]>>("/duty-config/exemption-types/duty-type-map")).data;
}
export async function setExemptionDutyTypes(id: string, duty_type_ids: string[]): Promise<string[]> {
  return (await api.put<string[]>(`/duty-config/exemption-types/${id}/duty-types`, { duty_type_ids })).data;
}
export async function getAllExemptionDutyLocationMaps(): Promise<Record<string, string[]>> {
  return (await api.get<Record<string, string[]>>("/duty-config/exemption-types/duty-location-map")).data;
}
export async function setExemptionDutyLocations(id: string, duty_location_ids: string[]): Promise<string[]> {
  return (await api.put<string[]>(`/duty-config/exemption-types/${id}/duty-locations`, { duty_location_ids })).data;
}

export async function updateDutyTypeRequirements(
  id: string,
  requirements: DutyType["requirements"]
): Promise<DutyType> {
  return (await api.patch<DutyType>(`/duty-config/duty-types/${id}`, { requirements })).data;
}
