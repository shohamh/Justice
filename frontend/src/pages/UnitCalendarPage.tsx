import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import UnitCalendar from "../components/UnitCalendar";
import { fetchFullTree, NodeDTO } from "../api/hierarchy";
import { useAuth } from "../auth/AuthContext";

function treeOrder(nodes: NodeDTO[]): NodeDTO[] {
  const ids = new Set(nodes.map((n) => n.id));
  const byParent = new Map<string | null, NodeDTO[]>();
  for (const n of nodes) {
    // Treat node as a root if its parent isn't in this list (e.g. soldier who only gets their own node)
    const key = n.parent_id && ids.has(n.parent_id) ? n.parent_id : null;
    byParent.set(key, [...(byParent.get(key) ?? []), n]);
  }
  const result: NodeDTO[] = [];
  function walk(parentId: string | null) {
    for (const n of byParent.get(parentId) ?? []) {
      result.push(n);
      walk(n.id);
    }
  }
  walk(null);
  return result;
}

export default function UnitCalendarPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  // Start with the user's own node immediately so UnitCalendar can fetch in
  // parallel with the tree, instead of waiting for the tree fetch to complete.
  const [nodeId, setNodeId] = useState<string>(() => user?.hierarchy_node_id ?? "");

  useEffect(() => {
    void fetchFullTree().then((ns) => {
      const ordered = treeOrder(ns);
      setNodes(ordered);
      if (!nodeId) {
        const preferred = user?.hierarchy_node_id
          ? ordered.find((n) => n.id === user.hierarchy_node_id)
          : null;
        setNodeId((preferred ?? ordered[0])?.id ?? "");
      }
    });
  }, [user]); // eslint-disable-line react-hooks/exhaustive-deps

  const indentLabel = useMemo(() => {
    const depthMap = new Map<string, number>();
    for (const n of nodes) {
      depthMap.set(n.id, (n.path_ids?.length ?? 1) - 1);
    }
    return (n: NodeDTO) => "  ".repeat(depthMap.get(n.id) ?? 0) + n.name;
  }, [nodes]);

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" data-testid="unit-calendar-page">
        <h2 className="text-xl font-semibold">{t("unit_calendar.title")}</h2>
        <select
          className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          value={nodeId}
          onChange={(e) => setNodeId(e.target.value)}
          data-testid="unit-node-select"
        >
          {nodes.map((n) => (
            <option key={n.id} value={n.id}>{indentLabel(n)}</option>
          ))}
        </select>
        {nodeId ? <UnitCalendar nodeId={nodeId} /> : <p data-testid="unit-calendar-empty">{t("unit_calendar.none")}</p>}
      </section>
    </Layout>
  );
}
