import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Loader2 } from "lucide-react";
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

const DEVIATION_NEUTRAL: [number, number, number] = [156, 163, 175]; // gray-400 — at the mean
const DEVIATION_HIGH: [number, number, number] = [239, 68, 68]; // red-500 — fully above the mean (|z| >= capZ)
const DEVIATION_LOW: [number, number, number] = [34, 197, 94]; // green-500 — fully below the mean (|z| >= capZ)

/** The color this soldier's position would have on one continuous
 * gray→red (or gray→green) spectrum spanning the whole track — i.e. the
 * same color a bar reaching exactly this far would end in in a full-length
 * version of that spectrum, not always the fully-saturated endpoint
 * regardless of distance. A soldier only 30% of the way to the cap gets a
 * gradient that itself only reaches 30% of the way to red/green. */
function deviationEndColor(z: number, capZ: number): string {
  const t = Math.min(Math.abs(z), capZ) / capZ;
  const target = z >= 0 ? DEVIATION_HIGH : DEVIATION_LOW;
  const [r, g, b] = DEVIATION_NEUTRAL.map((c, i) => Math.round(c + (target[i] - c) * t));
  return `rgb(${r}, ${g}, ${b})`;
}
const DEVIATION_NEUTRAL_RGB = `rgb(${DEVIATION_NEUTRAL.join(", ")})`;

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
  // Hovering always previews on top of whatever's locked — previously a
  // hover was ignored entirely once anything was locked, so after clicking
  // one sub-group there was no way to even glance at another without first
  // unlocking (reported live: "after clicking one subgroup I can't hover on
  // others"). Moving away just drops back to the locked set, since
  // hoveredCount resets to null.
  const activeCounts = new Set(lockedCounts);
  if (hoveredCount != null) activeCounts.add(hoveredCount);

  function openBreakdown(title: string, forSoldiers: FairnessSoldier[], e: { stopPropagation: () => void }) {
    e.stopPropagation();
    setBreakdown({
      title,
      soldiers: forSoldiers.map((s) => ({ id: s.soldier_id, name: s.full_name, burdenShare: s.burden_share })),
    });
  }

  const sortedSoldiers = [...c.soldiers].sort((a, b) => a.burden_share - b.burden_share);
  const mean = c.burden_share?.mean ?? null;
  const stddev = c.burden_share?.stddev ?? null;
  const burdenShareMin = sortedSoldiers[0]?.burden_share ?? 0;
  const burdenShareMax = sortedSoldiers[sortedSoldiers.length - 1]?.burden_share ?? 1;
  // Burden share is often heavily right-skewed (many soldiers near 0%, a
  // handful carrying most of the load) — CV over 100% is common — so a
  // fixed statistical cap like ±2.5σ (roughly right for a normal
  // distribution) badly underestimates the real spread: with mean≈0.3% and
  // stddev≈0.5%, ±2.5σ only covers ±1.4 points while actual shares ranged
  // 0%–4.2% (some soldiers 7σ out), pegging most of the high-burden group
  // to the same maxed-out bar with no way to tell them apart. Capping at
  // the group's own largest actual deviation instead means the true
  // extremes reach the full bar/color and everyone else is scaled against
  // what's actually observed here, not a one-size-fits-all constant.
  const maxAbsZ = stddev && mean != null
    ? Math.max(1, ...c.soldiers.map((s) => Math.abs((s.burden_share - mean) / stddev)))
    : 1;
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
              <button
                type="button"
                onClick={(e) => openBreakdown(`${c.soldier_count} חיילים`, c.soldiers, e)}
                className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded hover:brightness-110 dark:hover:brightness-125 transition-[filter] ${cvBadge(c.burden_share.cv)}`}
                aria-label="מה זה CV? הצג פירוט חישוב"
              >
                פיזור CV {(c.burden_share.cv * 100).toFixed(0)}%
                <span aria-hidden="true" className="text-current opacity-70 border border-current rounded-full w-3.5 h-3.5 inline-flex items-center justify-center leading-none">
                  ?
                </span>
              </button>
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
                                <button
                                  type="button"
                                  onClick={(e) => openBreakdown(
                                    `${d.soldiers} חיילים — ${d.count} סוגים`,
                                    c.soldiers.filter((s) => s.eligible_type_count === d.count),
                                    e,
                                  )}
                                  className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded hover:brightness-110 dark:hover:brightness-125 transition-[filter] ${cvBadge(stats.cv)}`}
                                  aria-label="מה זה CV? הצג פירוט חישוב"
                                >
                                  פיזור CV {(stats.cv * 100).toFixed(0)}%
                                  <span aria-hidden="true" className="text-current opacity-70 border border-current rounded-full w-3.5 h-3.5 inline-flex items-center justify-center leading-none">
                                    ?
                                  </span>
                                </button>
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
          <div className="flex items-center gap-1 sm:gap-2 pr-1 text-[10px] text-gray-400 dark:text-gray-500 whitespace-nowrap">
            <span className="w-4 sm:w-5 shrink-0" />
            <span className="w-16 sm:w-28 shrink-0 text-right">חייל</span>
            <span className="flex-1 text-center">מהממוצע</span>
            <span className="w-10 sm:w-12 text-left shrink-0">בנטל</span>
            {mean != null && <span className="w-10 sm:w-12 text-left shrink-0">סטייה</span>}
          </div>
          <div className="space-y-1 min-w-[230px]">
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
              // Position on a bell curve centered on the group mean, not a
              // min–max stretch of just this list — z is how many standard
              // deviations this soldier sits from average, so someone at the
              // mean sits at the center line regardless of the group's own
              // spread, and the bar only grows long when they're genuinely
              // far from typical (previously a top-of-range value like 4%
              // rendered as a nearly-full bar purely because it happened to
              // be the largest in a low-spread group, not because 4% is
              // actually extreme).
              const z = dev != null && stddev ? dev / stddev : null;
              const magnitudePct = z != null ? Math.min(Math.abs(z), maxAbsZ) / maxAbsZ * 50 : 0;
              const isCandidate = !filtered && rank < 3;
              return (
                <div
                  key={s.soldier_id}
                  className="flex items-center gap-1 sm:gap-2 pr-1 border-r-2 rounded transition-colors"
                  style={{ borderRightColor: typeCountColor.get(s.eligible_type_count) ?? "transparent" }}
                >
                  <span className={`text-xs w-4 sm:w-5 text-center font-bold shrink-0 ${isCandidate ? "text-indigo-600 dark:text-indigo-300" : "text-gray-400"}`}>
                    {rank + 1}
                  </span>
                  <SoldierLink
                    id={s.soldier_id}
                    name={s.full_name}
                    className="text-xs w-16 sm:w-28 truncate shrink-0 block text-right"
                  />
                  {/* Fills from the center line (the group mean) toward
                      whichever side this soldier sits on, growing only as
                      far as their actual distance from average (in standard
                      deviations) — and the fill itself fades from neutral
                      gray at the center to this soldier's own position on a
                      full gray→red/green spectrum (deviationEndColor), so
                      someone only 30% of the way to the cap gets a gradient
                      that itself only reaches 30% of the way to red/green,
                      not the fully-saturated color every bar would
                      otherwise end in regardless of how far it reaches. */}
                  <div className="relative flex-1 bg-gray-200 dark:bg-gray-700 rounded h-1.5" title="מרחק מהממוצע">
                    <div className="absolute inset-y-0 right-1/2 w-px bg-gray-400 dark:bg-gray-500" />
                    {z != null && (
                      <div
                        data-testid={`deviation-bar-${s.soldier_id}`}
                        className="absolute inset-y-0 rounded"
                        style={
                          z >= 0
                            ? { left: "50%", width: `${magnitudePct}%`, background: `linear-gradient(to right, ${DEVIATION_NEUTRAL_RGB}, ${deviationEndColor(z, maxAbsZ)})` }
                            : { right: "50%", width: `${magnitudePct}%`, background: `linear-gradient(to left, ${DEVIATION_NEUTRAL_RGB}, ${deviationEndColor(z, maxAbsZ)})` }
                        }
                      />
                    )}
                  </div>
                  <span className="text-xs tabular-nums text-gray-500 dark:text-gray-400 w-10 sm:w-12 text-left shrink-0">
                    {burdenSharePct}%
                  </span>
                  {devStr && (
                    <span className={`text-xs tabular-nums w-10 sm:w-12 text-left shrink-0 ${devCls}`}>
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

  if (failed) return null;

  if (!data) {
    return (
      <div
        dir="rtl"
        className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400"
        data-testid="fairness-components-loading"
      >
        <Loader2 size={16} className="animate-spin" aria-hidden="true" />
        <span>טוען פיזור חלק בנטל...</span>
      </div>
    );
  }

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
