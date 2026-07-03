import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, X } from "lucide-react";
import Layout from "../../components/Layout";
import { DataTable, type ColDef } from "../../components/DataTable";
import { ExcelExportButton } from "../../components/ExcelExportButton";
import SoldierLink from "../../components/SoldierLink";
import {
  getPotential,
  listModifiers,
  createModifier,
  deleteModifier,
  PotentialResult,
  PotentialModifierDTO,
  SoldierPotentialDetail,
} from "../../api/potential";
import { fetchFullTree, NodeDTO } from "../../api/hierarchy";
import { useLevelTypes } from "../../hooks/useLevelTypes";
import { sortNodesByTree } from "../../utils/sortNodesByTree";

export default function PotentialPage() {
  const { t } = useTranslation();
  const { levelTypes } = useLevelTypes();
  const levelLabelByKey = useMemo(
    () => new Map(levelTypes.map((lt) => [lt.key, lt.label])),
    [levelTypes],
  );
  const [treeNodes, setTreeNodes] = useState<NodeDTO[]>([]);
  const [referenceDate, setReferenceDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [results, setResults] = useState<Record<string, PotentialResult>>({});
  const [expandedNodeId, setExpandedNodeId] = useState<string | null>(null);
  const [modifiers, setModifiers] = useState<PotentialModifierDTO[]>([]);
  const [newReason, setNewReason] = useState("");
  const [newDelta, setNewDelta] = useState(0);
  const [exportRows, setExportRows] = useState<NodeDTO[]>([]);

  const nodes = useMemo(() => sortNodesByTree(treeNodes).map((n) => n.node), [treeNodes]);

  useEffect(() => {
    fetchFullTree().then(setTreeNodes);
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
    if (expandedNodeId) listModifiers(expandedNodeId).then(setModifiers);
  }, [expandedNodeId]);

  async function handleAddModifier() {
    if (!expandedNodeId || !newReason.trim()) return;
    await createModifier({ hierarchy_node_id: expandedNodeId, delta: newDelta, reason: newReason, start_date: referenceDate });
    setModifiers(await listModifiers(expandedNodeId));
    setNewReason("");
    setNewDelta(0);
  }

  function modifierSum(r: PotentialResult | undefined): number {
    return r ? r.modifiers.reduce((s, m) => s + m.delta, 0) : 0;
  }

  function pctOfParentValue(n: NodeDTO): number | null {
    if (!n.parent_id) return null;
    const parentFinal = results[n.parent_id]?.final_potential;
    const ownFinal = results[n.id]?.final_potential;
    if (parentFinal === undefined || ownFinal === undefined || parentFinal === 0) return null;
    return (ownFinal / parentFinal) * 100;
  }

  function pctOfParentText(n: NodeDTO): string {
    const pct = pctOfParentValue(n);
    return pct === null ? "—" : `${pct.toFixed(0)}%`;
  }

  function toggleExpanded(nodeId: string) {
    setExpandedNodeId((prev) => (prev === nodeId ? null : nodeId));
  }

  function reasonLabel(reason: string | null): string {
    if (!reason) return "";
    return t(`potential.reason_${reason}`, { defaultValue: reason });
  }

  function reasonText(s: SoldierPotentialDetail): string {
    if (s.counted) return "";
    if (s.reason === "exempted") {
      return s.exemption_names && s.exemption_names.length > 0
        ? s.exemption_names.join(", ")
        : t("potential.reason_exempted_restricted");
    }
    return reasonLabel(s.reason);
  }

  const cols: ColDef<NodeDTO>[] = [
    {
      id: "name",
      header: t("potential.node"),
      cell: (n) => (
        <span className="flex items-center gap-2" style={{ paddingRight: (n.path_ids.length - 1) * 16 }}>
          <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300 shrink-0">
            {levelLabelByKey.get(n.level) ?? n.level}
          </span>
          <span>{n.name}</span>
        </span>
      ),
      sortValue: (n) => n.name,
      filterValue: (n) => n.name,
    },
    {
      id: "eligible",
      header: t("potential.eligible"),
      headerTooltip: t("potential.eligible_tooltip"),
      cell: (n) => results[n.id]?.raw_eligible_count ?? "-",
      sortValue: (n) => results[n.id]?.raw_eligible_count ?? -1,
    },
    {
      id: "modifiers",
      header: t("potential.modifiers"),
      headerTooltip: t("potential.modifiers_tooltip"),
      cell: (n) => (results[n.id] ? modifierSum(results[n.id]) : "-"),
      sortValue: (n) => (results[n.id] ? modifierSum(results[n.id]) : -Infinity),
    },
    {
      id: "final_potential",
      header: t("potential.final_potential"),
      headerTooltip: t("potential.final_potential_tooltip"),
      cell: (n) => results[n.id]?.final_potential ?? "-",
      sortValue: (n) => results[n.id]?.final_potential ?? -1,
    },
    {
      id: "pct_of_parent",
      header: t("potential.pct_of_parent"),
      headerTooltip: t("potential.pct_of_parent_tooltip"),
      cell: (n) => pctOfParentText(n),
      sortValue: (n) => pctOfParentValue(n) ?? -Infinity,
      exportValue: (n) => {
        const pct = pctOfParentValue(n);
        return pct === null ? "" : Math.round(pct);
      },
    },
  ];

  const soldierCols: ColDef<SoldierPotentialDetail>[] = [
    {
      id: "name",
      header: t("potential.soldier_name"),
      cell: (s) => <SoldierLink id={s.soldier_id} name={s.full_name} />,
      sortValue: (s) => s.full_name,
      filterValue: (s) => s.full_name,
    },
    {
      id: "rank",
      header: t("potential.rank_col"),
      cell: (s) => s.rank ?? "—",
      sortValue: (s) => s.rank ?? "",
      filterValue: (s) => s.rank ?? "",
    },
    {
      id: "counted",
      header: t("potential.counted_col"),
      cell: (s) =>
        s.counted ? (
          <span
            className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400"
            title={t("potential.counted")}
          >
            <Check size={14} aria-label={t("potential.counted")} />
          </span>
        ) : (
          <span
            className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400"
            title={t("potential.not_counted_short")}
          >
            <X size={14} aria-label={t("potential.not_counted_short")} />
          </span>
        ),
      sortValue: (s) => (s.counted ? 1 : 0),
      columnFilter: true,
      filterValue: (s) => (s.counted ? t("potential.counted") : t("potential.not_counted_short")),
    },
    {
      id: "reason",
      header: t("potential.reason_col"),
      cell: (s) => (s.counted ? "—" : reasonText(s)),
      filterValue: (s) => reasonText(s),
    },
  ];

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl">
        <h2 className="text-xl font-semibold">{t("potential.title")}</h2>
        <div className="flex gap-2 items-center">
          <label>{t("potential.reference_date")}:</label>
          <input type="date" value={referenceDate} onChange={(e) => setReferenceDate(e.target.value)} className="border rounded p-1" />
        </div>

        <div className="flex justify-start" dir="ltr">
          <ExcelExportButton columns={cols} rows={exportRows} filename="potential.xlsx" />
        </div>
        <DataTable
          columns={cols}
          data={nodes}
          filterPlaceholder={t("table.filter_placeholder")}
          rowClassName={(n) => (n.id === expandedNodeId ? "bg-indigo-50 dark:bg-indigo-950" : "")}
          testId="potential-table"
          onVisibleRowsChange={setExportRows}
          expandable={{
            isExpanded: (n) => n.id === expandedNodeId,
            onToggle: (n) => toggleExpanded(n.id),
            content: (n) => (
              <div className="p-2">
                <DataTable
                  columns={soldierCols}
                  data={results[n.id]?.soldiers ?? []}
                  filterPlaceholder={t("table.filter_placeholder")}
                  emptyMessage={t("potential.no_soldiers")}
                  testId={`potential-soldiers-table-${n.id}`}
                />
              </div>
            ),
          }}
        />

        {expandedNodeId && (
          <div className="border dark:border-gray-700 rounded p-3 space-y-2">
            <h3 className="font-semibold">{t("potential.manual_modifiers_title")}</h3>
            <ul>
              {modifiers.map((m) => (
                <li key={m.id}>
                  {m.delta > 0 ? "+" : ""}{m.delta} — {m.reason} ({m.start_date}
                  {m.end_date ? ` ${t("potential.modifier_until")} ${m.end_date}` : ""})
                  <button
                    className="text-red-600 mr-2"
                    onClick={async () => {
                      await deleteModifier(m.id);
                      setModifiers(await listModifiers(expandedNodeId));
                    }}
                  >
                    {t("potential.modifier_delete")}
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex gap-2">
              <input type="number" value={newDelta} onChange={(e) => setNewDelta(Number(e.target.value))} className="border rounded p-1 w-20" />
              <input
                type="text"
                value={newReason}
                onChange={(e) => setNewReason(e.target.value)}
                placeholder={t("potential.modifier_reason_placeholder")}
                className="border rounded p-1 flex-1"
              />
              <button onClick={handleAddModifier} className="bg-blue-600 text-white rounded px-3 py-1">
                {t("potential.modifier_add")}
              </button>
            </div>
          </div>
        )}
      </section>
    </Layout>
  );
}
