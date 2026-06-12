import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { Breakdown, EffortBreakdown, TransparencyRow, getBreakdown, getEffortBreakdown, getTransparency, downloadTransparencyExport, downloadSubUnitsExport } from "../api/scoring";
import { DataTable, type ColDef } from "../components/DataTable";
import SoldierLink from "../components/SoldierLink";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import TabBar from "../components/TabBar";
import { computeEffortStats, getEffortColor as _getEffortColor, type EffortStats } from "../utils/effortStats";

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
  exempted_count: number;
  avg_cumulative: number;
  avg_cumulative_active: number;
  total_score_per_day: number;
  avg_active_days: number;
  avg_normalised: number;
}

// ─── fairness card ────────────────────────────────────────────────────────────

function FairnessCard({ stats }: { stats: EffortStats | null }) {
  const { t } = useTranslation();
  if (!stats) {
    return (
      <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-center">
        <p className="text-xs text-gray-500 dark:text-gray-400">{t("transparency.effort_spread")}</p>
        <p className="text-lg font-semibold text-gray-400">—</p>
      </div>
    );
  }
  const cvPct = stats.cv * 100;
  const cardClass = cvPct < 25
    ? "bg-green-50 dark:bg-green-950 border-green-300 dark:border-green-700"
    : cvPct < 50
      ? "bg-yellow-50 dark:bg-yellow-950 border-yellow-300 dark:border-yellow-700"
      : "bg-red-50 dark:bg-red-950 border-red-300 dark:border-red-700";
  const dotClass = cvPct < 25 ? "bg-green-500" : cvPct < 50 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className={`rounded-lg p-3 border text-center ${cardClass}`}>
      <p className="text-xs text-gray-500 dark:text-gray-400 flex items-center justify-center gap-1">
        <span className={`inline-block w-2 h-2 rounded-full ${dotClass}`} />
        {t("transparency.effort_spread")}
      </p>
      <p className="text-lg font-semibold text-gray-800 dark:text-gray-100">{cvPct.toFixed(1)}%</p>
      <div className="mt-1 text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
        <p>{t("transparency.effort_mean")}: {(stats.mean * 100).toFixed(1)}%</p>
        <p>{t("transparency.effort_stddev")}: ±{(stats.stddev * 100).toFixed(1)}%</p>
        <p>{t("transparency.effort_range")}: {(stats.min * 100).toFixed(1)}%–{(stats.max * 100).toFixed(1)}%</p>
      </div>
    </div>
  );
}

// ─── main page ────────────────────────────────────────────────────────────────

export default function TransparencyPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [rows, setRows] = useState<TransparencyRow[]>([]);
  const [breakdown, setBreakdown] = useState<Breakdown | null>(null);
  const [breakdownOpen, setBreakdownOpen] = useState(false);
  const [effortBreakdown, setEffortBreakdown] = useState<EffortBreakdown | null>(null);
  const [effortBreakdownSoldierName, setEffortBreakdownSoldierName] = useState<string | null>(null);
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

  async function openEffortBreakdown(soldierId: string, soldierName: string) {
    setEffortBreakdownSoldierName(soldierName);
    setEffortBreakdown(await getEffortBreakdown(soldierId));
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
          const exemptedCount = nodeRows.filter((r) => r.is_globally_exempted).length;
          result.push({
            node_id: node.id,
            node_name: node.name,
            depth: node.path_ids.length - 1,
            count: nodeRows.length,
            active_count: nodeRows.length - exemptedCount,
            exempted_count: exemptedCount,
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
    : subRows.length === 0 ? 0 : subRows.reduce((s, r) => s + r.total_score_per_day, 0) / subRows.length;
  const avgNormalised = statsRows
    ? statsRows.length === 0 ? 0 : statsRows.reduce((s, r) => s + Number(r.normalised_score), 0) / statsRows.length
    : subRows.length === 0 ? 0 : subRows.reduce((s, r) => s + r.avg_normalised, 0) / subRows.length;

  const effortStats: EffortStats | null = tab === 0
    ? computeEffortStats(visibleRows.map((r) => r.effort_score).filter((v) => !isNaN(v)))
    : null;

  const subEffortStats: EffortStats | null = tab === 1
    ? computeEffortStats((subRows as Array<{ avg_effort?: number }>).map((r) => r.avg_effort ?? NaN).filter((v) => !isNaN(v) && v > 0))
    : null;

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
    {
      id: "effort_score", header: "עומס רבעוני",
      headerTooltip: "ממוצע משוקלל של חלק התורנויות של החייל מסך תורנויות היחידה לרבעון, מאז תאריך האיפוס. לחץ לפירוט רבעוני.",
      cell: (r) => {
        const n = r.effort_score;
        const label = isNaN(n) || n === undefined ? "—" : (n * 100).toFixed(2) + "%";
        return (
          <button
            className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
            onClick={() => void openEffortBreakdown(r.soldier_id, r.full_name)}
            title="לחץ לפירוט רבעוני"
          >
            {label}
          </button>
        );
      },
      sortValue: (r) => r.effort_score,
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
    {
      id: "exempted_count",
      header: t("transparency.exempted_count"),
      cell: (r) => (
        <span
          className="text-gray-500"
          title={t("transparency.exempted_count_tooltip", { count: r.exempted_count })}
        >
          {r.exempted_count}
        </span>
      ),
      sortValue: (r) => r.exempted_count,
    },
    {
      id: "active_count",
      header: "חיילים פעילים",
      cell: (r) => `${r.active_count} (${Math.round(r.active_count / r.count * 100)}%)`,
      sortValue: (r) => r.active_count,
    },
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
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3" dir="rtl">
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
          {tab === 0 && <FairnessCard stats={effortStats} />}
          {tab === 1 && <FairnessCard stats={subEffortStats} />}
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
              testId="transparency-table"
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

      {/* Effort breakdown modal */}
      {effortBreakdown && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
          onClick={() => setEffortBreakdown(null)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-xl max-h-[80vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
            dir="rtl"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b dark:border-gray-700">
              <h2 className="text-base font-semibold text-gray-900 dark:text-white">
                📊 פירוט עומס רבעוני — {effortBreakdownSoldierName}
              </h2>
              <button
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xl leading-none"
                onClick={() => setEffortBreakdown(null)}
              >
                ✕
              </button>
            </div>

            {/* Table + Derivation (scrollable together so header & footer always visible) */}
            <div className="overflow-y-auto flex-1">
              {/* Table */}
              <div className="py-3">
                {effortBreakdown.quarters.length === 0 ? (
                  <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-6">אין נתוני היסטוריה — חייל חדש.</p>
                ) : (
                  <div className="overflow-x-auto px-4">
                    <table className="w-full text-sm border-collapse" style={{ minWidth: "480px" }}>
                      <thead>
                        <tr className="text-xs text-gray-500 dark:text-gray-400 border-b dark:border-gray-700">
                          <th className="text-right py-1 pb-2 font-medium">רבעון</th>
                          <th className="text-right py-1 pb-2 font-medium px-3">ניקוד חייל</th>
                          <th
                            className="text-right py-1 pb-2 font-medium px-3 cursor-help underline decoration-dotted"
                            title="סכום נקודות כל התורנויות של כל חיילי היחידה ברבעון זה. מחלקים בו את ניקוד החייל כדי לחשב את % חלקו."
                          >
                            ניקוד יחידה (סה״כ)
                          </th>
                          <th className="text-right py-1 pb-2 font-medium px-3">% נוכחות</th>
                          <th
                            className="text-right py-1 pb-2 font-medium px-3 cursor-help underline decoration-dotted"
                            title="חלק החייל מניקוד היחידה (ניקוד חייל ÷ ניקוד יחידה), לפני תיקון נוכחות."
                          >
                            חלק בנטל
                          </th>
                          <th
                            className="text-right py-1 pb-2 font-medium cursor-help underline decoration-dotted"
                            title="חלק בנטל × % נוכחות. זהו הערך שמצטבר לנוסחה הסופית (A)."
                          >
                            תרומה לנוסחה
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {effortBreakdown.quarters.map((q) => {
                          const sharePct = (parseFloat(q.share) * 100).toFixed(2);
                          const activePct = (parseFloat(q.active_frac) * 100).toFixed(0);
                          const unitScore = parseFloat(q.unit_score);
                          const weightedSharePct = (parseFloat(q.weighted_share) * 100).toFixed(2);
                          return (
                            <tr key={q.quarter_label} className={`border-b dark:border-gray-700 ${q.is_partial ? "bg-indigo-50/40 dark:bg-indigo-950/20" : ""}`}>
                              <td className="py-2 text-gray-700 dark:text-gray-300 font-medium">
                                <span className={q.is_partial ? "italic" : ""}>{q.quarter_label}</span>
                                {q.is_partial && <span className="mr-1 text-indigo-500 dark:text-indigo-400 text-xs font-normal not-italic">(חלקי)</span>}
                              </td>
                              <td className="py-2 text-right px-3 text-gray-700 dark:text-gray-300 tabular-nums">{parseFloat(q.soldier_score).toFixed(2)}</td>
                              <td className="py-2 text-right px-3 text-gray-500 dark:text-gray-400 tabular-nums">
                                {unitScore > 0 ? unitScore.toFixed(2) : <span className="italic text-xs">ללא</span>}
                              </td>
                              <td className="py-2 text-right px-3 text-gray-500 dark:text-gray-400 tabular-nums">{activePct}%</td>
                              <td className="py-2 text-right px-3 text-gray-500 dark:text-gray-400 tabular-nums">{sharePct}%</td>
                              <td className="py-2 text-right font-semibold text-indigo-700 dark:text-indigo-300 tabular-nums">{weightedSharePct}%</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    {(() => {
                      const partialQ = effortBreakdown.quarters.find((q) => q.is_partial);
                      if (!partialQ) return null;
                      const endFormatted = new Date(partialQ.quarter_end + "T00:00:00").toLocaleDateString("he-IL");
                      return (
                        <p className="mt-2 text-xs text-indigo-700 dark:text-indigo-400">
                          ℹ️ <strong>רבעון חלקי</strong> — התורנות האחרונה המפורסמת מסתיימת ב-{endFormatted}, לפני סוף הרבעון. לכן הניקוד ברבעון זה נמוך מרבעונות שלמים.
                        </p>
                      );
                    })()}
                  </div>
                )}
              </div>

              {/* Derivation — inside the scrollable area */}
              {effortBreakdown.quarters.length > 0 && (() => {
                const A = parseFloat(effortBreakdown.A_i);
                const W = parseFloat(effortBreakdown.W_i);
                const effort = parseFloat(effortBreakdown.effort_score);
                const qs = effortBreakdown.quarters;

                return (
                  <div className="border-t dark:border-gray-700 bg-gray-50 dark:bg-gray-900 px-4 py-4 space-y-4 text-xs" dir="rtl">
                    <p className="font-semibold text-gray-700 dark:text-gray-300">כיצד מגיעים למספר הסופי?</p>

                    {/* Step 1: A — per-row arithmetic */}
                    <div>
                      <p className="font-medium text-indigo-700 dark:text-indigo-300 mb-1">
                        שלב 1 — עומס שנצבר (A): לכל רבעון, חלק ניקוד החייל מניקוד היחידה כפול אחוז הנוכחות
                      </p>
                      <div className="bg-white dark:bg-gray-800 border border-indigo-100 dark:border-indigo-900 rounded-lg overflow-hidden">
                        {qs.map((q, i) => {
                          const ss = parseFloat(q.soldier_score);
                          const us = parseFloat(q.unit_score);
                          const ap = (parseFloat(q.active_frac) * 100).toFixed(0);
                          const ws = (parseFloat(q.weighted_share) * 100).toFixed(2);
                          const hasScore = us > 0;
                          return (
                            <div
                              key={q.quarter_label}
                              className={`flex items-center justify-between gap-2 px-2 py-1.5 ${i > 0 ? "border-t border-gray-100 dark:border-gray-700" : ""}`}
                            >
                              <span className="font-medium text-gray-600 dark:text-gray-400 shrink-0 w-14">{q.quarter_label}</span>
                              {hasScore ? (
                                <span dir="ltr" className="tabular-nums text-gray-600 dark:text-gray-400 text-left">
                                  {ap}% × ({ss.toFixed(2)} ÷ {us.toFixed(2)})
                                  {" = "}
                                  <strong className="text-indigo-600 dark:text-indigo-400">{ws}%</strong>
                                </span>
                              ) : (
                                <span className="text-gray-400 dark:text-gray-500 italic">
                                  אין תורנויות ביחידה — תרומה 0%
                                </span>
                              )}
                            </div>
                          );
                        })}
                        <div className="border-t border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-950 px-2 py-1.5 flex justify-between font-semibold text-indigo-700 dark:text-indigo-300">
                          <span>סכום = A</span>
                          <span className="tabular-nums">{(A * 100).toFixed(2)}%</span>
                        </div>
                      </div>
                    </div>

                    {/* Step 2: W — sum of presences + final formula */}
                    <div>
                      <p className="font-medium text-amber-700 dark:text-amber-300 mb-1">
                        שלב 2 — היסטוריה כוללת (W): סכום % נוכחות לכל רבעון
                      </p>
                      <div className="bg-white dark:bg-gray-800 border border-amber-100 dark:border-amber-900 rounded-lg overflow-hidden">
                        {qs.map((q, i) => (
                          <div
                            key={q.quarter_label}
                            className={`flex justify-between px-2 py-1.5 text-gray-600 dark:text-gray-400 ${i > 0 ? "border-t border-gray-100 dark:border-gray-700" : ""}`}
                          >
                            <span className="font-medium text-gray-600 dark:text-gray-400 w-14">{q.quarter_label}</span>
                            <span className="tabular-nums">{(parseFloat(q.active_frac) * 100).toFixed(0)}%</span>
                          </div>
                        ))}
                        <div className="border-t border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950 px-2 py-1.5 flex justify-between font-semibold text-amber-700 dark:text-amber-300">
                          <span>סכום = W</span>
                          <span className="tabular-nums">{W.toFixed(2)}</span>
                        </div>
                      </div>
                      <div className="mt-2 bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 rounded-lg px-3 py-2">
                        <p className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">עומס = A ÷ W</p>
                        <p dir="ltr" className="font-bold text-base text-indigo-700 dark:text-indigo-300 tabular-nums text-left">
                          {(A * 100).toFixed(2)}% ÷ {W.toFixed(2)} = <span className="text-lg">{(effort * 100).toFixed(2)}%</span>
                        </p>
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* Footer */}
            <div className="px-5 py-3 border-t dark:border-gray-700 bg-white dark:bg-gray-800 flex items-center justify-between text-sm">
              <span className="text-gray-500 dark:text-gray-400">עומס רבעוני מצטבר:</span>
              <span className="text-xl font-bold text-indigo-700 dark:text-indigo-300">
                {(parseFloat(effortBreakdown.effort_score) * 100).toFixed(2)}%
              </span>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
 
