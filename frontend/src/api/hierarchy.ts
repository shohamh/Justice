import { api } from "./client";

export interface NodeDTO {
  id: string;
  level: "corps" | "division" | "unit" | "department" | "branch" | "group" | "team";
  name: string;
  parent_id: string | null;
  commander_id: string | null;
  commander_name: string | null;
  path_ids: string[];
  children?: NodeDTO[];
}

export async function fetchTree(): Promise<NodeDTO[]> {
  return (await api.get<NodeDTO[]>("/hierarchy/tree")).data;
}

export async function fetchFullTree(): Promise<NodeDTO[]> {
  return (await api.get<NodeDTO[]>("/hierarchy/tree", { params: { all: true } })).data;
}

export async function createNode(input: {
  level: string;
  name: string;
  parent_id: string | null;
}): Promise<NodeDTO> {
  return (await api.post<NodeDTO>("/hierarchy/nodes", input)).data;
}

export async function renameNode(id: string, name: string): Promise<NodeDTO> {
  return (await api.patch<NodeDTO>(`/hierarchy/nodes/${id}`, { name })).data;
}

export async function moveNode(id: string, new_parent_id: string | null): Promise<NodeDTO> {
  return (await api.post<NodeDTO>(`/hierarchy/nodes/${id}/move`, { new_parent_id })).data;
}

export async function updateNode(id: string, input: { name?: string; commander_id?: string | null; level?: string }): Promise<NodeDTO> {
  return (await api.patch<NodeDTO>(`/hierarchy/nodes/${id}`, input)).data;
}

export async function deleteNode(id: string): Promise<void> {
  await api.delete(`/hierarchy/nodes/${id}`);
}
