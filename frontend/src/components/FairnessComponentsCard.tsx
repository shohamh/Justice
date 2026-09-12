import { useEffect, useRef, useState, type MouseEvent } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer } from "recharts";
import { getFairnessComponents, type FairnessComponent, type FairnessComponents, type FairnessSoldier } from "../api/scoring";
import SoldierLink from "./SoldierLink";
import FairnessSpreadBreakdownModal, { type FairnessSpreadBreakdownSoldier } from "./FairnessSpreadBreakdownModal";

function eligibilityDistribution(soldiers: FairnessSoldier[]): { count: number; soldiers: number }[] {
  const freq: Record<number, number> = {};
  for (const s of soldiers) {
    freq[s.eligible_type_count] = (freq[s.eligible_type_count] ?? 0) + 1;
  }
  return Object.entries(freq)
    .map(([count, soldiers]) => ({ count: Number(count), soldiers }))
    .sort((a, b) => a.count - b.count);
}

// Colors assigned to each fairness component — shared with TransparencyPage for row coloring
export const COMPONENT_COLORS = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#f97316", "#84cc16"];
const PIE_COLORS = ["#6366f1", "#10b981", "#f59e0b", "#f43f5e", "#0ea5e9", "#a855f7"];

function cvBadge(cv: number): string {
  if (cv < 0.25) return "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300";
  if (cv <= 0.5) return "bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-300";
  return "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300";
}

interface BucketBurdenShareStats { mean: number; stddev: number; cv: number; min: number; max: number }

/** Burden-share spread (same CV/stddev/range shape as the group-level badge)
 * computed for just the soldiers sharing one eligible-type count, so
 * selecting a count row can show how equally *that* sub-group carries load —
 * null below 2 soldiers, same convention as the group-level stats. */
function bucketBurdenShareStats(soldiers: FairnessSoldier[], count: number): BucketBurdenShareStats | null {
  const shares = soldiers.filter((s) => s.eligible_type_count === count).map((s) => s.burden_share);
  if (shares.length < 2) return null;
  const mean = shares.reduce((a, b) => a + b, 0) / shares.length;
  const variance = shares.reduce((a, b) => a + (b - mean) ** 2, 0) / shares.length;
  const stddev = Math.sqrt(variance);
  return { mean, stddev, cv: mean !== 0 ? stddev / mean : 0, min: Math.min(...shares), max: Math.max(...shares) };
}

/** Soldiers sharing an eligible-type COUNT can still differ in which specific
 * duty types they're eligible for. This unions the real duty-type ids across
 * every soldier in every selected bucket, so hovering/clicking (or ctrl+
 * clicking several) "5 חיילים — 2 סוגים" rows can name and highlight the
 * actual duty types involved (not just the counts). */
function typeIdsForCounts(soldiers: FairnessSoldier[], counts: Set<number>): Set<string> {
  if (counts.size === 0) return new Set();
  const ids = new Set<string>();
  for (const s of soldiers) {
    if (counts.has(s.eligible_type_count)) {
      for (const tid of s.eligible_duty_type_ids) ids.add(tid);
    }
  }
  return ids;
}

function FairnessComponentCard({
  c, i, isActive, onGroupToggle, onToggle,
}: {
  c: FairnessComponent;
  i: number;
  isActive: boolean;
  onGroupToggle?: (soldierIds: string[], key: GroupKey) => void;
  onToggle: () => void;
}) {
  const [hoveredCount, setHoveredCount] = useState<number | null>(null);
  // The stats panel floats beside (not below) the row on desktop, so the
  // mouse has to cross a small gap to reach it — clearing hoveredCount the
  // instant the row itself is left would unmount the panel mid-crossing,
  // before the mouse ever gets there. Closing on a short delay (cancelled if
  // the mouse re-enters either the row or the panel itself) gives it time to
  // arrive first. Once the delay actually elapses, the panel stays mounted a
  // little longer still (closingCount) so a CSS opacity transition can play
  // instead of the panel just vanishing.
  const hoveredCountRef = useRef(hoveredCount);
  hoveredCountRef.current = hoveredCount;
  const [closingCount, setClosingCount] = useState<number | null>(null);
  const hoverCloseTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fadeOutTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (hoverCloseTimeoutRef.current) clearTimeout(hoverCloseTimeoutRef.current);
    if (fadeOutTimeoutRef.current) clearTimeout(fadeOutTimeoutRef.current);
  }, []);
  function cancelHoverClose() {
    if (hoverCloseTimeoutRef.current) {
      clearTimeout(hoverCloseTimeoutRef.current);
      hoverCloseTimeoutRef.current = null;
    }
    if (fadeOutTimeoutRef.current) {
      clearTimeout(fadeOutTimeoutRef.current);
      fadeOutTimeoutRef.current = null;
    }
    setClosingCount(null);
  }
  function scheduleHoverClose(count: number) {
    cancelHoverClose();
    hoverCloseTimeoutRef.current = setTimeout(() => {
      if (hoveredCountRef.current !== count) return;
      setHoveredCount(null);
      setClosingCount(count);
      fadeOutTimeoutRef.current = setTimeout(() => {
        setClosingCount((prev) => (prev === count ? null : prev));
      }, 150);
    }, 250);
  }
  // A plain click replaces the whole selection with just that one count; a
  // ctrl/cmd+click toggles that count in or out of the current selection
  // without touching the others, so several sub-groups can be combined as a
  // filter for the soldier list below.
  const [lockedCounts, setLockedCounts] = useState<Set<number>>(new Set());
  const [breakdown, setBreakdown] = useState<{ title: string; soldiers: FairnessSpreadBreakdownSoldier[] } | null>(null);
  // A hover-only preview never fights an existing multi-selection — it's
  // only shown when nothing is locked yet.
  const activeCounts = lockedCounts.size > 0
    ? lockedCounts
    : (hoveredCount != null ? new Set([hoveredCount]) : new Set<number>());

  function openBreakdown(title: string, forSoldiers: FairnessSoldier[], e: { stopPropagation: () => void }) {
    e.stopPropagation();
    setBreakdown({
      title,
      soldiers: forSoldiers.map((s) => ({ id: s.soldier_id, name: s.full_name, burdenShare: s.burden_share })),
    });
  }

  const sortedSoldiers = [...c.soldiers].sort((a, b) => a.burden_share - b.burden_share);
  const mean = c.burden_share?.mean ?? null;
  const burdenShareMin = sortedSoldiers[0]?.burden_share ?? 0;
  const burdenShareMax = sortedSoldiers[sortedSoldiers.length - 1]?.burden_share ?? 1;
  const burdenShareRange = burdenShareMax - burdenShareMin || 1;
  const dist = eligibilityDistribution(c.soldiers);
  const typeCountColor = new Map(dist.map((d, idx) => [d.count, PIE_COLORS[idx % PIE_COLORS.length]]));

  const highlightedTypeIds = typeIdsForCounts(c.soldiers, activeCounts);

  function toggleLock(count: number, e: MouseEvent) {
    e.stopPropagation();
    const multiSelect = e.ctrlKey || e.metaKey;
    setLockedCounts((prev) => {
      const next = new Set(prev);
      if (multiSelect) {
        if (next.has(count)) next.delete(count);
        else next.add(count);
      } else if (next.size === 1 && next.has(count)) {
        next.clear();
      } else {
        next.clear();
        next.add(count);
      }
      return next;
    });
    // On touch devices a tap fires a synthetic mouseenter (setting hoveredCount)
    // but no mouseleave ever follows (there's no pointer to leave with), so
    // hoveredCount would otherwise keep the row looking selected via the
    // hover-preview fallback even after unlocking it here.
    setHoveredCount(null);
  }

  return (
    <>
    <div
      className={`w-full text-right border rounded-lg transition-colors ${
        isActive
          ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950 ring-1 ring-indigo-400"
          : onGroupToggle
            ? "border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:border-indigo-600"
            : "border-gray-200 dark:border-gray-700"
      }`}
      style={{ borderRightColor: COMPONENT_COLORS[i % COMPONENT_COLORS.length], borderRightWidth: 4 }}
    >
      {/* Clickable header */}
      <div
        className={`p-3 ${onGroupToggle ? "cursor-pointer" : ""}`}
        onClick={onToggle}
      >
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <span className="text-sm text-gray-700 dark:text-gray-200">
            <span className="font-semibold">{c.soldier_count}</span> חיילים
            {isActive && <span className="mr-2 text-xs text-indigo-600 dark:text-indigo-300 font-normal">✓ נבחר — לחץ לסינון בטבלה</span>}
          </span>
          <div className="flex items-center gap-2">
            {c.burden_share ? (
              <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded ${cvBadge(c.burden_share.cv)}`}>
                פיזור CV {(c.burden_share.cv * 100).toFixed(0)}%
                <button
                  type="button"
                  onClick={(e) => openBreakdown(`${c.soldier_count} חיילים`, c.soldiers, e)}
                  className="text-current opacity-70 hover:opacity-100 border border-current rounded-full w-3.5 h-3.5 inline-flex items-center justify-center leading-none"
                  aria-label="מה זה CV? הצג פירוט חישוב"
                >
                  ?
                </button>
              </span>
            ) : (
              <span className="text-xs text-gray-400">פחות מ-2 חיילים</span>
            )}
            {c.burden_share && (
              <span className="text-xs text-gray-400">
                טווח: {(burdenShareMin * 100).toFixed(1)}%–{(burdenShareMax * 100).toFixed(1)}%
              </span>
            )}
          </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {c.duty_types.map((dt) => (
            <span
              key={dt.id}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${
                activeCounts.size > 0 && highlightedTypeIds.has(dt.id)
                  ? "bg-indigo-600 text-white dark:bg-indigo-500"
                  : "bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300"
              }`}
            >
              {dt.name}
            </span>
          ))}
        </div>
        {(() => {
          if (dist.length === 0) return null;
          return (
            <div className="mt-2 flex items-center gap-3 md:pr-16">
              <div data-testid="fairness-component-pie-chart" className="shrink-0" style={{ width: 96, height: 96 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={dist}
                      dataKey="soldiers"
                      cx="50%"
                      cy="50%"
                      innerRadius={28}
                      outerRadius={44}
                      paddingAngle={2}
                    >
                      {dist.map((d, idx) => (
                        <Cell
                          key={idx}
                          fill={PIE_COLORS[idx % PIE_COLORS.length]}
                          stroke={activeCounts.has(d.count) ? "currentColor" : undefined}
                          strokeWidth={activeCounts.has(d.count) ? 2 : undefined}
                          className={activeCounts.has(d.count) ? "text-gray-700 dark:text-gray-200" : undefined}
                          onMouseEnter={() => setHoveredCount(d.count)}
                          onMouseLeave={() => setHoveredCount(null)}
                          onClick={(e) => toggleLock(d.count, e)}
                          style={{ cursor: "pointer" }}
                        />
                      ))}
                    </Pie>
                    {/* No Recharts <Tooltip>: the same info (duty types, spread,
                        breakdown) is already surfaced by the legend row's own
                        highlight/stats-line/breakdown-link below, and the
                        tooltip was a recurring source of bugs (touch getting it
                        stuck open, its content running off-screen, RTL sidebar
                        clipping) for something the highlight alone now covers. */}
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="min-w-0 text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
                {dist.map((d, idx) => (
                  <div key={d.count} className="relative">
                    <div
                      className={`flex items-center gap-1 rounded px-1 -mx-1 cursor-pointer ${
                        activeCounts.has(d.count) ? "bg-indigo-100 dark:bg-indigo-900" : ""
                      }`}
                      onMouseEnter={() => { cancelHoverClose(); setHoveredCount(d.count); }}
                      onMouseLeave={() => scheduleHoverClose(d.count)}
                      onClick={(e) => toggleLock(d.count, e)}
                    >
                      <span
                        className="inline-block w-2 h-2 rounded-full shrink-0"
                        style={{ background: PIE_COLORS[idx % PIE_COLORS.length] }}
                      />
                      <span>{d.soldiers} חיילים — {d.count} סוגים</span>
                    </div>
                    {(activeCounts.has(d.count) || closingCount === d.count) && (() => {
                      const stats = bucketBurdenShareStats(c.soldiers, d.count);
                      const visible = activeCounts.has(d.count);
                      return (
                        // On desktop this floats to the left of the row (into
                        // the card's own empty space) instead of pushing the
                        // rows below it down the page on every hover — that
                        // reflow was reported as distracting when scanning
                        // several sub-groups in a row. Mobile has no such
                        // spare width, so it stays in normal flow there.
                        // The opacity transition covers the closingCount
                        // window above, so a hover-driven close fades out
                        // instead of the panel just vanishing.
                        <div
                          className={`mr-3 md:mr-0 text-indigo-600 dark:text-indigo-300 md:absolute md:top-0 md:right-[calc(100%+0.75rem)] md:z-10 md:w-64 md:rounded-lg md:border md:border-indigo-200 md:bg-white md:p-2 md:shadow-lg md:dark:border-indigo-700 md:dark:bg-gray-800 transition-opacity duration-150 ${visible ? "opacity-100" : "opacity-0"}`}
                          onMouseEnter={() => { cancelHoverClose(); setHoveredCount(d.count); }}
                          onMouseLeave={() => scheduleHoverClose(d.count)}
                        >
                          <div className="flex items-center flex-wrap gap-1">
                            {stats ? (
                              <>
                                <span>
                                  טווח: {(stats.min * 100).toFixed(1)}%–{(stats.max * 100).toFixed(1)}% · סטיית תקן: ±{(stats.stddev * 100).toFixed(1)}%
                                </span>
                                <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded ${cvBadge(stats.cv)}`}>
                                  פיזור CV {(stats.cv * 100).toFixed(0)}%
                                  <button
                                    type="button"
                                    onClick={(e) => openBreakdown(
                                      `${d.soldiers} חיילים — ${d.count} סוגים`,
                                      c.soldiers.filter((s) => s.eligible_type_count === d.count),
                                      e,
                                    )}
                                    className="text-current opacity-70 hover:opacity-100 border border-current rounded-full w-3.5 h-3.5 inline-flex items-center justify-center leading-none"
                                    aria-label="מה זה CV? הצג פירוט חישוב"
                                  >
                                    ?
                                  </button>
                                </span>
                              </>
                            ) : (
                              <span>פחות מ-2 חיילים בקבוצה זו</span>
                            )}
                          </div>
                        </div>
                      );
                    })()}
                  </div>
                ))}
              </div>
            </div>
          );
        })()}
      </div>

      {/* Ranked candidate list — visible when the whole group is selected, or
          when one or more subgroup (eligible-type count) rows are hovered/
          locked (ctrl/cmd+click locks several at once). With any subgroup
          active, the list is FILTERED down to just their soldiers (not
          merely tinted within the full list) — a group can run to hundreds
          of soldiers, making a handful of highlighted rows within them
          practically unfindable by scrolling (confirmed live). Filtered
          rank is local to the selection, so the "top 3 candidate" framing
          (a whole-group, next-duty-assignment concept) is dropped for it. */}
      {(isActive || activeCounts.size > 0) && sortedSoldiers.length > 0 && (() => {
        const filtered = activeCounts.size > 0;
        const displayedSoldiers = filtered
          ? sortedSoldiers.filter((s) => activeCounts.has(s.eligible_type_count))
          : sortedSoldiers;
        return (
        <div className="border-t border-indigo-200 dark:border-indigo-700 px-3 pb-3 pt-2 overflow-x-auto">
          <p className="text-xs font-semibold text-indigo-700 dark:text-indigo-300 mb-2">
            {filtered
              ? `חיילים בקבוצות שנבחרו (${displayedSoldiers.length}), ממוינים לפי חלק בנטל:`
              : "סדר עדיפויות לתורנות הבאה (חלק בנטל עולה — מקום 1 מועמד ראשי):"}
          </p>
          <div className="space-y-1 min-w-[260px]">
            {displayedSoldiers.map((s, rank) => {
              const burdenSharePct = (s.burden_share * 100).toFixed(2);
              const dev = mean != null ? s.burden_share - mean : null;
              const devStr = dev != null
                ? (dev >= 0 ? `+${(dev * 100).toFixed(1)}%` : `${(dev * 100).toFixed(1)}%`)
                : null;
              const devCls = dev != null && dev > 0.005
                ? "text-red-500 dark:text-red-400"
                : dev != null && dev < -0.005
                  ? "text-green-600 dark:text-green-400"
                  : "text-gray-400";
              const barWidth = Math.round(((s.burden_share - burdenShareMin) / burdenShareRange) * 100);
              const isCandidate = !filtered && rank < 3;
              return (
                <div
                  key={s.soldier_id}
                  className="flex items-center gap-2 pr-1 border-r-2 rounded transition-colors"
                  style={{ borderRightColor: typeCountColor.get(s.eligible_type_count) ?? "transparent" }}
                >
                  <span className={`text-xs w-5 text-center font-bold shrink-0 ${isCandidate ? "text-indigo-600 dark:text-indigo-300" : "text-gray-400"}`}>
                    {rank + 1}
                  </span>
                  <SoldierLink
                    id={s.soldier_id}
                    name={s.full_name}
                    className="text-xs w-28 truncate shrink-0 block text-right"
                  />
                  <div className="flex-1 bg-gray-200 dark:bg-gray-700 rounded h-1.5 overflow-hidden">
                    <div
                      className={`h-full rounded ${isCandidate ? "bg-indigo-500" : "bg-gray-400 dark:bg-gray-500"}`}
                      style={{ width: `${Math.max(barWidth, 2)}%` }}
                    />
                  </div>
                  <span className="text-xs tabular-nums text-gray-500 dark:text-gray-400 w-12 text-left shrink-0">
                    {burdenSharePct}%
                  </span>
                  {devStr && (
                    <span className={`text-xs tabular-nums w-12 text-left shrink-0 ${devCls}`}>
                      {devStr}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          {!filtered && mean != null && (
            <p className="text-xs text-gray-400 mt-2">
              ממוצע קבוצה: {(mean * 100).toFixed(2)}% · סטיית תקן: {c.burden_share ? (c.burden_share.stddev * 100).toFixed(2) : "—"}%
            </p>
          )}
        </div>
        );
      })()}
    </div>
    {breakdown && (
      <FairnessSpreadBreakdownModal
        title={breakdown.title}
        soldiers={breakdown.soldiers}
        onClose={() => setBreakdown(null)}
      />
    )}
    </>
  );
}

export type GroupKey = `comp_${number}` | "exempt";

export interface FairnessComponentsCardProps {
  activeGroupKeys?: Set<GroupKey>;
  onGroupToggle?: (soldierIds: string[], key: GroupKey) => void;
  onClearGroups?: () => void;
}

/**
 * פיזור חלק בנטל per connected component of soldiers who do the same duties.
 * Splits the single global CV — which is inflated by soldiers exempt from
 * everything and by mixing groups that can't substitute for each other — into a
 * per-group spread plus the count of soldiers exempt from all duties.
 */
export default function FairnessComponentsCard({ activeGroupKeys, onGroupToggle, onClearGroups }: FairnessComponentsCardProps) {
  const [data, setData] = useState<FairnessComponents | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getFairnessComponents().then(setData).catch(() => setFailed(true));
  }, []);

  if (failed || !data) return null;

  const anyActive = (activeGroupKeys?.size ?? 0) > 0;

  function ids(soldiers: FairnessSoldier[]) {
    return soldiers.map((s) => s.soldier_id);
  }

  return (
    <div dir="rtl" className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="font-semibold text-gray-800 dark:text-gray-100">פיזור חלק בנטל לפי קבוצות כשירות</h3>
        {anyActive && onClearGroups && (
          <button className="text-xs text-red-500 hover:underline" onClick={onClearGroups}>
            הצג כל החיילים ✕
          </button>
        )}
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
        לחץ על קבוצה לסינון הטבלה (ניתן לבחור כמה קבוצות). כל קבוצה היא אוסף חיילים שמבצעים את אותן תורנויות (מחוברים דרך סוגי תורנות משותפים).
        הפיזור (CV) מחושב בנפרד לכל קבוצה — כך רואים את ההוגנות האמיתית בתוך כל קבוצה, בלי עיוות
        מחיילים שאינם כשירים לאותן תורנויות.
      </p>
      <div className="space-y-2">
        {data.components.map((c, i) => {
          const key: GroupKey = `comp_${i}`;
          return (
            <FairnessComponentCard
              key={i}
              c={c}
              i={i}
              isActive={activeGroupKeys?.has(key) ?? false}
              onGroupToggle={onGroupToggle}
              onToggle={() => onGroupToggle?.(ids(c.soldiers), key)}
            />
          );
        })}

        {/* Exempt / can't-do-any-duty group */}
        {data.exempt_from_all.count > 0 && (() => {
          const key: GroupKey = "exempt";
          const isActive = activeGroupKeys?.has(key) ?? false;
          return (
            <button
              type="button"
              className={`w-full text-right border rounded-lg p-3 transition-colors ${
                isActive
                  ? "border-orange-500 bg-orange-50 dark:bg-orange-950 ring-1 ring-orange-400"
                  : onGroupToggle
                    ? "border-gray-200 dark:border-gray-700 hover:border-orange-300 dark:hover:border-orange-600 hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer"
                    : "border-gray-200 dark:border-gray-700"
              }`}
              onClick={() => onGroupToggle?.(ids(data.exempt_from_all.soldiers), key)}
            >
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="text-sm text-gray-700 dark:text-gray-200">
                  <span className="font-semibold">{data.exempt_from_all.count}</span> חיילים
                  {isActive && <span className="mr-2 text-xs text-orange-600 dark:text-orange-400 font-normal">✓ נבחר</span>}
                </span>
                <span className="text-xs font-semibold px-2 py-0.5 rounded bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300">
                  פטורים / לא כשירים לתורנויות
                </span>
              </div>
              <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
                חיילים עם פטור גלובלי או שאינם כשירים לאף סוג תורנות
              </p>
            </button>
          );
        })()}
      </div>
    </div>
  );
}
