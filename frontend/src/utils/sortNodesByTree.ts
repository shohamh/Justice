import type { NodeDTO } from "../api/hierarchy";

/**
 * Returns a flat list of nodes sorted by DFS tree traversal order.
 * Each entry includes the original node plus its depth in the hierarchy.
 */
export interface NodeWithDepth {
  node: NodeDTO;
  depth: number;
}

export function sortNodesByTree(nodes: NodeDTO[]): NodeWithDepth[] {
  const byParent = new Map<string | null, NodeDTO[]>();
  for (const n of nodes) {
    const key = n.parent_id ?? null;
    byParent.set(key, [...(byParent.get(key) ?? []), n]);
  }
  const result: NodeWithDepth[] = [];
  function walk(parentId: string | null, depth: number) {
    for (const n of byParent.get(parentId) ?? []) {
      result.push({ node: n, depth });
      walk(n.id, depth + 1);
    }
  }
  walk(null, 0);
  return result;
}

/** Convenience: returns indented label for use inside <option> elements. */
export function indentedNodeLabel(node: NodeDTO, depth: number): string {
  return "  ".repeat(depth) + node.name;
}
