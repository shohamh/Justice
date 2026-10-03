import axios from "axios";

import { api } from "./client";
import {
  isRecord,
  optionalArrayResponse,
  requiredArrayResponse,
  requiredObjectResponse,
} from "./responseGuards";

export interface DutyManagerEntry {
  scope_id: string;
  soldier_id: string;
  name: string;
}

export interface NodeDTO {
  id: string;
  level: "corps" | "division" | "unit" | "department" | "branch" | "group" | "team";
  name: string;
  parent_id: string | null;
  commander_id: string | null;
  commander_name: string | null;
  path_ids: string[];
  duty_managers: DutyManagerEntry[];
  dm_manageable: boolean;
  can_edit: boolean;
  has_children?: boolean;
  has_soldiers?: boolean;
  children?: NodeDTO[];
}

export type HierarchyNodeSummaryDTO = Pick<NodeDTO, "id" | "level" | "name">;

export interface MyCommandScopeDTO {
  commanded_nodes: HierarchyNodeSummaryDTO[];
  assigned_node: HierarchyNodeSummaryDTO | null;
}

export interface NodeBranchPageDTO {
  items: NodeDTO[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface HierarchySearchMatchDTO {
  node: NodeDTO;
  path: NodeDTO[];
}

export interface HierarchySearchDTO {
  matches: HierarchySearchMatchDTO[];
  has_more: boolean;
}

export async function fetchHierarchyBranchPage(request: {
  parentId: string | null;
  cursor?: string;
  signal?: AbortSignal;
}): Promise<NodeBranchPageDTO> {
  const params: Record<string, string> = {};
  if (request.parentId) params.parent_id = request.parentId;
  if (request.cursor) params.cursor = request.cursor;
  const payload = requiredObjectResponse(
    (await api.get<unknown>("/hierarchy/branches", { params, signal: request.signal })).data,
    "Invalid hierarchy branch response",
  );
  const items = requiredArrayResponse<NodeDTO>(payload.items, "Invalid hierarchy branch items");
  if (typeof payload.has_more !== "boolean") {
    throw new Error("Invalid hierarchy paging state");
  }
  if (payload.next_cursor !== null && typeof payload.next_cursor !== "string") {
    throw new Error("Invalid hierarchy cursor");
  }
  return { items, has_more: payload.has_more, next_cursor: payload.next_cursor };
}

export async function searchHierarchyNodes(
  query: string,
  signal?: AbortSignal,
): Promise<HierarchySearchDTO> {
  const payload = requiredObjectResponse(
    (await api.get<unknown>("/hierarchy/search", { params: { q: query }, signal })).data,
    "Invalid hierarchy search response",
  );
  if (typeof payload.has_more !== "boolean") {
    throw new Error("Invalid hierarchy search state");
  }
  const rawMatches = requiredArrayResponse<unknown>(payload.matches, "Invalid hierarchy search matches");
  const matches = rawMatches.map((value) => {
    const match = requiredObjectResponse(value, "Invalid hierarchy search match");
    return {
      node: requiredObjectResponse(match.node, "Invalid hierarchy search node") as unknown as NodeDTO,
      path: requiredArrayResponse<NodeDTO>(match.path, "Invalid hierarchy search path"),
    };
  });
  return { matches, has_more: payload.has_more };
}

export function isStaleHierarchyCursorError(error: unknown): boolean {
  return (
    axios.isAxiosError(error) &&
    error.response?.status === 409 &&
    isRecord(error.response.data) &&
    error.response.data.detail === "stale_cursor"
  );
}

export async function fetchTree(): Promise<NodeDTO[]> {
  const data = (await api.get<unknown>("/hierarchy/tree")).data;
  return optionalArrayResponse<NodeDTO>(data);
}

export async function fetchFullTree(): Promise<NodeDTO[]> {
  const data = (await api.get<unknown>("/hierarchy/tree", { params: { all: true } })).data;
  return optionalArrayResponse<NodeDTO>(data);
}

/** Rejects malformed hierarchy payloads so a complete export cannot look empty. */
export async function fetchFullTreeForExport(): Promise<NodeDTO[]> {
  const data = (await api.get<unknown>("/hierarchy/tree", { params: { all: true } })).data;
  return requiredArrayResponse<unknown>(data, "Invalid hierarchy tree response").map(parseHierarchyTreeNodeForExport);
}

function parseHierarchyTreeNodeForExport(value: unknown): NodeDTO {
  const node = requiredObjectResponse(value, "Invalid hierarchy tree node response");
  if (
    typeof node.id !== "string" ||
    typeof node.name !== "string" ||
    (node.parent_id !== null && typeof node.parent_id !== "string") ||
    !Array.isArray(node.path_ids) ||
    !node.path_ids.every((id: unknown) => typeof id === "string") ||
    (node.children !== undefined && !Array.isArray(node.children))
  ) {
    throw new Error("Invalid hierarchy tree node response");
  }
  if (Array.isArray(node.children)) {
    node.children.forEach(parseHierarchyTreeNodeForExport);
  }
  return node as unknown as NodeDTO;
}

function parseHierarchyNodeSummary(value: unknown): HierarchyNodeSummaryDTO {
  const summary = requiredObjectResponse(value, "Invalid hierarchy node summary");
  if (
    typeof summary.id !== "string" ||
    typeof summary.level !== "string" ||
    typeof summary.name !== "string"
  ) {
    throw new Error("Invalid hierarchy node summary");
  }
  return { id: summary.id, level: summary.level as NodeDTO["level"], name: summary.name };
}

export async function fetchMyCommandScope(): Promise<MyCommandScopeDTO> {
  const payload = requiredObjectResponse(
    (await api.get<unknown>("/hierarchy/my-command-scope")).data,
    "Invalid hierarchy command scope response",
  );
  const commandedNodes = requiredArrayResponse<unknown>(
    payload.commanded_nodes,
    "Invalid hierarchy commanded nodes",
  ).map(parseHierarchyNodeSummary);
  const assignedNode =
    payload.assigned_node === null
      ? null
      : parseHierarchyNodeSummary(payload.assigned_node);
  return { commanded_nodes: commandedNodes, assigned_node: assignedNode };
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
