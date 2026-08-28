import { useState } from "react";
import type { BurdenShare, BurdenShareBreakdown } from "../../api/scoring";

interface Props {
  share: BurdenShare;
  breakdown: BurdenShareBreakdown | null;
}

export default function BurdenShareCard({ share, breakdown }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (!share.has_group) {
    return (
      <div dir="rtl" className="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
        <h3 className="font-semibold text-gray-800 dark:text-gray-100 mb-1">החלק שלי בנטל התורנויות</h3>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          אין קבוצת השוואה — אתה פטור מכל סוגי התורנות הפעילים כרגע.
        </p>
      </div>
    );
  }

  const pct = (share.burden_share ?? 0) * 100;
  const peers = [...share.peer_scores].sort((a, b) => a - b);
  const min = peers[0] ?? 0;
  const max = peers[peers.length - 1] ?? 1;
  const range = max - min || 1;
  const myScore = share.burden_share ?? 0;

  return (
    <div dir="rtl" className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
      <div>
        <h3 className="font-semibold text-gray-800 dark:text-gray-100">החלק שלי בנטל התורנויות</h3>
        <div className="mt-1 text-3xl font-bold text-indigo-700 dark:text-indigo-300">
          {pct.toFixed(1)}%
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          מקום {share.rank} מתוך {share.group_size} · מושווה מול חיילים כשירים לאותן תורנויות
          {share.duty_type_names.length > 0 && (
            <> ({share.duty_type_names.join(", ")})</>
          )}
        </p>
        {share.low_sample && (
          <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
            בקבוצת הכשירות שלך פחות מ-3 חיילים — ההשוואה פחות משמעותית סטטיסטית
          </p>
        )}
      </div>

      {/* Anonymized distribution strip */}
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
        {share.mean != null && (
          <p className="text-xs text-gray-400 mt-1">
            טווח הקבוצה: {(min * 100).toFixed(0)}%–{(max * 100).toFixed(0)}% · ממוצע: {(share.mean * 100).toFixed(0)}%
            {share.cv != null && <> · פיזור (CV): {(share.cv * 100).toFixed(0)}%</>}
          </p>
        )}
      </div>

      <button
        type="button"
        className="text-xs text-indigo-600 dark:text-indigo-300 hover:underline"
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded ? "הסתר פירוט חישוב" : "הצג פירוט חישוב"}
      </button>

      {expanded && breakdown && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 dark:text-gray-400 border-b dark:border-gray-600">
                <th className="text-right pb-1 font-medium">רבעון</th>
                <th className="text-right pb-1 font-medium">הניקוד שלי</th>
                <th className="text-right pb-1 font-medium">ניקוד יחידה</th>
                <th className="text-right pb-1 font-medium">חלק</th>
              </tr>
            </thead>
            <tbody>
              {breakdown.quarters.map((q) => (
                <tr key={q.quarter_start} className="border-b dark:border-gray-600 last:border-0">
                  <td className="py-1">
                    {q.quarter_label}
                    {q.is_partial && (
                      <span className="mr-1 text-[10px] px-1 py-0.5 rounded bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300">
                        רבעון חלקי
                      </span>
                    )}
                  </td>
                  <td className="py-1">{Number(q.soldier_score).toFixed(2)}</td>
                  <td className="py-1">{Number(q.unit_score).toFixed(2)}</td>
                  <td className="py-1">{(Number(q.share) * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
