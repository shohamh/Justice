import { useEffect, useMemo, useState } from "react";
import Layout from "../../components/Layout";
import { getPotential, listModifiers, createModifier, deleteModifier, exportPotentialUrl, PotentialResult, PotentialModifierDTO } from "../../api/potential";
import { fetchFullTree, NodeDTO } from "../../api/hierarchy";

function flattenTree(nodes: NodeDTO[]): NodeDTO[] {
  const result: NodeDTO[] = [];
  function traverse(node: NodeDTO) {
    result.push(node);
    node.children?.forEach(traverse);
  }
  nodes.forEach(traverse);
  return result;
}

export default function PotentialPage() {
  const [treeNodes, setTreeNodes] = useState<NodeDTO[]>([]);
  const [rootId, setRootId] = useState<string | null>(null);
  const [referenceDate, setReferenceDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [results, setResults] = useState<Record<string, PotentialResult>>({});
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [modifiers, setModifiers] = useState<PotentialModifierDTO[]>([]);
  const [newReason, setNewReason] = useState("");
  const [newDelta, setNewDelta] = useState(0);

  const nodes = useMemo(() => flattenTree(treeNodes), [treeNodes]);

  useEffect(() => {
    fetchFullTree().then((tree) => {
      setTreeNodes(tree);
      if (tree.length > 0) setRootId(tree[0].id);
    });
  }, []);

  useEffect(() => {
    if (nodes.length === 0) return;
    Promise.allSettled(nodes.map((n) => getPotential(n.id, referenceDate))).then((all) => {
      const byId: Record<string, PotentialResult> = {};
      all.forEach((r, i) => {
        if (r.status === "fulfilled") {
          byId[nodes[i].id] = r.value;
        } else {
          console.error(`Failed to fetch potential for node ${nodes[i].id}:`, r.reason);
        }
      });
      setResults(byId);
    });
  }, [nodes, referenceDate]);

  useEffect(() => {
    if (selectedNodeId) listModifiers(selectedNodeId).then(setModifiers);
  }, [selectedNodeId]);

  async function handleAddModifier() {
    if (!selectedNodeId || !newReason.trim()) return;
    await createModifier({ hierarchy_node_id: selectedNodeId, delta: newDelta, reason: newReason, start_date: referenceDate });
    setModifiers(await listModifiers(selectedNodeId));
    setNewReason("");
    setNewDelta(0);
  }

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl">
        <h2 className="text-xl font-semibold">פוטנציאל</h2>
        <div className="flex gap-2 items-center">
          <label>תאריך ייחוס:</label>
          <input type="date" value={referenceDate} onChange={(e) => setReferenceDate(e.target.value)} className="border rounded p-1" />
          {rootId && (
            <a href={exportPotentialUrl(rootId, referenceDate)} className="text-blue-600 underline">
              ייצוא לאקסל
            </a>
          )}
        </div>
        <table className="w-full border-collapse" data-testid="potential-table">
          <thead>
            <tr>
              <th className="border p-2">יחידה</th>
              <th className="border p-2">כשירים</th>
              <th className="border p-2">התאמות</th>
              <th className="border p-2">פוטנציאל סופי</th>
            </tr>
          </thead>
          <tbody>
            {nodes.map((n) => {
              const r = results[n.id];
              return (
                <tr key={n.id} className="cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700" onClick={() => setSelectedNodeId(n.id)}>
                  <td className="border p-2">{n.name}</td>
                  <td className="border p-2">{r?.raw_eligible_count ?? "-"}</td>
                  <td className="border p-2">{r ? r.modifiers.reduce((s, m) => s + m.delta, 0) : "-"}</td>
                  <td className="border p-2">{r?.final_potential ?? "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {selectedNodeId && (
          <div className="border dark:border-gray-700 rounded p-3 space-y-2">
            <h3 className="font-semibold">פירוט וביקורת</h3>
            <ul>
              {results[selectedNodeId]?.soldiers.map((s) => (
                <li key={s.soldier_id}>
                  {s.full_name} — {s.counted ? "נספר" : `לא נספר (${s.reason})`}
                </li>
              ))}
            </ul>
            <h3 className="font-semibold">התאמות ידניות</h3>
            <ul>
              {modifiers.map((m) => (
                <li key={m.id}>
                  {m.delta > 0 ? "+" : ""}{m.delta} — {m.reason} ({m.start_date}
                  {m.end_date ? ` עד ${m.end_date}` : ""})
                  <button
                    className="text-red-600 mr-2"
                    onClick={async () => {
                      await deleteModifier(m.id);
                      setModifiers(await listModifiers(selectedNodeId));
                    }}
                  >
                    מחק
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex gap-2">
              <input type="number" value={newDelta} onChange={(e) => setNewDelta(Number(e.target.value))} className="border rounded p-1 w-20" />
              <input type="text" value={newReason} onChange={(e) => setNewReason(e.target.value)} placeholder="סיבה (חובה)" className="border rounded p-1 flex-1" />
              <button onClick={handleAddModifier} className="bg-blue-600 text-white rounded px-3 py-1">הוסף</button>
            </div>
          </div>
        )}
      </section>
    </Layout>
  );
}
