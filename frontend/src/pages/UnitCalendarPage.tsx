import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import UnitCalendar from "../components/UnitCalendar";
import { NodeDTO, fetchTree } from "../api/hierarchy";

export default function UnitCalendarPage() {
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [nodeId, setNodeId] = useState<string>("");

  useEffect(() => { void fetchTree().then((ns) => { setNodes(ns); if (ns[0]) setNodeId(ns[0].id); }); }, []);

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" data-testid="unit-calendar-page">
        <h2 className="text-xl font-semibold">{t("unit_calendar.title")}</h2>
        <select className="border rounded p-1" value={nodeId} onChange={(e) => setNodeId(e.target.value)} data-testid="unit-node-select">
          {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
        </select>
        {nodeId ? <UnitCalendar nodeId={nodeId} /> : <p data-testid="unit-calendar-empty">{t("unit_calendar.none")}</p>}
      </section>
    </Layout>
  );
}
