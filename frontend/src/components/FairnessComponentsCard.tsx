import { useEffect, useState } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { getFairnessComponents, type FairnessComponents, type FairnessSoldier } from "../api/scoring";

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

export type GroupKey = `comp_${number}` | "exempt";

export interface FairnessComponentsCardProps {
  activeGroupKeys?: Set<GroupKey>;
  onGroupToggle?: (soldierIds: string[], key: GroupKey) => void;
  onClearGroups?: () => void;
}

/**
 * פיזור עומס per connected component of soldiers who do the same duties.
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
        <h3 className="font-semibold text-gray-800 dark:text-gray-100">פיזור עומס לפי קבוצות כשירות</h3>
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
          const isActive = activeGroupKeys?.has(key) ?? false;
          const sortedSoldiers = [...c.soldiers].sort((a, b) => a.effort_score - b.effort_score);
          const mean = c.effort?.mean ?? null;
          const effortMin = sortedSoldiers[0]?.effort_score ?? 0;
          const effortMax = sortedSoldiers[sortedSoldiers.length - 1]?.effort_score ?? 1;
          const effortRange = effortMax - effortMin || 1;
          const dist = eligibilityDistribution(c.soldiers);
          const typeCountColor = new Map(dist.map((d, idx) => [d.count, PIE_COLORS[idx % PIE_COLORS.length]]));
          return (
            <div
              key={i}
              className={`w-full text-right border rounded-lg transition-colors overflow-hidden ${
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
                onClick={() => onGroupToggle?.(ids(c.soldiers), key)}
              >
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span className="text-sm text-gray-700 dark:text-gray-200">
                    <span className="font-semibold">{c.soldier_count}</span> חיילים
                    {isActive && <span className="mr-2 text-xs text-indigo-600 dark:text-indigo-300 font-normal">✓ נבחר — לחץ לסינון בטבלה</span>}
                  </span>
                  <div className="flex items-center gap-2">
                    {c.effort ? (
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded ${cvBadge(c.effort.cv)}`}>
                        פיזור CV {(c.effort.cv * 100).toFixed(0)}%
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">פחות מ-2 חיילים</span>
                    )}
                    {c.effort && (
                      <span className="text-xs text-gray-400">
                        טווח: {(effortMin * 100).toFixed(1)}%–{(effortMax * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {c.duty_type_names.map((n) => (
                    <span
                      key={n}
                      className="text-xs bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 px-2 py-0.5 rounded"
                    >
                      {n}
                    </span>
                  ))}
                </div>
                {(() => {
                  if (dist.length === 0) return null;
                  return (
                    <div className="mt-2 flex items-center gap-3">
                      <div style={{ width: 96, height: 96 }}>
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
                              {dist.map((_, i) => (
                                <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                              ))}
                            </Pie>
                            <Tooltip
                              formatter={(value, _name, props) =>
                                [`${value} חיילים`, `${(props.payload as { count?: number })?.count ?? "?"} סוגי תורנות`]
                              }
                            />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
                        {dist.map((d, i) => (
                          <div key={d.count} className="flex items-center gap-1">
                            <span
                              className="inline-block w-2 h-2 rounded-full shrink-0"
                              style={{ background: PIE_COLORS[i % PIE_COLORS.length] }}
                            />
                            <span>{d.soldiers} חיילים — {d.count} סוגים</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })()}
              </div>

              {/* Ranked candidate list — visible when group is selected */}
              {isActive && sortedSoldiers.length > 0 && (
                <div className="border-t border-indigo-200 dark:border-indigo-700 px-3 pb-3 pt-2 overflow-x-auto">
                  <p className="text-xs font-semibold text-indigo-700 dark:text-indigo-300 mb-2">
                    סדר עדיפויות לתורנות הבאה (עומס עולה — מקום 1 מועמד ראשי):
                  </p>
                  <div className="space-y-1 min-w-[260px]">
                    {sortedSoldiers.map((s, rank) => {
                      const effortPct = (s.effort_score * 100).toFixed(2);
                      const dev = mean != null ? s.effort_score - mean : null;
                      const devStr = dev != null
                        ? (dev >= 0 ? `+${(dev * 100).toFixed(1)}%` : `${(dev * 100).toFixed(1)}%`)
                        : null;
                      const devCls = dev != null && dev > 0.005
                        ? "text-red-500 dark:text-red-400"
                        : dev != null && dev < -0.005
                          ? "text-green-600 dark:text-green-400"
                          : "text-gray-400";
                      const barWidth = Math.round(((s.effort_score - effortMin) / effortRange) * 100);
                      const isCandidate = rank < 3;
                      return (
                        <div key={s.soldier_id} className="flex items-center gap-2 pr-1 border-r-2" style={{ borderRightColor: typeCountColor.get(s.eligible_type_count) ?? "transparent" }}>
                          <span className={`text-xs w-5 text-center font-bold shrink-0 ${isCandidate ? "text-indigo-600 dark:text-indigo-300" : "text-gray-400"}`}>
                            {rank + 1}
                          </span>
                          <span className="text-xs text-gray-700 dark:text-gray-300 w-28 truncate shrink-0" title={s.full_name}>
                            {s.full_name}
                          </span>
                          <div className="flex-1 bg-gray-200 dark:bg-gray-700 rounded h-1.5 overflow-hidden">
                            <div
                              className={`h-full rounded ${isCandidate ? "bg-indigo-500" : "bg-gray-400 dark:bg-gray-500"}`}
                              style={{ width: `${Math.max(barWidth, 2)}%` }}
                            />
                          </div>
                          <span className="text-xs tabular-nums text-gray-500 dark:text-gray-400 w-12 text-left shrink-0">
                            {effortPct}%
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
                  {mean != null && (
                    <p className="text-xs text-gray-400 mt-2">
                      ממוצע קבוצה: {(mean * 100).toFixed(2)}% · סטיית תקן: {c.effort ? (c.effort.stddev * 100).toFixed(2) : "—"}%
                    </p>
                  )}
                </div>
              )}
            </div>
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
