import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { CalRow, getUnitCalendar } from "../api/calendar";
import { NodeDTO, fetchTree } from "../api/hierarchy";

export default function UnitCalendarPage() {
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [nodeId, setNodeId] = useState<string>("");
  const [rows, setRows] = useState<CalRow[]>([]);

  useEffect(() => { void fetchTree().then((ns) => { setNodes(ns); if (ns[0]) setNodeId(ns[0].id); }); }, []);
  useEffect(() => { if (nodeId) void getUnitCalendar(nodeId).then(setRows); }, [nodeId]);

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" data-testid="unit-calendar-page">
        <h2 className="text-xl font-semibold">{t("unit_calendar.title")}</h2>
        <select className="border rounded p-1" value={nodeId} onChange={(e) => setNodeId(e.target.value)} data-testid="unit-node-select">
          {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
        </select>
        {rows.length === 0 ? (
          <p data-testid="unit-calendar-empty">{t("unit_calendar.none")}</p>
        ) : (
          <table className="w-full text-sm text-right" data-testid="unit-calendar-table">
            <thead>
              <tr className="border-b">
                <th className="p-1">{t("unit_calendar.soldier")}</th>
                <th className="p-1">{t("unit_calendar.duties")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.soldier_id} data-testid={`unit-row-${r.soldier_id}`}>
                  <td className="p-1">{r.full_name}</td>
                  <td className="p-1">
                    {r.assignments.map((a) => `${a.start_date}→${a.end_date}`).join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </Layout>
  );
}
