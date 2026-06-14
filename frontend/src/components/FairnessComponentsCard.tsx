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

const PIE_COLORS = ["#6366f1", "#8b5cf6", "#a78bfa", "#c4b5fd", "#ddd6fe", "#e0e7ff"];

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
          return (
            <button
              key={i}
              type="button"
              className={`w-full text-right border rounded-lg p-3 transition-colors ${
                isActive
                  ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950 ring-1 ring-indigo-400"
                  : onGroupToggle
                    ? "border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:border-indigo-600 hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer"
                    : "border-gray-200 dark:border-gray-700"
              }`}
              onClick={() => onGroupToggle?.(ids(c.soldiers), key)}
            >
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="text-sm text-gray-700 dark:text-gray-200">
                  <span className="font-semibold">{c.soldier_count}</span> חיילים
                  {isActive && <span className="mr-2 text-xs text-indigo-600 dark:text-indigo-400 font-normal">✓ נבחר</span>}
                </span>
                {c.effort ? (
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded ${cvBadge(c.effort.cv)}`}>
                    פיזור CV {(c.effort.cv * 100).toFixed(0)}%
                  </span>
                ) : (
                  <span className="text-xs text-gray-400">פחות מ-2 חיילים</span>
                )}
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
                const dist = eligibilityDistribution(c.soldiers);
                if (dist.length <= 1) return null;
                return (
                  <div className="mt-2 flex items-center gap-3">
                    <div style={{ width: 56, height: 56 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={dist}
                            dataKey="soldiers"
                            cx="50%"
                            cy="50%"
                            innerRadius={16}
                            outerRadius={26}
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
            </button>
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
