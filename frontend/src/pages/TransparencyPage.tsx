import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { Breakdown, TransparencyRow, getBreakdown, getTransparency, downloadTransparencyExport, downloadSubUnitsExport } from "../api/scoring";
import { DataTable, type ColDef } from "../components/DataTable";
import SoldierLink from "../components/SoldierLink";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import TabBar from "../components/TabBar";

// ─── tree helpers ────────────────────────────────────────────────────────────

function flattenTree(nodes: NodeDTO[]): NodeDTO[] {
  const result: NodeDTO[] = [];
  function traverse(node: NodeDTO) {
    result.push(node);
    node.children?.forEach(traverse);
  }
  nodes.forEach(traverse);
  return result;
}

function TreeNode({
  node, selectedId, onSelect, depth,
}: {
  node: NodeDTO; selectedId: string | null; onSelect: (id: string) => void; depth: number;
}) {
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = (node.children?.length ?? 0) > 0;
  const isSelected = node.id === selectedId;
  return (
    <div>
      <div className="flex items-center gap-1 py-0.5 rounded" style={{ paddingRight: `${depth * 14 + 4}px` }}>
        <button
          className={`w-4 text-gray-400 text-[10px] ${hasChildren ? "visible" : "invisible"}`}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "▼" : "▶"}
        </button>
        <button
          className={`text-sm px-1.5 py-0.5 rounded text-right w-full ${
            isSelected
              ? "bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300 font-medium"
              : "hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-900 dark:text-white"
          }`}
          onClick={() => onSelect(node.id)}
        >
          {node.name}
        </button>
      </div>
      {open && hasChildren && node.children?.map((child) => (
        <TreeNode key={child.id} node={child} selectedId={selectedId} onSelect={onSelect} depth={depth + 1} />
      ))}
    </div>
  );
}

// ─── rank ordering ───────────────────────────────────────────────────────────

const RANK_ORDER: Record<string, number> = {
  // Enlisted (with and without geresh)
  "טוראי": 1,
  'רב"ט': 2, "רבט": 2,
  "סמל": 3,
  'סמ"ר': 4, "סמר": 4,
  'רס"ל': 5, "רסל": 5,
  'רס"ר': 6, "רסר": 6,
  'רס"מ': 7, "רסמ": 7,
  'רס"ב': 8, "רסב": 8,
  "רנג": 9,
  // Officers
  "קמא": 10,
  "סגמ": 11,
  "סגן": 12,
  "קאב": 13,
  "סרן": 14,
  'רס"ן': 15, "רסן": 15,
  'סא"ל': 16, "סאל": 16,
  'אל"מ': 17, "אלמ": 17,
  'תא"ל': 18, "תאל": 18,
  "אלוף": 19,
  "רב אלוף": 20,
};

// ─── filter pills ─────────────────────────────────────────────────────────────

type OfficerFilter = "all" | "officer" | "enlisted";
type ServiceFilter = "all" | "חובה" | "קבע";

function FilterPills<T extends string>({
  value, onChange, options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <div className="flex gap-1 flex-wrap" dir="rtl">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`px-3 py-1 rounded-full text-sm border transition-colors ${
            value === o.value
              ? "bg-indigo-600 text-white border-indigo-600"
              : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-gray-300 dark:border-gray-600 hover:border-indigo-400"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ─── sub-hierarchy row type ───────────────────────────────────────────────────

interface SubRow {
  node_id: string;
  node_name: string;
  depth: number;
  count: number;
  active_count: number;
  avg_cumulative: number;
  avg_cumulative_active: number;
  total_score_per_day: number;
  avg_active_days: number;
  avg_normalised: number;
}

// ─── main page ────────────────────────────────────────────────────────────────

export default function TransparencyPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [rows, setRows] = useState<TransparencyRow[]>([]);
  const [breakdown, setBreakdown] = useState<Breakdown | null>(null);
  const [breakdownOpen, setBreakdownOpen] = useState(false);
  const [treeNodes, setTreeNodes] = useState<NodeDTO[]>([]);
  const [treeOpen, setTreeOpen] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [tab, setTab] = useState(0);
  const [officerFilter, setOfficerFilter] = useState<OfficerFilter>("all");
  const [serviceFilter, setServiceFilter] = useState<ServiceFilter>("all");

  useEffect(() => { void getTransparency().then(setRows); }, []);
  useEffect(() => { void fetchTree().then(setTreeNodes); }, []);

  async function toggleOwn() {
    if (!breakdownOpen && user) setBreakdown(await getBreakdown(user.id));
    setBreakdownOpen((o) => !o);
  }

  // ── flat node list & lookup map ──
  const flatNodes = useMemo(() => flattenTree(treeNodes), [treeNodes]);

  const nodePathsMap = useMemo(() => {
    const map = new Map<string, string[]>();
    flatNodes.forEach((n) => map.set(n.id, n.path_ids));
    return map;
  }, [flatNodes]);

  const selectedNodeName = useMemo(
    () => flatNodes.find((n) => n.id === selectedNodeId)?.name ?? null,
    [flatNodes, selectedNodeId],
  );

  // ── soldiers tab: filter to selected subtree ──
  const subtreeIds = useMemo((): Set<string> | null => {
    if (!selectedNodeId) return null;
    return new Set(flatNodes.filter((n) => n.path_ids.includes(selectedNodeId)).map((n) => n.id));
  }, [selectedNodeId, flatNodes]);

  const visibleRows = useMemo(() => {
    let filtered = subtreeIds
      ? rows.filter((r) => r.node_id != null && subtreeIds.has(r.node_id))
      : rows;
    if (officerFilter === "officer") filtered = filtered.filter((r) => r.is_officer);
    if (officerFilter === "enlisted") filtered = filtered.filter((r) => !r.is_officer);
    if (serviceFilter !== "all") filtered = filtered.filter((r) => r.service_type === serviceFilter);
    // Stamp stable row numbers + pre-computed rank order so sortValue is a plain property lookup
    return filtered.map((r, i) => ({
      ...r,
      _row_num: i + 1,
      _rank_order: r.rank ? (RANK_ORDER[r.rank] ?? 999) : 999,
    }));
  }, [rows, subtreeIds, officerFilter, serviceFilter]);

  // ── sub-hierarchy tab: build children map from parent_id (API returns flat list) ──
  const subRows = useMemo((): SubRow[] => {
    const result: SubRow[] = [];
    const avg = (vals: number[]) => vals.reduce((a, b) => a + b, 0) / vals.length;
    const childrenMap = new Map<string | null, NodeDTO[]>();
    for (const node of flatNodes) {
      const key = node.parent_id ?? null;
      if (!childrenMap.has(key)) childrenMap.set(key, []);
      childrenMap.get(key)!.push(node);
    }
    function traverse(parentId: string | null) {
      for (const node of childrenMap.get(parentId) ?? []) {
        const nodeRows = rows.filter(
          (r) => r.node_id != null && nodePathsMap.get(r.node_id)?.includes(node.id),
        );
        if (nodeRows.length > 0) {
          result.push({
            node_id: node.id,
            node_name: node.name,
            depth: node.path_ids.length - 1,
            count: nodeRows.length,
            active_count: nodeRows.filter((r) => Number(r.cumulative_score) > 0).length,
            avg_cumulative: avg(nodeRows.map((r) => Number(r.cumulative_score))),
            avg_cumulative_active: (() => {
              const active = nodeRows.filter((r) => Number(r.cumulative_score) > 0);
              return active.length > 0 ? avg(active.map((r) => Number(r.cumulative_score))) : 0;
            })(),
            total_score_per_day: nodeRows.reduce((s, r) => s + Number(r.score_per_day), 0),
            avg_active_days: Math.round(avg(nodeRows.map((r) => r.active_days))),
            avg_normalised: avg(nodeRows.map((r) => Number(r.normalised_score))),
          });
        }
        traverse(node.id);
      }
    }
    traverse(null);
    return result;
  }, [flatNodes, nodePathsMap, rows]);

  // ── summary stats (reflect current tab's visible data) ──
  const statsRows = tab === 0 ? visibleRows : null;
  const avgCumulative = statsRows
    ? statsRows.length === 0 ? 0 : statsRows.reduce((s, r) => s + Number(r.cumulative_score), 0) / statsRows.length
    : subRows.length === 0 ? 0 : subRows.reduce((s, r) => s + r.avg_cumulative, 0) / subRows.length;
  const avgActiveDays = statsRows
    ? statsRows.length === 0 ? 0 : Math.round(statsRows.reduce((s, r) => s + r.active_days, 0) / statsRows.length)
    : subRows.length === 0 ? 0 : Math.round(subRows.reduce((s, r) => s + r.avg_active_days, 0) / subRows.length);
  const avgScorePerDay = statsRows
    ? statsRows.length === 0 ? 0 : statsRows.reduce((s, r) => s + Number(r.score_per_day), 0) / statsRows.length
    : subRows.length === 0 ? 0 : subRows.reduce((s, r) => s + r.avg_score_per_day, 0) / subRows.length;
  const avgNormalised = statsRows
    ? statsRows.length === 0 ? 0 : statsRows.reduce((s, r) => s + Number(r.normalised_score), 0) / statsRows.length
    : subRows.length === 0 ? 0 : subRows.reduce((s, r) => s + r.avg_normalised, 0) / subRows.length;

  function handleSelectNode(id: string) {
    setSelectedNodeId((prev) => (prev === id ? null : id));
    setTreeOpen(false);
  }

  function clearFilter() {
    setSelectedNodeId(null);
    setTreeOpen(false);
  }

  // ── soldiers columns ──
  type NumberedRow = TransparencyRow & { _row_num: number; _rank_order: number };
  const soldierCols: ColDef<NumberedRow>[] = [
    {
      id: "num", header: "#",
      cell: (r) => r._row_num,
      sortValue: (r) => r._row_num,
    },
    {
      id: "name", header: t("transparency.name"),
      cell: (r) => r.soldier_id === user?.id
        ? <button className="text-indigo-600 dark:text-indigo-400" onClick={toggleOwn} data-testid="own-row-toggle">{r.full_name}</button>
        : <SoldierLink id={r.soldier_id} name={r.full_name} />,
      sortValue: (r) => r.full_name, filterValue: (r) => r.full_name,
    },
    {
      id: "unit", header: t("transparency.unit"),
      cell: (r) => r.node_name ?? "—",
      sortValue: (r) => r.node_name ?? "", filterValue: (r) => r.node_name ?? "",
    },
    { id: "enrolled_at", header: t("transparency.enrolled_at"), cell: (r) => r.enrolled_at, sortValue: (r) => r.enrolled_at },
    { id: "active_days", header: t("transparency.active_days"), cell: (r) => r.active_days, sortValue: (r) => r.active_days },
    {
      id: "rank", header: t("transparency.rank"),
      cell: (r) => r.rank ?? "—",
      sortValue: (r) => r._rank_order,
      filterValue: (r) => r.rank ?? "",
      columnFilter: true,
    },
    {
      id: "shift_count", header: t("transparency.shift_count"),
      headerTooltip: t("transparency.shift_count_tooltip"),
      cell: (r) => r.shift_count,
      sortValue: (r) => r.shift_count,
    },
    { id: "cumulative", header: t("transparency.cumulative"), cell: (r) => r.cumulative_score, sortValue: (r) => Number(r.cumulative_score) },
    {
      id: "score_per_day", header: t("transparency.score_per_day"),
      headerTooltip: `${t("transparency.score_per_day_modal_title")}\n\n${t("transparency.score_per_day_modal_body")}`,
      cell: (r) => { const n = Number(r.score_per_day); return isNaN(n) ? r.score_per_day : n.toFixed(3); },
      sortValue: (r) => Number(r.score_per_day),
    },
    {
      id: "normalised", header: t("transparency.normalised"),
      headerTooltip: t("transparency.normalised_tooltip"),
      cell: (r) => { const n = Number(r.normalised_score); return isNaN(n) ? r.normalised_score : n.toFixed(3); },
      sortValue: (r) => Number(r.normalised_score),
    },
  ];

  // ── sub-hierarchy columns ──
  const subCols: ColDef<SubRow>[] = [
    {
      id: "name", header: "יחידה",
      cell: (r) => (
        <span className="flex items-center" style={{ paddingRight: `${r.depth * 16}px` }}>
          {r.depth > 0 && <span className="text-gray-300 dark:text-gray-600 ml-1 text-xs">{"└"}</span>}
          <button
            className="text-indigo-600 dark:text-indigo-400 hover:underline text-right"
            onClick={() => { setSelectedNodeId(r.node_id); setTab(0); }}
          >
            {r.node_name}
          </button>
        </span>
      ),
      sortValue: (r) => r.node_name, filterValue: (r) => r.node_name,
    },
    { id: "count", header: "כמות חיילים", cell: (r) => r.count, sortValue: (r) => r.count },
    { id: "active_count", header: "חיילים פעילים", cell: (r) => `${r.active_count} (${Math.round(r.active_count / r.count * 100)}%)`, sortValue: (r) => r.active_count },
    { id: "avg_active_days", header: t("transparency.avg_active_days"), cell: (r) => r.avg_active_days, sortValue: (r) => r.avg_active_days },
    { id: "avg_cumulative", header: "ממוצע ניקוד לחייל", cell: (r) => r.avg_cumulative.toFixed(2), sortValue: (r) => r.avg_cumulative },
    { id: "avg_cumulative_active", header: "ממוצע ניקוד לחייל פעיל", cell: (r) => r.avg_cumulative_active > 0 ? r.avg_cumulative_active.toFixed(2) : "—", sortValue: (r) => r.avg_cumulative_active },
    {
      id: "total_score_per_day", header: "ניקוד ליום (מסגרת)",
      headerTooltip: "סך ניקוד ליום של כל חיילי המסגרת — מייצג את עומס התורנויות הכולל של היחידה.",
      cell: (r) => (
        <span className={r.total_score_per_day > 0.3 * r.count ? "text-red-600 dark:text-red-400 font-medium" : ""}>
          {r.total_score_per_day.toFixed(2)}
        </span>
      ),
      sortValue: (r) => r.total_score_per_day,
    },
    {
      id: "avg_normalised", header: t("transparency.normalised"),
      headerTooltip: t("transparency.normalised_tooltip"),
      cell: (r) => r.avg_normalised.toFixed(3),
      sortValue: (r) => r.avg_normalised,
    },
  ];

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" data-testid="transparency-page">
        {/* Header with tree filter */}
        <div className="flex items-center justify-between gap-4" dir="rtl">
          <h2 className="text-xl font-semibold">{t("transparency.title")}</h2>

          <div className="relative" style={{ display: tab === 1 ? "none" : undefined }}>
            {selectedNodeId ? (
              <div className="flex items-center gap-1">
                <span className="text-sm bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300 px-2 py-1 rounded-full">
                  {selectedNodeName}
                </span>
                <button className="text-xs text-gray-400 hover:text-red-500 px-1" onClick={clearFilter}>✕</button>
                <button className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline px-1" onClick={() => setTreeOpen((o) => !o)}>שנה</button>
              </div>
            ) : (
              <button
                className="flex items-center gap-1 text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
                onClick={() => setTreeOpen((o) => !o)}
              >
                <span>🌳</span>
                <span>סנן לפי יחידה</span>
                <span className="text-xs">{treeOpen ? "▲" : "▼"}</span>
              </button>
            )}

            {treeOpen && (
              <div
                className="absolute left-0 top-full mt-1 z-20 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg p-2 min-w-52 max-h-72 overflow-y-auto"
                dir="rtl"
              >
                <div className="flex items-center justify-between mb-1 px-1">
                  <span className="text-xs text-gray-500">בחר יחידה לסינון</span>
                  {selectedNodeId && (
                    <button className="text-xs text-red-500 hover:underline" onClick={clearFilter}>הצג הכל</button>
                  )}
                </div>
                {treeNodes.map((node) => (
                  <TreeNode key={node.id} node={node} selectedId={selectedNodeId} onSelect={handleSelectNode} depth={0} />
                ))}
              </div>
            )}
          </div>

          {tab === 0 && (
            <button
              className="text-sm text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700 px-3 py-1 rounded hover:bg-green-50 dark:hover:bg-green-950"
              onClick={() => void downloadTransparencyExport(selectedNodeId)}
            >
              📥 ייצוא לאקסל
            </button>
          )}
          {tab === 1 && (
            <button
              className="text-sm text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700 px-3 py-1 rounded hover:bg-green-50 dark:hover:bg-green-950"
              onClick={() => void downloadSubUnitsExport()}
            >
              📥 ייצוא לאקסל
            </button>
          )}
        </div>

        {/* Tabs */}
        <TabBar tabs={["חיילים", "תתי יחידות"]} active={tab} onChange={setTab} />

        {/* Summary cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" dir="rtl">
          <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-center">
            <p className="text-xs text-gray-500 dark:text-gray-400">{t("transparency.avg_cumulative")}</p>
            <p className="text-lg font-semibold text-gray-800 dark:text-gray-100">{avgCumulative.toFixed(2)}</p>
          </div>
          <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-center">
            <p className="text-xs text-gray-500 dark:text-gray-400">{t("transparency.avg_active_days")}</p>
            <p className="text-lg font-semibold text-gray-800 dark:text-gray-100">{avgActiveDays}</p>
          </div>
          <div className={`rounded-lg p-3 border text-center ${avgScorePerDay > 0.3 ? "bg-red-50 dark:bg-red-950 border-red-300 dark:border-red-700" : "bg-gray-50 dark:bg-gray-700 border-gray-200 dark:border-gray-600"}`}>
            <p className="text-xs text-gray-500 dark:text-gray-400">{t("transparency.score_per_day")} ממוצע</p>
            <p className={`text-lg font-semibold ${avgScorePerDay > 0.3 ? "text-red-600 dark:text-red-400" : "text-gray-800 dark:text-gray-100"}`}>{avgScorePerDay.toFixed(3)}</p>
            {avgScorePerDay > 0.3 && <p className="text-xs text-red-500 mt-0.5">עומס תורנויות חמור</p>}
          </div>
          <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-center">
            <p className="text-xs text-gray-500 dark:text-gray-400">{t("transparency.avg_normalised")}</p>
            <p className="text-lg font-semibold text-gray-800 dark:text-gray-100">{avgNormalised.toFixed(3)}</p>
          </div>
        </div>

        {/* Filter pills (soldiers tab only) */}
        {tab === 0 && (
          <div className="flex flex-wrap gap-3 items-center" dir="rtl">
            <FilterPills<OfficerFilter>
              value={officerFilter}
              onChange={setOfficerFilter}
              options={[
                { value: "all", label: "קצינים וחוגרים" },
                { value: "officer", label: "קצינים" },
                { value: "enlisted", label: "חוגרים" },
              ]}
            />
            <div className="w-px h-5 bg-gray-300 dark:bg-gray-600 hidden sm:block" />
            <FilterPills<ServiceFilter>
              value={serviceFilter}
              onChange={setServiceFilter}
              options={[
                { value: "all", label: "חובה וקבע" },
                { value: "חובה", label: "חובה" },
                { value: "קבע", label: "קבע" },
              ]}
            />
          </div>
        )}

        {/* Tab content */}
        {tab === 0 && (
          <>
            <DataTable
              columns={soldierCols}
              data={visibleRows}
              filterPlaceholder={t("table.filter_placeholder")}
              rowClassName={(r) => (r.soldier_id === user?.id ? "bg-indigo-50 dark:bg-indigo-950" : "")}
            />
            {breakdownOpen && breakdown && (
              <div data-testid="own-breakdown" className="border-t pt-3 text-sm">
                <h3 className="font-medium">{t("transparency.my_breakdown")}</h3>
                <ul>
                  {breakdown.per_type.map((pt) => (
                    <li key={pt.duty_type_id}>{pt.duty_type_name ?? pt.duty_type_id}: {pt.days} {t("transparency.days")} — {pt.score}</li>
                  ))}
                </ul>
                <h4 className="font-medium mt-2">{t("transparency.adjustments")}</h4>
                <ul>
                  {breakdown.adjustments.map((a) => <li key={a.id}>{a.delta} — {a.reason}</li>)}
                </ul>
              </div>
            )}
          </>
        )}

        {tab === 1 && (
          <DataTable
            columns={subCols}
            data={subRows}
            filterPlaceholder={t("table.filter_placeholder")}
          />
        )}
      </section>

      {treeOpen && <div className="fixed inset-0 z-10" onClick={() => setTreeOpen(false)} />}
    </Layout>
  );
}
 
