import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import Combobox from "../components/Combobox";
import Layout from "../components/Layout";
import UnitCalendar from "../components/UnitCalendar";
import { fetchFullTree, NodeDTO } from "../api/hierarchy";
import { useAuth } from "../auth/AuthContext";

function treeOrder(nodes: NodeDTO[]): NodeDTO[] {
  const ids = new Set(nodes.map((n) => n.id));
  const byParent = new Map<string | null, NodeDTO[]>();
  for (const n of nodes) {
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

function buildDepthMap(nodes: NodeDTO[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const n of nodes) {
    map.set(n.id, (n.path_ids?.length ?? 1) - 1);
  }
  return map;
}

export default function UnitCalendarPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [nodeId, setNodeId] = useState<string>("");

  useEffect(() => {
    void fetchFullTree().then((ns) => {
      const ordered = treeOrder(ns);
      setNodes(ordered);
      if (!nodeId) {
        const root = ordered.find((n) => n.level === "corps") ?? ordered[0];
        setNodeId(root?.id ?? "");
      }
    });
  }, [user]); // eslint-disable-line react-hooks/exhaustive-deps

  const depthMap = useMemo(() => buildDepthMap(nodes), [nodes]);

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" data-testid="unit-calendar-page">
        <h2 className="text-xl font-semibold">{t("unit_calendar.title")}</h2>
        <div className="w-72">
          <Combobox
            items={nodes.map((n) => ({ id: n.id, name: n.name, depth: depthMap.get(n.id) ?? 0 }))}
            value={nodeId}
            onChange={setNodeId}
          />
        </div>
        {nodeId ? <UnitCalendar nodeId={nodeId} /> : <p data-testid="unit-calendar-empty">{t("unit_calendar.none")}</p>}
      </section>
    </Layout>
  );
}
