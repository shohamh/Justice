import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { BlockMath } from "react-katex";
import { EffectiveDuty } from "../../api/assignments";
import { TransparencyRow, BurdenShare, BurdenShareBreakdown } from "../../api/scoring";
import { formatDutyRange } from "../../utils/formatDate";
import BurdenShareBreakdownModal from "../BurdenShareBreakdownModal";
import BurdenShareTrendChart from "./BurdenShareTrendChart";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
  locationNames: Record<string, string>;
  myRow: TransparencyRow | null;
  allRows: TransparencyRow[];
  canViewTransparency: boolean;
  burdenShare?: BurdenShare | null;
  burdenShareBreakdown?: BurdenShareBreakdown | null;
  soldierName?: string;
}

function avg(rows: TransparencyRow[], key: keyof TransparencyRow): number {
  if (rows.length === 0) return 0;
  return rows.reduce((s, r) => s + Number(r[key]), 0) / rows.length;
}

export default function DutyHistoryWidget({
  duties, typeNames, locationNames, myRow, allRows, canViewTransparency,
  burdenShare, burdenShareBreakdown, soldierName,
}: Props) {
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const [breakdownModalOpen, setBreakdownModalOpen] = useState(false);
  const today = new Date().toISOString().split("T")[0];
  const past = duties
    // end_date is exclusive, so "over" means end_date is today or earlier.
    .filter((d) => d.end_date <= today)
    .sort((a, b) => b.start_date.localeCompare(a.start_date));

  const avgActiveDays = Math.round(avg(allRows, "active_days"));
  const avgScore = avg(allRows, "cumulative_score").toFixed(3);
  const avgBurdenSharePct = (avg(allRows, "burden_share") * 100).toFixed(1);

  const burdenSharePct = burdenShare?.has_group
    ? (Number(burdenShare.burden_share ?? 0) * 100)
    : Number(myRow?.burden_share ?? 0) * 100;

  const peers = burdenShare?.has_group ? [...burdenShare.peer_scores].sort((a, b) => a - b) : [];
  const min = peers[0] ?? 0;
  const max = peers[peers.length - 1] ?? 1;
  const range = max - min || 1;
  const myScore = burdenShare?.burden_share ?? 0;

  const normTooltip = useMemo(() => (
    <div className="space-y-3" dir="rtl">
      <p>חלק בנטל מחושב לפי הניקוד ליום שלך ביחס לממוצע היחידה.</p>
      <BlockMath math="\text{חלק בנטל} = \dfrac{\text{ניקוד ליום שלך}}{\text{ממוצע ניקוד ליום ביחידה}}" />
      <p className="text-xs text-gray-500 dark:text-gray-400">ניקוד 1.0 = בדיוק כמו הממוצע. מעל 1.0 = עשית יותר מהממוצע. מתחת 1.0 = עשית פחות.</p>
    </div>
  ), []);

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-4" dir="rtl">
      <div className="flex justify-between items-center">
        <h2 className="text-lg font-semibold">היסטוריית תורנויות</h2>
        {canViewTransparency && (
          <Link to="/transparency" className="text-sm text-indigo-600 dark:text-indigo-300 hover:text-indigo-800 dark:hover:text-indigo-200">
            לדף השקיפות →
          </Link>
        )}
      </div>

      {/* Scoring metrics */}
      <div className="grid grid-cols-3 gap-3 text-sm">
        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 text-center">
          <div className="text-xs text-gray-500 mb-1">ניקוד מצטבר</div>
          <div className="text-lg font-semibold text-indigo-700 dark:text-indigo-300">{Number(myRow?.cumulative_score ?? 0).toFixed(3)}</div>
          <div className="text-xs text-gray-400 mt-1">ממוצע יחידה: {avgScore}</div>
        </div>
        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 text-center">
          <div className="text-xs text-gray-500 mb-1">ימים פעילים</div>
          <div className="text-lg font-semibold text-indigo-700 dark:text-indigo-300">{myRow?.active_days ?? 0}</div>
          <div className="text-xs text-gray-400 mt-1">ממוצע יחידה: {avgActiveDays}</div>
        </div>
        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 text-center">
          <div className="text-xs text-gray-500 mb-1 inline-flex items-center gap-1">
            חלק בנטל
            <button
              type="button"
              onClick={() => setTooltipOpen(true)}
              className="text-gray-400 hover:text-gray-600 text-xs border border-gray-300 rounded-full w-3.5 h-3.5 inline-flex items-center justify-center"
              aria-label="הסבר חלק בנטל"
            >
              ?
            </button>
          </div>
          <div className="text-lg font-semibold text-indigo-700 dark:text-indigo-300">{burdenSharePct.toFixed(1)}%</div>
          <div className="text-xs text-gray-400 mt-1">
            {burdenShare?.has_group
              ? `מקום ${burdenShare.rank} מתוך ${burdenShare.group_size}`
              : `ממוצע יחידה: ${avgBurdenSharePct}%`}
          </div>
        </div>
      </div>

      {/* חלק בנטל — comparison group context, distribution, trend, breakdown */}
      {burdenShare && (
        burdenShare.has_group ? (
          <div className="space-y-3">
            <p className="text-xs text-gray-500 dark:text-gray-400">
              מושווה מול חיילים כשירים לאותן תורנויות
              {burdenShare.duty_type_names.length > 0 && (
                <> ({burdenShare.duty_type_names.join(", ")})</>
              )}
            </p>
            {burdenShare.low_sample && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                בקבוצת הכשירות שלך פחות מ-3 חיילים — ההשוואה פחות משמעותית סטטיסטית
              </p>
            )}

            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">איפה אני ביחס לקבוצה שלי</p>
              <div className="relative h-6 bg-gray-100 dark:bg-gray-700 rounded">
                {peers.map((v, i) => {
                  const left = ((v - min) / range) * 100;
                  const isMine = v === myScore;
                  return (
                    <div
                      key={i}
                      data-testid={isMine ? "burden-dot-me" : "burden-dot-peer"}
                      className={`absolute top-1/2 -translate-y-1/2 rounded-full ${
                        isMine ? "w-3 h-3 bg-indigo-600 ring-2 ring-white dark:ring-gray-800 z-10" : "w-1.5 h-1.5 bg-gray-400 dark:bg-gray-500"
                      }`}
                      style={{ left: `calc(${left}% - 2px)` }}
                    />
                  );
                })}
              </div>
              {burdenShare.mean != null && (
                <p className="text-xs text-gray-400 mt-1">
                  טווח הקבוצה: {(min * 100).toFixed(0)}%–{(max * 100).toFixed(0)}% · ממוצע: {(burdenShare.mean * 100).toFixed(0)}%
                  {burdenShare.cv != null && <> · פיזור (CV): {(burdenShare.cv * 100).toFixed(0)}%</>}
                </p>
              )}
            </div>

            {burdenShareBreakdown && burdenShareBreakdown.quarters.length > 0 && (
              <BurdenShareTrendChart quarters={burdenShareBreakdown.quarters} />
            )}

            {burdenShareBreakdown && (
              <button
                type="button"
                className="text-xs text-indigo-600 dark:text-indigo-300 hover:underline"
                onClick={() => setBreakdownModalOpen(true)}
              >
                הצג פירוט חישוב
              </button>
            )}
          </div>
        ) : (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            אין קבוצת השוואה — אתה פטור מכל סוגי התורנות הפעילים כרגע.
          </p>
        )
      )}

      {/* Past duties list */}
      {past.length === 0 ? (
        <p className="text-sm text-gray-500">אין היסטוריית תורנויות</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 dark:text-gray-400 border-b dark:border-gray-600">
              <th className="text-right pb-2 font-medium">תאריך</th>
              <th className="text-right pb-2 font-medium">סוג</th>
              <th className="text-right pb-2 font-medium">מיקום</th>
            </tr>
          </thead>
          <tbody>
            {past.map((d) => (
              <tr key={d.assignment_id} className="border-b dark:border-gray-600 last:border-0">
                <td className="py-2">{formatDutyRange(d.start_date, d.end_date)}</td>
                <td className="py-2">{typeNames[d.duty_type_id] ?? "—"}</td>
                <td className="py-2">{locationNames[d.duty_location_id] ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Tooltip modal */}
      {tooltipOpen && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setTooltipOpen(false)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md mx-4" dir="rtl" onClick={(e) => e.stopPropagation()}>
            <div className="text-sm">{normTooltip}</div>
            <div className="mt-4 text-left">
              <button type="button" className="bg-indigo-600 text-white px-3 py-1 rounded text-sm" onClick={() => setTooltipOpen(false)}>סגור</button>
            </div>
          </div>
        </div>
      )}

      {/* Burden-share breakdown modal */}
      {breakdownModalOpen && burdenShareBreakdown && (
        <BurdenShareBreakdownModal
          soldierName={soldierName ?? ""}
          breakdown={burdenShareBreakdown}
          onClose={() => setBreakdownModalOpen(false)}
        />
      )}
    </section>
  );
}
