import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import Combobox from "../components/Combobox";
import { useAuth } from "../auth/AuthContext";
import { TransparencyRow, getEffortBreakdown, getFairnessComponents, getTransparency } from "../api/scoring";
import { DataTable, type ColDef } from "../components/DataTable";
import { ExcelExportButton } from "../components/ExcelExportButton";
import SoldierLink from "../components/SoldierLink";
import { useSoldierModal } from "../contexts/SoldierModalContext";
import ExemptionsCell from "../components/ExemptionsCell";
import { formatDate } from "../utils/formatDate";
import { fetchFullTree, NodeDTO } from "../api/hierarchy";
import TabBar from "../components/TabBar";
import FairnessComponentsCard, { COMPONENT_COLORS, type GroupKey } from "../components/FairnessComponentsCard";
import { InlineMath, BlockMath } from "react-katex";
import { computeEffortStats, getEffortColor, type EffortStats } from "../utils/effortStats";
import { WHOLE_ORG_ID } from "../utils/wholeOrg";
import { getEffortGap } from "../api/potential";
import { sortNodesByTree } from "../utils/sortNodesByTree";

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

function gapColor(gap: number | null): string {
  if (gap === null) return "text-gray-400";
  if (gap > 1.3) return "text-red-600 dark:text-red-400 font-semibold";
  if (gap < 0.7) return "text-blue-600 dark:text-blue-400 font-semibold";
  return "text-gray-700 dark:text-gray-300";
}

function formatGap(gap: number | null): string {
  return gap === null ? "—" : gap.toFixed(3);
}

const SCORE_AFFECTING_TYPES = ["assignment", "cancellation", "call_up", "dismissal"];

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
  'סג"ם': 11, "סגמ": 11,
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

// ─── soldier group info (from fairness components) ───────────────────────────

interface SoldierGroupInfo {
  compIndex: number;      // 0-based component index; -1 = exempt from all
  rank: number;           // 1 = lowest effort (assigned first); 0 for exempt
  groupSize: number;
  groupMean: number | null;
  groupCV: number | null;
  dutyTypeNames: string[];
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
  avg_effort: number;
  cv_effort: number | null;
  count_global_exemption: number | null;
  count_partial_exemption: number | null;
  count_temporary_exemption: number | null;
  sibling_gap: number | null;
  global_gap: number | null;
}

// ─── fairness card ────────────────────────────────────────────────────────────

function FairnessHelpModal({ variant, onClose }: { variant: "soldiers" | "subunits"; onClose: () => void }) {
  const isSoldiers = variant === "soldiers";
  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-lg w-full mx-4 max-h-[85vh] overflow-y-auto space-y-5"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-gray-900 dark:text-white">
          {isSoldiers ? "פיזור עומס (CV) — כיצד מחושב?" : "פיזור עומס בין מסגרות — כיצד מחושב?"}
        </h3>

        <p className="text-sm text-gray-700 dark:text-gray-300">
          {isSoldiers
            ? "מדד המציג כמה שוויונית חלוקת התורנויות בין החיילים. ערך נמוך פירושו שכולם נושאים עומס דומה."
            : "מדד המציג כמה שוויוני הנטל בין המסגרות השונות, לפי ממוצע עומס לחייל בכל מסגרת."}
        </p>

        {/* Stddev */}
        <div>
          <p className="text-sm font-semibold text-indigo-700 dark:text-indigo-300 mb-1">שלב 1 — סטיית תקן (σ)</p>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
            לכל {isSoldiers ? "חייל" : "מסגרת"} מחשבים כמה הוא שונה מהממוצע, מעלים בריבוע (כדי שהפרשים בכיוונים הפוכים לא יתבטלו), מחשבים ממוצע של הריבועים, ולוקחים שורש ריבועי.
          </p>
          <div className="bg-gray-50 dark:bg-gray-900 rounded-lg px-4 py-3 overflow-x-auto text-center">
            <BlockMath math={String.raw`\sigma = \sqrt{\frac{\displaystyle\sum_{i=1}^{n}(x_i - \mu)^2}{n}}`} />
          </div>
          <div className="mt-2 text-xs text-gray-500 dark:text-gray-400 space-y-0.5 pr-1">
            <p><InlineMath math="x_i" /> — {isSoldiers ? "עומס חייל i" : "ממוצע עומס מסגרת i"}</p>
            <p><InlineMath math="\mu" /> — ממוצע {isSoldiers ? "עומסי כל החיילים" : "ממוצעי כל המסגרות"}</p>
            <p><InlineMath math="n" /> — מספר {isSoldiers ? "החיילים" : "המסגרות"}</p>
          </div>
        </div>

        {/* CV */}
        <div>
          <p className="text-sm font-semibold text-indigo-700 dark:text-indigo-300 mb-1">שלב 2 — מקדם הפיזור (CV)</p>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
            מנרמל את סטיית התקן לפי הממוצע, כך שאפשר להשוות פיזור גם כשהממוצע משתנה לאורך הזמן.
          </p>
          <div className="bg-gray-50 dark:bg-gray-900 rounded-lg px-4 py-3 overflow-x-auto text-center">
            <BlockMath math={String.raw`CV = \frac{\sigma}{\mu}`} />
          </div>
        </div>

        {/* Thresholds */}
        <div>
          <p className="text-sm font-semibold text-indigo-700 dark:text-indigo-300 mb-2">פרשנות</p>
          <div className="space-y-2 text-sm">
            {[
              { dot: "bg-green-500", range: "פחות מ-25%", desc: isSoldiers ? "פיזור בריא — העומס מחולק בצורה שוויונית" : "פיזור בריא — המסגרות נושאות עומס דומה" },
              { dot: "bg-yellow-500", range: "25%–50%", desc: "אי-שוויון בינוני — כדאי לבדוק" },
              { dot: "bg-red-500", range: "מעל 50%", desc: isSoldiers ? "פיזור גבוה — חיילים מסוימים נושאים עומס שונה מאוד מהממוצע" : "פיזור גבוה — מסגרת אחת לפחות נושאת עומס שונה מאוד משאר המסגרות" },
            ].map(({ dot, range, desc }) => (
              <div key={range} className="flex items-start gap-2">
                <span className={`mt-1 inline-block w-2 h-2 rounded-full shrink-0 ${dot}`} />
                <span className="text-gray-700 dark:text-gray-300"><strong>{range}</strong> — {desc}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="text-left pt-1">
          <button type="button" className="bg-indigo-600 text-white px-4 py-1.5 rounded text-sm" onClick={onClose}>סגור</button>
        </div>
      </div>
    </div>
  );
}

function FairnessCard({ stats, helpVariant }: { stats: EffortStats | null; helpVariant?: "soldiers" | "subunits" }) {
  const { t } = useTranslation();
  const [modalOpen, setModalOpen] = useState(false);

  const helpButton = helpVariant && (
    <button
      type="button"
      onClick={() => setModalOpen(true)}
      className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xs border border-gray-300 dark:border-gray-500 rounded-full w-3.5 h-3.5 inline-flex items-center justify-center cursor-pointer"
    >
      ?
    </button>
  );

  if (!stats) {
    return (
      <>
        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-center">
          <p className="text-xs text-gray-500 dark:text-gray-400 flex items-center justify-center gap-1">
            {t("transparency.effort_spread")}
            {helpButton}
          </p>
          <p className="text-lg font-semibold text-gray-400">—</p>
        </div>
        {modalOpen && helpVariant && <FairnessHelpModal variant={helpVariant} onClose={() => setModalOpen(false)} />}
      </>
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
    <>
      <div className={`rounded-lg p-3 border text-center ${cardClass}`}>
        <p className="text-xs text-gray-500 dark:text-gray-400 flex items-center justify-center gap-1">
          <span className={`inline-block w-2 h-2 rounded-full ${dotClass}`} />
          {t("transparency.effort_spread")}
          {helpButton}
        </p>
        <p className="text-lg font-semibold text-gray-800 dark:text-gray-100">{cvPct.toFixed(1)}%</p>
        <div className="mt-1 text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
          <p>{t("transparency.effort_mean")}: {(stats.mean * 100).toFixed(1)}%</p>
          <p>{t("transparency.effort_stddev")}: ±{(stats.stddev * 100).toFixed(1)}%</p>
          <p>{t("transparency.effort_range")}: {(stats.min * 100).toFixed(1)}%–{(stats.max * 100).toFixed(1)}%</p>
        </div>
      </div>
      {modalOpen && helpVariant && <FairnessHelpModal variant={helpVariant} onClose={() => setModalOpen(false)} />}
    </>
  );
}

// ─── main page ────────────────────────────────────────────────────────────────

export default function TransparencyPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { openSoldierModal } = useSoldierModal();
  const [treeOpen, setTreeOpen] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  const TAB_KEYS = ["soldiers", "sub_units"] as const;
  type TabKey = typeof TAB_KEYS[number];
  const rawKey = searchParams.get("tab") as TabKey | null;
  const tab = rawKey === "sub_units" ? 1 : 0;

  function setTab(next: number) {
    setSearchParams((prev) => { prev.set("tab", TAB_KEYS[next] ?? "soldiers"); return prev; }, { replace: true });
  }
  const [showDebug, setShowDebug] = useState(false);
  const [officerFilter, setOfficerFilter] = useState<OfficerFilter>("all");
  const [serviceFilter, setServiceFilter] = useState<ServiceFilter>("all");
  const [activeGroupKeys, setActiveGroupKeys] = useState<Set<GroupKey>>(new Set());
  const [groupSoldiersMap, setGroupSoldiersMap] = useState<Map<GroupKey, string[]>>(new Map());
  const [exportSoldierRows, setExportSoldierRows] = useState<NumberedRow[]>([]);
  const [exportSubRows, setExportSubRows] = useState<SubRow[]>([]);
  const [effortBreakdownFor, setEffortBreakdownFor] = useState<{ soldierId: string; soldierName: string } | null>(null);

  const canViewTransparency = user?.can_view_transparency ?? true; // true until /me loads, avoids a flash-then-hide for allowed users
  const transparencyQuery = useQuery({
    queryKey: queryKeys.transparency(),
    queryFn: getTransparency,
    enabled: canViewTransparency,
  });
  const rows = useMemo(() => transparencyQuery.data?.rows ?? [], [transparencyQuery.data]);
  const canSeeExemptionAggregates = transparencyQuery.data?.can_see_exemption_aggregates ?? false;
  const transparencyForbidden =
    user?.can_view_transparency === false ||
    (isAxiosError(transparencyQuery.error) && transparencyQuery.error.response?.status === 403);

  const treeQuery = useQuery({ queryKey: queryKeys.hierarchyTree(), queryFn: fetchFullTree });
  const treeNodes = useMemo(() => treeQuery.data ?? [], [treeQuery.data]);

  const fairnessComponentsQuery = useQuery({
    queryKey: queryKeys.fairnessComponents(),
    queryFn: getFairnessComponents,
    enabled: canViewTransparency,
  });
  const fairnessComponents = fairnessComponentsQuery.data ?? null;

  const effortGapQuery = useQuery({ queryKey: queryKeys.effortGapNodes(), queryFn: () => getEffortGap() });
  const effortGapByNode = useMemo(
    () => new Map((effortGapQuery.data ?? []).map((r) => [r.node_id, r])),
    [effortGapQuery.data],
  );

  const effortBreakdownQuery = useQuery({
    queryKey: effortBreakdownFor ? queryKeys.effortBreakdown(effortBreakdownFor.soldierId) : ["scoring", "effortBreakdown", "none"],
    queryFn: () => getEffortBreakdown(effortBreakdownFor!.soldierId),
    enabled: !!effortBreakdownFor,
  });
  const effortBreakdown = effortBreakdownFor ? effortBreakdownQuery.data ?? null : null;
  const effortBreakdownSoldierName = effortBreakdownFor?.soldierName ?? null;

  function openEffortBreakdown(soldierId: string, soldierName: string) {
    setEffortBreakdownFor({ soldierId, soldierName });
  }

  function closeEffortBreakdown() {
    setEffortBreakdownFor(null);
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

  const soldierGroupMap = useMemo((): Map<string, SoldierGroupInfo> => {
    const map = new Map<string, SoldierGroupInfo>();
    if (!fairnessComponents) return map;
    fairnessComponents.components.forEach((comp, compIndex) => {
      const sorted = [...comp.soldiers].sort((a, b) => a.effort_score - b.effort_score);
      sorted.forEach((s, i) => {
        map.set(s.soldier_id, {
          compIndex,
          rank: i + 1,
          groupSize: comp.soldier_count,
          groupMean: comp.effort?.mean ?? null,
          groupCV: comp.effort?.cv ?? null,
          dutyTypeNames: comp.duty_type_names,
        });
      });
    });
    fairnessComponents.exempt_from_all.soldiers.forEach((s) => {
      map.set(s.soldier_id, {
        compIndex: -1,
        rank: 0,
        groupSize: fairnessComponents.exempt_from_all.count,
        groupMean: null,
        groupCV: null,
        dutyTypeNames: [],
      });
    });
    return map;
  }, [fairnessComponents]);

  const visibleRows = useMemo(() => {
    let filtered = subtreeIds
      ? rows.filter((r) => r.node_id != null && subtreeIds.has(r.node_id))
      : rows;
    if (activeGroupKeys.size > 0) {
      const ids = new Set<string>();
      for (const key of activeGroupKeys) for (const id of groupSoldiersMap.get(key) ?? []) ids.add(id);
      filtered = filtered.filter((r) => ids.has(r.soldier_id));
    }
    if (officerFilter === "officer") filtered = filtered.filter((r) => r.is_officer);
    if (officerFilter === "enlisted") filtered = filtered.filter((r) => !r.is_officer);
    if (serviceFilter !== "all") filtered = filtered.filter((r) => r.service_type === serviceFilter);
    // Stamp stable row numbers + pre-computed rank order so sortValue is a plain property lookup
    return filtered.map((r, i) => ({
      ...r,
      _row_num: i + 1,
      _rank_order: r.rank ? (RANK_ORDER[r.rank] ?? 999) : 999,
      _group: soldierGroupMap.get(r.soldier_id),
    }));
  }, [rows, subtreeIds, officerFilter, serviceFilter, activeGroupKeys, groupSoldiersMap, soldierGroupMap]);

  // ── auto-range bounds (approximated from all rows — real run also adds per-milli headroom) ──
  const effortRange = useMemo(() => {
    const offsets = rows.map((r) => r.effort_offset_raw).filter((v) => v > 0);
    if (offsets.length === 0) return null;
    const min = Math.min(...offsets);
    const max = Math.max(...offsets);
    const size = Math.max(1, max - min);
    const precisionPct = (size / 1_000_000_000 / 1000) * 100; // range / EFFORT_SCALE / resolution × 100
    return { min, max, size, precisionPct };
  }, [rows]);

  // ── sub-hierarchy tab: build children map from parent_id (API returns flat list) ──
  const subRows = useMemo((): SubRow[] => {
    const result: SubRow[] = [];
    const avg = (vals: number[]) => vals.reduce((a, b) => a + b, 0) / vals.length;

    function buildSubRow(nodeId: string, nodeName: string, depth: number, nodeRows: TransparencyRow[]): SubRow {
      const exemptedCount = nodeRows.filter((r) => r.is_globally_exempted).length;
      return {
        node_id: nodeId,
        node_name: nodeName,
        depth,
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
        avg_effort: (() => {
          const efforts = nodeRows.map((r) => r.effort_score).filter((v) => !isNaN(v));
          return efforts.length > 0 ? efforts.reduce((a, b) => a + b, 0) / efforts.length : 0;
        })(),
        cv_effort: (() => {
          const efforts = nodeRows.map((r) => r.effort_score).filter((v) => !isNaN(v));
          const stats = computeEffortStats(efforts);
          return stats ? stats.cv : null;
        })(),
        count_global_exemption: canSeeExemptionAggregates
          ? nodeRows.filter((r) => r.has_global_exemption === true).length
          : null,
        count_partial_exemption: canSeeExemptionAggregates
          ? nodeRows.filter((r) => r.has_partial_exemption === true).length
          : null,
        count_temporary_exemption: canSeeExemptionAggregates
          ? nodeRows.filter((r) => r.has_temporary_exemption === true).length
          : null,
        sibling_gap: effortGapByNode.get(nodeId)?.sibling_gap ?? null,
        global_gap: effortGapByNode.get(nodeId)?.global_gap ?? null,
      };
    }

    const childrenMap = new Map<string | null, NodeDTO[]>();
    for (const node of flatNodes) {
      const key = node.parent_id ?? null;
      if (!childrenMap.has(key)) childrenMap.set(key, []);
      childrenMap.get(key)!.push(node);
    }

    // The synthetic whole-org row is only needed as a fallback for 0 or 2+
    // real top-level roots — with exactly one, that root's own row already
    // IS the whole-org total, so showing both would just duplicate it.
    const showWholeOrgRow = (childrenMap.get(null) ?? []).length !== 1;
    const depthOffset = showWholeOrgRow ? 0 : -1;

    function traverse(parentId: string | null) {
      for (const node of childrenMap.get(parentId) ?? []) {
        const nodeRows = rows.filter(
          (r) => r.node_id != null && nodePathsMap.get(r.node_id)?.includes(node.id),
        );
        if (nodeRows.length > 0) result.push(buildSubRow(node.id, node.name, node.path_ids.length + depthOffset, nodeRows));
        traverse(node.id);
      }
    }
    traverse(null);

    // Stable first row: aggregates every soldier regardless of how many real
    // top-level roots currently exist.
    if (showWholeOrgRow && rows.length > 0) result.unshift(buildSubRow(WHOLE_ORG_ID, t("common.whole_org"), 0, rows));
    return result;
  }, [flatNodes, nodePathsMap, rows, canSeeExemptionAggregates, t, effortGapByNode]);

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
    ? computeEffortStats(subRows.map((r) => r.avg_effort).filter((v) => !isNaN(v) && v > 0))
    : null;

  function handleSelectNode(id: string) {
    setSelectedNodeId((prev) => (prev === id ? null : id));
    setTreeOpen(false);
  }

  function clearFilter() {
    setSelectedNodeId(null);
    setTreeOpen(false);
  }

  function handleGroupToggle(soldierIds: string[], key: GroupKey) {
    setGroupSoldiersMap((prev) => new Map(prev).set(key, soldierIds));
    setActiveGroupKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
    setTab(0);
  }

  function clearGroupFilter() {
    setActiveGroupKeys(new Set());
  }

  // ── soldiers columns ──
  type NumberedRow = TransparencyRow & { _row_num: number; _rank_order: number; _group?: SoldierGroupInfo };
  const soldierCols: ColDef<NumberedRow>[] = [
    {
      id: "num", header: "#",
      cell: (r) => r._row_num,
      sortValue: (r) => r._row_num,
    },
    {
      id: "name", header: t("transparency.name"),
      cell: (r) => <SoldierLink id={r.soldier_id} name={r.full_name} />,
      sortValue: (r) => r.full_name, filterValue: (r) => r.full_name,
    },
    {
      id: "unit", header: t("transparency.unit"),
      cell: (r) => r.node_name ?? "—",
      sortValue: (r) => r.node_name ?? "", filterValue: (r) => r.node_name ?? "",
    },
    {
      id: "exemptions", header: t("transparency.exemptions"),
      cell: (r) => (
        <ExemptionsCell
          exemptions={r.exemptions}
          visible={r.exemptions_visible}
          placeholder="חסוי"
          soldierId={r.soldier_id}
        />
      ),
      sortValue: (r) => r.exemptions_display,
      filterValue: (r) => r.exemptions_display,
      exportValue: (r) => r.exemptions_display || "—",
    },
    { id: "enrolled_at", header: t("transparency.enrolled_at"), cell: (r) => formatDate(r.enrolled_at), sortValue: (r) => r.enrolled_at },
    { id: "active_days", header: t("transparency.active_days"), cell: (r) => r.active_days, sortValue: (r) => r.active_days },
    {
      id: "rank", header: t("transparency.rank"),
      cell: (r) => r.rank ?? "—",
      sortValue: (r) => r._rank_order,
      filterValue: (r) => r.rank ?? "",
      columnFilter: true,
      sortDescFirst: true, // senior ranks (higher _rank_order) should sort first on first click
    },
    {
      id: "shift_count", header: t("transparency.shift_count"),
      headerTooltip: t("transparency.shift_count_tooltip"),
      cell: (r) => r.shift_count,
      sortValue: (r) => r.shift_count,
    },
    {
      id: "cumulative", header: t("transparency.cumulative"),
      headerTooltip: "לחץ על הערך לצפייה באירועים שמשפיעים על הניקוד (תורנויות, ביטולים, הקפצות, שחרורים).",
      cell: (r) => {
        const n = Number(r.cumulative_score);
        const label = isNaN(n) ? r.cumulative_score : n.toFixed(3);
        return (
          <button
            className="text-indigo-600 dark:text-indigo-300 hover:underline font-medium"
            onClick={() => openSoldierModal(r.soldier_id, undefined, "duty_history", SCORE_AFFECTING_TYPES)}
            title="לחץ לצפייה באירועים שמשפיעים על הניקוד"
          >
            {label}
          </button>
        );
      },
      sortValue: (r) => Number(r.cumulative_score),
    },
    {
      id: "score_per_day", header: t("transparency.score_per_day"),
      headerTooltip: (
        <div className="space-y-3" dir="rtl">
          <p className="font-semibold">{t("transparency.score_per_day_modal_title")}</p>
          <BlockMath math="\text{ניקוד ליום} = \dfrac{\text{ניקוד מצטבר}}{\text{ימים פעילים}}" />
          <p className="text-xs text-gray-600 dark:text-gray-400">זהו קירוב של אחוז הזמן שאתה בתורנויות. כיוון שתורנויות מסוימות מקבלות ניקוד גבוה מ-1 ליום, הערך יכול לעלות מעל 1. כשהממוצע ביחידה עולה על 0.3, מצב התורנויות ביחידה די חמור.</p>
        </div>
      ),
      cell: (r) => { const n = Number(r.score_per_day); return isNaN(n) ? r.score_per_day : n.toFixed(3); },
      sortValue: (r) => Number(r.score_per_day),
    },
    {
      id: "normalised", header: t("transparency.normalised"),
      headerTooltip: (
        <div className="space-y-3" dir="rtl">
          <p>הניקוד המנורמל מחושב לפי הניקוד ליום שלך ביחס לממוצע היחידה.</p>
          <BlockMath math="\text{ניקוד מנורמל} = \dfrac{\text{ניקוד ליום שלך}}{\text{ממוצע ניקוד ליום ביחידה}}" />
          <p className="text-xs text-gray-500 dark:text-gray-400">ניקוד 1.0 = בדיוק כמו הממוצע. מעל 1.0 = עשית יותר מהממוצע. מתחת 1.0 = עשית פחות.</p>
        </div>
      ),
      cell: (r) => { const n = Number(r.normalised_score); return isNaN(n) ? r.normalised_score : n.toFixed(3); },
      sortValue: (r) => Number(r.normalised_score),
    },
    {
      id: "effort_score", header: "עומס רבעוני",
      headerTooltip: "חלקך מסך ניקוד היחידה: Σ(ניקודך × נוכחות) ÷ Σ(ניקוד היחידה × נוכחות). ערך הוגן = 1/N. עולה ומתכנס ככל שמצטברים רבעונות. לחץ לפירוט רבעוני.",
      cell: (r) => {
        const n = r.effort_score;
        const label = isNaN(n) || n === undefined ? "—" : (n * 100).toFixed(2) + "%";
        const colorClass = effortStats ? getEffortColor(n, effortStats.mean, effortStats.stddev) : "";
        return (
          <span className={`inline-block w-full rounded px-0.5 ${colorClass}`}>
            <button
              className="text-indigo-600 dark:text-indigo-300 hover:underline font-medium"
              onClick={() => openEffortBreakdown(r.soldier_id, r.full_name)}
              title="לחץ לפירוט רבעוני"
            >
              {label}
            </button>
          </span>
        );
      },
      sortValue: (r) => r.effort_score,
      exportValue: (r) => {
        const n = r.effort_score;
        return isNaN(n) || n === undefined ? "—" : (n * 100).toFixed(2) + "%";
      },
    },
    {
      id: "group_rank",
      header: "מקום בקבוצה",
      headerTooltip: (
        <div className="space-y-2" dir="rtl">
          <p className="font-semibold">מקום בקבוצת הכשירות</p>
          <p>מקום 1 = עומס הנמוך ביותר בקבוצה = האלגוריתם יקצה לו תורנות ראשון כדי לאזן.</p>
          <p className="text-xs text-gray-400">הכותרת מציגה מקום/גודל-קבוצה. ריחוף על תא מציג את סוגי התורנות של הקבוצה.</p>
        </div>
      ),
      cell: (r: NumberedRow) => {
        const g = r._group;
        if (!g || g.compIndex === -1) return <span className="text-gray-400 text-xs">פטור</span>;
        if (g.groupSize < 2) return <span className="text-gray-400 text-xs">—</span>;
        const isTop = g.rank <= 3;
        const isBottom = g.rank >= g.groupSize - 2;
        const cls = isTop
          ? "text-indigo-600 dark:text-indigo-300 font-semibold"
          : isBottom
            ? "text-gray-400"
            : "text-gray-700 dark:text-gray-300";
        return (
          <span className={`tabular-nums ${cls}`} title={g.dutyTypeNames.join("، ")}>
            {g.rank}/{g.groupSize}
            {isTop && <span className="mr-1 text-indigo-400 dark:text-indigo-500 text-[10px]">▲</span>}
          </span>
        );
      },
      sortValue: (r: NumberedRow) => r._group?.rank ?? 9999,
      exportValue: (r: NumberedRow) => {
        const g = r._group;
        if (!g || g.compIndex === -1) return "פטור";
        if (g.groupSize < 2) return "—";
        return `${g.rank}/${g.groupSize}`;
      },
    } as ColDef<NumberedRow>,
    {
      id: "group_dev",
      header: "עודף עומס",
      headerTooltip: (
        <div className="space-y-2" dir="rtl">
          <p className="font-semibold">עודף עומס יחסית לממוצע הקבוצה</p>
          <p><span className="text-red-500 font-medium">אדום חיובי</span> = נשא עומס מעל הממוצע → האלגוריתם מגן עליו מהקצאות.</p>
          <p><span className="text-green-600 font-medium">ירוק שלילי</span> = מתחת לממוצע → האלגוריתם ייתן לו עדיפות בהקצאה הבאה.</p>
        </div>
      ),
      cell: (r: NumberedRow) => {
        const mean = r._group?.groupMean;
        if (mean == null || isNaN(r.effort_score) || r._group?.compIndex === -1) return <span className="text-gray-400">—</span>;
        const dev = r.effort_score - mean;
        const sign = dev >= 0 ? "+" : "";
        const cls = dev > 0.005
          ? "text-red-600 dark:text-red-400"
          : dev < -0.005
            ? "text-green-700 dark:text-green-400"
            : "text-gray-500";
        return <span className={`tabular-nums ${cls}`}>{sign}{(dev * 100).toFixed(2)}%</span>;
      },
      sortValue: (r: NumberedRow) => {
        const mean = r._group?.groupMean;
        return mean != null && !isNaN(r.effort_score) ? r.effort_score - mean : 9999;
      },
      exportValue: (r: NumberedRow) => {
        const mean = r._group?.groupMean;
        if (mean == null || isNaN(r.effort_score) || r._group?.compIndex === -1) return "—";
        const dev = r.effort_score - mean;
        return (dev >= 0 ? "+" : "") + (dev * 100).toFixed(2) + "%";
      },
    } as ColDef<NumberedRow>,
    ...(showDebug ? [
      {
        id: "c_over_d",
        header: "C/D (1/Wᵢ)",
        headerTooltip: "C_over_D = 1/Wᵢ — משקל הכנסת תורנות חדשה לעומס. חייל חדש → גבוה; ותיק → נמוך.",
        cell: (r: NumberedRow) => r.c_over_d.toFixed(4),
        sortValue: (r: NumberedRow) => r.c_over_d,
      },
      {
        id: "effort_offset_raw",
        header: "effort_offset (×10⁹)",
        headerTooltip: "int(effort_score × 10⁹) — ה-offset ההיסטורי שמוזרק למודל ה-CP-SAT.",
        cell: (r: NumberedRow) => r.effort_offset_raw.toLocaleString(),
        sortValue: (r: NumberedRow) => r.effort_offset_raw,
      },
      {
        id: "count_offset",
        header: "count_offset",
        headerTooltip: "הערך שה-CP-SAT מבצע עליו אופטימיזציה: (effort_offset − range_min) × 1000 ÷ range_size. כל החיילים ממופים ל-[0, 1000] כך שכל 1000 הטיקים נופלים בטווח הפעיל. ערך ≈ מוצג כאן — הריצה האמיתית מוסיפה headroom לצבירה.",
        cell: (r: NumberedRow) => {
          if (!effortRange || effortRange.size <= 0) return <span className="text-gray-400">—</span>;
          const val = Math.max(0, Math.min(1000, Math.round((r.effort_offset_raw - effortRange.min) * 1000 / effortRange.size)));
          const frac = val / 1000;
          const barColor = frac < 0.33 ? "#10b981" : frac < 0.67 ? "#f59e0b" : "#ef4444";
          return (
            <span className="flex items-center gap-1.5">
              <span className="tabular-nums font-mono text-xs w-8 shrink-0">{val}</span>
              <span className="flex-1 bg-gray-200 dark:bg-gray-700 rounded h-1.5 overflow-hidden" style={{ minWidth: 40 }}>
                <span className="h-full block rounded" style={{ width: `${Math.max(2, val / 10)}%`, background: barColor }} />
              </span>
            </span>
          );
        },
        sortValue: (r: NumberedRow) => effortRange ? (r.effort_offset_raw - effortRange.min) * 1000 / effortRange.size : 0,
      },
    ] as ColDef<NumberedRow>[] : []),
  ];

  // ── sub-hierarchy columns ──
  const subCols: ColDef<SubRow>[] = [
    {
      id: "name", header: "יחידה",
      cell: (r) => (
        <span className="flex items-center" style={{ paddingRight: `${r.depth * 16}px` }}>
          {r.depth > 0 && <span className="text-gray-300 dark:text-gray-600 ml-1 text-xs">{"└"}</span>}
          <button
            className="text-indigo-600 dark:text-indigo-300 hover:underline text-right"
            onClick={() => { setSelectedNodeId(r.node_id === WHOLE_ORG_ID ? null : r.node_id); setTab(0); }}
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
      id: "count_global_exemption", header: t("transparency.count_global_exemption"),
      cell: (r) => r.count_global_exemption === null ? "חסוי" : r.count_global_exemption,
      sortValue: (r) => r.count_global_exemption ?? -1,
      exportValue: (r) => r.count_global_exemption === null ? "חסוי" : r.count_global_exemption,
    },
    {
      id: "count_partial_exemption", header: t("transparency.count_partial_exemption"),
      cell: (r) => r.count_partial_exemption === null ? "חסוי" : r.count_partial_exemption,
      sortValue: (r) => r.count_partial_exemption ?? -1,
      exportValue: (r) => r.count_partial_exemption === null ? "חסוי" : r.count_partial_exemption,
    },
    {
      id: "count_temporary_exemption", header: t("transparency.count_temporary_exemption"),
      cell: (r) => r.count_temporary_exemption === null ? "חסוי" : r.count_temporary_exemption,
      sortValue: (r) => r.count_temporary_exemption ?? -1,
      exportValue: (r) => r.count_temporary_exemption === null ? "חסוי" : r.count_temporary_exemption,
    },
    {
      id: "active_count",
      header: "חיילים פעילים",
      cell: (r) => `${r.active_count} (${Math.round(r.active_count / r.count * 100)}%)`,
      sortValue: (r) => r.active_count,
      exportValue: (r) => `${r.active_count} (${Math.round(r.active_count / r.count * 100)}%)`,
    },
    { id: "avg_active_days", header: t("transparency.avg_active_days"), cell: (r) => r.avg_active_days, sortValue: (r) => r.avg_active_days },
    { id: "avg_cumulative", header: "ממוצע ניקוד לחייל", cell: (r) => r.avg_cumulative.toFixed(3), sortValue: (r) => r.avg_cumulative },
    {
      id: "avg_cumulative_active",
      header: "ממוצע ניקוד לחייל פעיל",
      cell: (r) => r.avg_cumulative_active > 0 ? r.avg_cumulative_active.toFixed(3) : "—",
      sortValue: (r) => r.avg_cumulative_active,
      exportValue: (r) => r.avg_cumulative_active > 0 ? r.avg_cumulative_active.toFixed(3) : "—",
    },
    {
      id: "total_score_per_day", header: "ניקוד ליום (מסגרת)",
      headerTooltip: "סך ניקוד ליום של כל חיילי המסגרת — מייצג את עומס התורנויות הכולל של היחידה.",
      cell: (r) => (
        <span className={r.total_score_per_day > 0.3 * r.count ? "text-red-600 dark:text-red-400 font-medium" : ""}>
          {r.total_score_per_day.toFixed(3)}
        </span>
      ),
      sortValue: (r) => r.total_score_per_day,
      exportValue: (r) => r.total_score_per_day.toFixed(3),
    },
    {
      id: "avg_normalised", header: t("transparency.normalised"),
      headerTooltip: (
        <div className="space-y-3" dir="rtl">
          <p>הניקוד המנורמל מחושב לפי הניקוד ליום שלך ביחס לממוצע היחידה.</p>
          <BlockMath math="\text{ניקוד מנורמל} = \dfrac{\text{ניקוד ליום שלך}}{\text{ממוצע ניקוד ליום ביחידה}}" />
          <p className="text-xs text-gray-500 dark:text-gray-400">ניקוד 1.0 = בדיוק כמו הממוצע. מעל 1.0 = עשית יותר מהממוצע. מתחת 1.0 = עשית פחות.</p>
        </div>
      ),
      cell: (r) => r.avg_normalised.toFixed(3),
      sortValue: (r) => r.avg_normalised,
    },
    {
      id: "avg_effort",
      header: t("transparency.subunit_avg_effort"),
      cell: (r) => r.avg_effort > 0 ? (r.avg_effort * 100).toFixed(1) + "%" : "—",
      sortValue: (r) => r.avg_effort,
      exportValue: (r) => r.avg_effort > 0 ? (r.avg_effort * 100).toFixed(1) + "%" : "—",
    },
    {
      id: "cv_effort",
      header: t("transparency.subunit_cv_effort"),
      cell: (r) => {
        if (r.cv_effort === null) return "—";
        const pct = r.cv_effort * 100;
        const colorClass = pct < 25
          ? "text-green-600 dark:text-green-400"
          : pct < 50
            ? "text-yellow-600 dark:text-yellow-400"
            : "text-red-600 dark:text-red-400 font-medium";
        return <span className={colorClass}>{pct.toFixed(1)}%</span>;
      },
      sortValue: (r) => r.cv_effort ?? -1,
      exportValue: (r) => {
        if (r.cv_effort === null) return "—";
        return (r.cv_effort * 100).toFixed(1) + "%";
      },
    },
    {
      id: "sibling_gap",
      header: t("transparency.subunit_sibling_gap"),
      cell: (r) => <span className={gapColor(r.sibling_gap)}>{formatGap(r.sibling_gap)}</span>,
      sortValue: (r) => r.sibling_gap ?? -1,
      exportValue: (r) => formatGap(r.sibling_gap),
    },
    {
      id: "global_gap",
      header: t("transparency.subunit_global_gap"),
      cell: (r) => <span className={gapColor(r.global_gap)}>{formatGap(r.global_gap)}</span>,
      sortValue: (r) => r.global_gap ?? -1,
      exportValue: (r) => formatGap(r.global_gap),
    },
  ];

  if (transparencyForbidden) {
    return (
      <Layout>
        <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6" data-testid="transparency-page">
          <p className="text-sm text-red-500" dir="rtl">{t("transparency.no_permission")}</p>
        </section>
      </Layout>
    );
  }

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
                <button className="text-xs text-indigo-600 dark:text-indigo-300 hover:underline px-1" onClick={() => setTreeOpen((o) => !o)}>שנה</button>
              </div>
            ) : (
              <button
                className="flex items-center gap-1 text-sm text-indigo-600 dark:text-indigo-300 hover:underline"
                onClick={() => setTreeOpen((o) => !o)}
              >
                <span>🌳</span>
                <span>סנן לפי יחידה</span>
                <span className="text-xs">{treeOpen ? "▲" : "▼"}</span>
              </button>
            )}

            {treeOpen && (
              <div
                className="absolute left-0 top-full mt-1 z-20 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg p-2 min-w-64"
                dir="rtl"
              >
                <div className="flex items-center justify-between mb-1 px-1">
                  <span className="text-xs text-gray-500">בחר יחידה לסינון</span>
                  {selectedNodeId && (
                    <button className="text-xs text-red-500 hover:underline" onClick={clearFilter}>הצג הכל</button>
                  )}
                </div>
                <Combobox
                  items={sortNodesByTree(flatNodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
                  value={selectedNodeId ?? ""}
                  onChange={handleSelectNode}
                  placeholder="— כל הארגון —"
                  testId="transparency-unit-filter"
                />
              </div>
            )}
          </div>

          {tab === 0 && user?.role === "admin" && (
            <button
              className={`text-xs px-2 py-1 rounded border transition-colors ${showDebug ? "bg-amber-100 dark:bg-amber-900 border-amber-400 text-amber-800 dark:text-amber-200" : "border-gray-300 dark:border-gray-600 text-gray-500 hover:border-amber-400"}`}
              onClick={() => setShowDebug(d => !d)}
              title="הצג ערכי count-space לדיבאג הוגנות"
            >
              🔧 מצב דיבאג
            </button>
          )}
        </div>

        {/* Tabs */}
        <TabBar tabs={["חיילים", "תתי יחידות"]} active={tab} onChange={setTab} />

        {/* Summary cards */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3" dir="rtl">
          <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-center">
            <p className="text-xs text-gray-500 dark:text-gray-400">{t("transparency.avg_cumulative")}</p>
            <p className="text-lg font-semibold text-gray-800 dark:text-gray-100">{avgCumulative.toFixed(3)}</p>
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
          {tab === 0 && <FairnessCard stats={effortStats} helpVariant="soldiers" />}
          {tab === 1 && <FairnessCard stats={subEffortStats} helpVariant="subunits" />}
        </div>

        {tab === 0 && (
          <FairnessComponentsCard
            activeGroupKeys={activeGroupKeys}
            onGroupToggle={handleGroupToggle}
            onClearGroups={clearGroupFilter}
          />
        )}

        {showDebug && tab === 0 && (
          <div className="text-xs text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded p-2 space-y-1" dir="rtl">
            <p><strong>מצב דיבאג count-space (ערכי CP-SAT):</strong></p>
            <p><strong>C/D</strong> = 1/Wᵢ — משקל תורנות חדשה בחישוב עומס: חייל חדש → C/D גבוה (כל תורנות &ldquo;שוקלת&rdquo; יותר). ותיק → C/D נמוך.</p>
            <p><strong>effort_offset</strong> = int(עומס_רבעוני × 10⁹) — הערך ההיסטורי שמוזרק למודל ה-CP-SAT כנקודת התחלה לחישוב ההוגנות.</p>
            <p><strong>ה-μ</strong> שהאלגוריתם מכוון אליו = (Σ effort_offset + total_new_weight) / n_eligible — מחושב per-run על-פי הכשירויות הספציפיות של כל ריצה.</p>
            <p className="text-amber-600 dark:text-amber-400">האלגוריתם ממזער את שונות ה-effort בתוך כל קבוצת כשירות. חיילים עם effort נמוך מהממוצע יקבלו עדיפות בהקצאה הבאה.</p>
            {effortRange ? (
              <p><strong>Auto-range:</strong> min={effortRange.min.toLocaleString()} | max={effortRange.max.toLocaleString()} | range={effortRange.size.toLocaleString()} — דיוק לטיק: ~{effortRange.precisionPct.toFixed(4)}%</p>
            ) : (
              <p className="text-gray-400">Auto-range: אין נתוני effort_offset</p>
            )}
            <p><strong>count_offset</strong> = (effort_offset − range_min) × 1000 ÷ range_size — הערך ב-[0,1000] שה-CP-SAT מבצע עליו אופטימיזציה (ראה עמודה בטבלה)</p>
          </div>
        )}

        {/* Filter pills (soldiers tab only) */}
        {tab === 0 && (
          <div className="flex flex-wrap gap-3 items-center" dir="rtl">
            {activeGroupKeys.size > 0 && (
              <>
                {[...activeGroupKeys].map((key) => (
                  <div key={key} className="flex items-center gap-1">
                    <span className={`text-sm px-2 py-1 rounded-full border font-medium ${
                      key === "exempt"
                        ? "bg-orange-100 dark:bg-orange-950 text-orange-700 dark:text-orange-300 border-orange-400"
                        : "bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300 border-indigo-400"
                    }`}>
                      {key === "exempt" ? "פטורים / לא כשירים" : `קבוצה ${parseInt(key.replace("comp_", "")) + 1}`}
                    </span>
                    <button className="text-xs text-gray-400 hover:text-red-500 px-1" onClick={() => handleGroupToggle(groupSoldiersMap.get(key) ?? [], key)}>✕</button>
                  </div>
                ))}
                <div className="w-px h-5 bg-gray-300 dark:bg-gray-600 hidden sm:block" />
              </>
            )}
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
            <div className="flex justify-start" dir="ltr">
              <ExcelExportButton columns={soldierCols} rows={exportSoldierRows} filename="transparency.xlsx" />
            </div>
            <DataTable
              columns={soldierCols}
              data={visibleRows}
              filterPlaceholder={t("table.filter_placeholder")}
              defaultSort={[{ id: "effort_score", desc: true }]}
              rowClassName={(r) => (r.soldier_id === user?.id ? "bg-indigo-50 dark:bg-indigo-950" : "")}
              rowStyle={(r) => {
                const g = r._group;
                if (!g || g.compIndex < 0) return {};
                const color = COMPONENT_COLORS[g.compIndex % COMPONENT_COLORS.length];
                return { borderRight: `3px solid ${color}` };
              }}
              testId="transparency-table"
              onVisibleRowsChange={setExportSoldierRows}
            />
          </>
        )}

        {tab === 1 && (
          <>
            <div className="flex justify-start" dir="ltr">
              <ExcelExportButton columns={subCols} rows={exportSubRows} filename="sub-units.xlsx" />
            </div>
            <DataTable
              columns={subCols}
              data={subRows}
              filterPlaceholder={t("table.filter_placeholder")}
              onVisibleRowsChange={setExportSubRows}
            />
          </>
        )}
      </section>

      {treeOpen && <div className="fixed inset-0 z-10" onClick={() => setTreeOpen(false)} />}

      {/* Effort breakdown modal */}
      {effortBreakdown && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
          onClick={closeEffortBreakdown}
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
                onClick={closeEffortBreakdown}
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
                            title="חלק החייל מניקוד היחידה (ניקוד חייל / ניקוד יחידה), לפני תיקון נוכחות."
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
                          const adjDelta = parseFloat(q.adjustment_delta ?? "0");
                          return (
                            <tr key={q.quarter_label} className={`border-b dark:border-gray-700 ${q.is_partial ? "bg-indigo-50/40 dark:bg-indigo-950/20" : ""}`}>
                              <td className="py-2 text-gray-700 dark:text-gray-300 font-medium">
                                <span className={q.is_partial ? "italic" : ""}>{q.quarter_label}</span>
                                <span
                                  className="mr-1 text-gray-400 dark:text-gray-500 text-xs cursor-help"
                                  title={`${formatDate(q.quarter_start)} – ${formatDate(q.quarter_end)}`}
                                >
                                  ⓘ
                                </span>
                                {q.is_partial && <span className="mr-1 text-indigo-500 dark:text-indigo-300 text-xs font-normal not-italic">(חלקי)</span>}
                              </td>
                              <td className="py-2 text-right px-3 text-gray-700 dark:text-gray-300 tabular-nums">
                                <span>{parseFloat(q.soldier_score).toFixed(3)}</span>
                                {adjDelta !== 0 && (
                                  <span className={`block text-xs font-normal ${adjDelta > 0 ? "text-green-600 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}>
                                    {adjDelta > 0 ? "+" : ""}{adjDelta.toFixed(3)} התאמה
                                  </span>
                                )}
                              </td>
                              <td className="py-2 text-right px-3 text-gray-500 dark:text-gray-400 tabular-nums">
                                {unitScore > 0 ? unitScore.toFixed(3) : <span className="italic text-xs">ללא</span>}
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
                        <p className="mt-2 text-xs text-indigo-700 dark:text-indigo-300">
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

                    {/* Step 0: line items — which duties/adjustments fed each quarter */}
                    {qs.some((q) => (q.contributions ?? []).length > 0) && (
                      <div>
                        <p className="font-medium text-gray-700 dark:text-gray-300 mb-1">
                          שלב 0 — מאיפה מגיע ניקוד החייל בכל רבעון
                        </p>
                        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                          {qs.filter((q) => (q.contributions ?? []).length > 0).map((q, qi) => (
                            <div key={q.quarter_label} className={qi > 0 ? "border-t border-gray-100 dark:border-gray-700" : ""}>
                              <div className="px-2 py-1 font-medium text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-900">
                                {q.quarter_label}
                              </div>
                              {q.contributions.map((c, ci) => (
                                <div
                                  key={`${q.quarter_label}-${ci}`}
                                  className="flex items-center justify-between gap-2 px-2 py-1 text-gray-600 dark:text-gray-400"
                                >
                                  <span className="flex flex-col min-w-0">
                                    <span className="truncate">
                                      {c.kind === "adjustment" && <span className="text-green-600 dark:text-green-400 ml-1">✏️</span>}
                                      {c.label}
                                      {c.start_date && c.end_date && (
                                        <span className="text-gray-400 dark:text-gray-500"> ({formatDate(c.start_date)}–{formatDate(c.end_date)})</span>
                                      )}
                                    </span>
                                    {c.detail && <span className="text-xs text-gray-400 dark:text-gray-500">{c.detail}</span>}
                                  </span>
                                  <span className="tabular-nums shrink-0">
                                    {c.kind === "duty" ? `${c.days} ${c.days === 1 ? "יום" : "ימים"} × ${parseFloat(c.multiplier).toFixed(2)} = ` : ""}
                                    <strong className="text-indigo-600 dark:text-indigo-300">{parseFloat(c.score).toFixed(3)}</strong>
                                  </span>
                                </div>
                              ))}
                              <div className="flex justify-between px-2 py-1 border-t border-gray-100 dark:border-gray-700 text-gray-500 dark:text-gray-400">
                                <span>סה״כ ניקוד חייל ברבעון</span>
                                <span className="tabular-nums font-medium">{parseFloat(q.soldier_score).toFixed(3)}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Step 1: A — per-row arithmetic */}
                    <div>
                      <p className="font-medium text-indigo-700 dark:text-indigo-300 mb-1">
                        שלב 1 — עומס שנצבר (A): לכל רבעון, ניקוד החייל כפול אחוז הנוכחות
                      </p>
                      <div className="bg-white dark:bg-gray-800 border border-indigo-100 dark:border-indigo-900 rounded-lg overflow-hidden">
                        {qs.map((q, i) => {
                          const ss = parseFloat(q.soldier_score);
                          const us = parseFloat(q.unit_score);
                          const ap = (parseFloat(q.active_frac) * 100).toFixed(0);
                          const hasScore = us > 0;
                          const aTerm = ss * parseFloat(q.active_frac);
                          return (
                            <div
                              key={q.quarter_label}
                              className={`flex items-center justify-between gap-2 px-2 py-1.5 ${i > 0 ? "border-t border-gray-100 dark:border-gray-700" : ""}`}
                            >
                              <span className="font-medium text-gray-600 dark:text-gray-400 shrink-0 w-14">{q.quarter_label}</span>
                              {hasScore ? (
                                <span className="tabular-nums text-gray-600 dark:text-gray-400">
                                  <InlineMath math={`${ap}\\% \\times ${ss.toFixed(3)} = `} />
                                  <strong className="text-indigo-600 dark:text-indigo-300">{aTerm.toFixed(3)}</strong>
                                </span>
                              ) : (
                                <span className="text-gray-400 dark:text-gray-500 italic">
                                  אין תורנויות ביחידה — תרומה 0
                                </span>
                              )}
                            </div>
                          );
                        })}
                        <div className="border-t border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-950 px-2 py-1.5 flex justify-between font-semibold text-indigo-700 dark:text-indigo-300">
                          <span
                            className="cursor-help underline decoration-dotted"
                            title="סכום התרומות (העמודה הימנית) מכל השורות למעלה — ניקוד גולמי, לא אחוז. עדיין לא מחולק בניקוד היחידה (זה קורה בנוסחה הסופית)."
                          >
                            סכום = A
                          </span>
                          <span className="tabular-nums">{A.toFixed(3)}</span>
                        </div>
                      </div>
                    </div>

                    {/* Step 2: W — sum of presences (duty-quarters only) + final formula */}
                    <div>
                      <p className="font-medium text-amber-700 dark:text-amber-300 mb-1">
                        שלב 2 — היסטוריה כוללת (W): לכל רבעון, ניקוד היחידה כפול אחוז הנוכחות
                      </p>
                      <div className="bg-white dark:bg-gray-800 border border-amber-100 dark:border-amber-900 rounded-lg overflow-hidden">
                        {qs.filter((q) => parseFloat(q.unit_score) > 0).map((q, i) => {
                          const us = parseFloat(q.unit_score);
                          const ap = (parseFloat(q.active_frac) * 100).toFixed(0);
                          const wTerm = us * parseFloat(q.active_frac);
                          return (
                            <div
                              key={q.quarter_label}
                              className={`flex items-center justify-between gap-2 px-2 py-1.5 text-gray-600 dark:text-gray-400 ${i > 0 ? "border-t border-gray-100 dark:border-gray-700" : ""}`}
                            >
                              <span className="font-medium text-gray-600 dark:text-gray-400 w-14">{q.quarter_label}</span>
                              <span className="tabular-nums">
                                <InlineMath math={`${ap}\\% \\times ${us.toFixed(3)} = `} />
                                <strong>{wTerm.toFixed(3)}</strong>
                              </span>
                            </div>
                          );
                        })}
                        {qs.some((q) => parseFloat(q.unit_score) === 0) && (
                          <div className="px-2 py-1.5 border-t border-gray-100 dark:border-gray-700 text-xs text-gray-400 dark:text-gray-500 italic">
                            רבעונות ריקים (ללא תורנויות ביחידה) אינם נספרים ב-W
                          </div>
                        )}
                        <div className="border-t border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950 px-2 py-1.5 flex justify-between font-semibold text-amber-700 dark:text-amber-300">
                          <span
                            className="cursor-help underline decoration-dotted"
                            title="סכום התרומות (העמודה הימנית) מכל השורות למעלה — ניקוד גולמי של כל היחידה, לא אחוז."
                          >
                            סכום = W
                          </span>
                          <span className="tabular-nums">{W.toFixed(3)}</span>
                        </div>
                      </div>
                      <div className="mt-2 bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 rounded-lg px-3 py-2">
                        <p className="text-xs text-gray-500 dark:text-gray-400 mb-0.5"><InlineMath math="\text{עומס} = \dfrac{A}{W}" /></p>
                        <p className="font-bold text-base text-indigo-700 dark:text-indigo-300 tabular-nums">
                          <InlineMath math={`\\dfrac{${A.toFixed(3)}}{${W.toFixed(3)}} = ${(effort * 100).toFixed(2)}\\%`} />
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
 
