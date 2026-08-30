import { api } from "./client";

export interface LevelTypeDTO {
  id: string;
  key: string;
  label: string;
  rank: number;
}

export async function listLevelTypes(): Promise<LevelTypeDTO[]> {
  const data = (await api.get<LevelTypeDTO[]>("/hierarchy/level-types")).data;
  return Array.isArray(data) ? data : [];
}

export async function createLevelType(key: string, label: string): Promise<LevelTypeDTO> {
  return (await api.post<LevelTypeDTO>("/hierarchy/level-types", { key, label })).data;
}

export async function reorderLevelTypes(orderedIds: string[]): Promise<LevelTypeDTO[]> {
  return (await api.put<LevelTypeDTO[]>("/hierarchy/level-types/reorder", { ordered_ids: orderedIds })).data;
}

export async function deleteLevelType(id: string): Promise<void> {
  await api.delete(`/hierarchy/level-types/${id}`);
}
