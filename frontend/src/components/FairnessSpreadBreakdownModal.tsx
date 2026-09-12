import { useState } from "react";
import { InlineMath } from "react-katex";
import { useModalBackClose } from "../hooks/useModalBackClose";
import SoldierLink from "./SoldierLink";

export interface FairnessSpreadBreakdownSoldier {
  id: string;
  name: string;
  burdenShare: number;
}

interface Props {
  title: string;
  soldiers: FairnessSpreadBreakdownSoldier[];
  onClose: () => void;
}

const COLUMN_INFO: Record<string, string> = {
  soldier: "שם החייל. לחיצה על השם פותחת את הפרופיל שלו.",
  share: "אחוז התורנויות שהחייל נושא, מתוך כלל הנטל של הקבוצה.",
  deviation: "ההפרש בין חלק החייל בנטל לממוצע הקבוצה (μ). חיובי = נושא יותר מהממוצע.",
  squared: "הסטייה בריבוע — כך שהפרשים בכיוונים הפוכים (מעל/מתחת לממוצע) לא מתבטלים זה את זה כשמסכמים אותם. זה הבסיס לחישוב סטיית התקן (σ) בשלב 2 למטה.",
};

interface ColumnTooltip {
  id: string;
  rect: DOMRect;
}

function ColumnHeader({
  id, label, openColId, onToggle, className,
}: {
  id: string;
  label: string;
  openColId: string | null;
  onToggle: (id: string, rect: DOMRect) => void;
  className?: string;
}) {
  return (
    <th className={`text-right py-1 pb-2 font-medium ${className ?? ""}`}>
      <button
        type="button"
        className={`underline decoration-dotted cursor-help ${openColId === id ? "text-gray-900 dark:text-white" : ""}`}
        onClick={(e) => {
          e.stopPropagation();
          onToggle(id, e.currentTarget.getBoundingClientRect());
        }}
      >
        {label}
      </button>
    </th>
  );
}

function interpretation(cv: number): { label: string; cls: string } {
  if (cv < 0.25) return { label: "פיזור בריא — העומס מחולק בצורה שוויונית", cls: "text-green-700 dark:text-green-300" };
  if (cv <= 0.5) return { label: "אי-שוויון בינוני — כדאי לבדוק", cls: "text-yellow-700 dark:text-yellow-300" };
  return { label: "פיזור גבוה — חלק מהחיילים נושאים עומס שונה מאוד מהממוצע", cls: "text-red-700 dark:text-red-300" };
}

// Spelling out every term in a group of a few hundred soldiers renders as an
// unreadable, page-breaking wall of numbers (verified live) — but the
// threshold for that must stay well above the table's own visible row count,
// or the formula silently omits terms a reader can still see (and is trying
// to trace) in the table right above it. 8 comfortably covers the table's
// own fixed height (~9 rows before it needs to scroll) while still catching
// the genuinely huge (hundreds-of-soldiers) case this exists for.
function ellipsizedSum(terms: string[]): string {
  if (terms.length <= 8) return terms.join(" + ");
  return `${terms[0]} + ${terms[1]} + \\cdots + ${terms[terms.length - 1]}`;
}

/** Client-side breakdown of the same mean/stddev/CV computation shown
 * throughout this card (group-level and per-subgroup), using the burden_share
 * values already loaded — no extra fetch, unlike the per-soldier quarterly
 * breakdown (BurdenShareBreakdownModal), which needs its own API call. */
export default function FairnessSpreadBreakdownModal({ title, soldiers, onClose }: Props) {
  useModalBackClose(onClose);
  // position:fixed and measured from the clicked header's own screen rect,
  // rendered outside the table's scrollable container — nesting it inside
  // (as an absolutely-positioned child) meant the table's own overflow-auto
  // (needed to cap a hundreds-of-soldiers table at a fixed height) clipped
  // the tooltip for any column near the table's edge (confirmed live on
  // mobile: the last, left-most-in-RTL column's tooltip was invisible).
  const [colTooltip, setColTooltip] = useState<ColumnTooltip | null>(null);

  function toggleColInfo(id: string, rect: DOMRect) {
    setColTooltip((prev) => (prev?.id === id ? null : { id, rect }));
  }

  const sorted = [...soldiers].sort((a, b) => a.burdenShare - b.burdenShare);
  const n = sorted.length;
  const mean = n > 0 ? sorted.reduce((sum, s) => sum + s.burdenShare, 0) / n : 0;
  const variance = n > 0 ? sorted.reduce((sum, s) => sum + (s.burdenShare - mean) ** 2, 0) / n : 0;
  const stddev = Math.sqrt(variance);
  const cv = mean !== 0 ? stddev / mean : 0;
  const min = n > 0 ? sorted[0].burdenShare : 0;
  const max = n > 0 ? sorted[n - 1].burdenShare : 0;
  const pct = (v: number) => (v * 100).toFixed(2);

  const meanTerms = sorted.map((s) => `${pct(s.burdenShare)}\\%`);
  const varianceTerms = sorted.map((s) => ((s.burdenShare - mean) ** 2 * 10000).toFixed(3));

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-xl max-h-[80vh] flex flex-col overflow-hidden"
        onClick={(e) => { setColTooltip(null); e.stopPropagation(); }}
        dir="rtl"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b dark:border-gray-700">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">📊 פירוט חישוב פיזור — {title}</h2>
          <button
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xl leading-none"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        <div className="overflow-y-auto flex-1">
          {n < 2 ? (
            <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-6">
              פחות מ-2 חיילים בקבוצה זו — אין מספיק נתונים לחישוב פיזור.
            </p>
          ) : (
            <>
              {/* Per-soldier table — fixed height, scrolls on its own so a
                  group of hundreds doesn't force the whole modal to scroll
                  past it before reaching the derivation below. The soldier
                  name column is narrow and wraps (instead of a wider,
                  truncated column) so the squared-deviation column stays
                  visible on a narrow (mobile) screen without needing to
                  scroll the table horizontally. */}
              <div className="overflow-auto px-4 py-3 max-h-72">
                <table className="w-full text-sm border-collapse sm:min-w-[420px]">
                  <thead>
                    <tr className="text-xs text-gray-500 dark:text-gray-400 border-b dark:border-gray-700 sticky top-0 bg-white dark:bg-gray-800">
                      <ColumnHeader id="soldier" label="חייל" openColId={colTooltip?.id ?? null} onToggle={toggleColInfo} className="w-16 sm:w-auto" />
                      <ColumnHeader id="share" label="חלק בנטל" openColId={colTooltip?.id ?? null} onToggle={toggleColInfo} className="px-3" />
                      <ColumnHeader id="deviation" label="סטייה מהממוצע" openColId={colTooltip?.id ?? null} onToggle={toggleColInfo} className="px-3" />
                      <ColumnHeader id="squared" label="סטייה בריבוע" openColId={colTooltip?.id ?? null} onToggle={toggleColInfo} />
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((s) => {
                      const dev = s.burdenShare - mean;
                      const devPct = dev >= 0 ? `+${pct(dev)}` : pct(dev);
                      const devCls = dev > 0.005 ? "text-red-500 dark:text-red-400" : dev < -0.005 ? "text-green-600 dark:text-green-400" : "text-gray-400";
                      return (
                        <tr key={s.id} className="border-b dark:border-gray-700">
                          <td className="py-1.5 w-16 sm:w-auto sm:max-w-[9rem]">
                            <SoldierLink id={s.id} name={s.name} className="break-words text-gray-700 dark:text-gray-300" />
                          </td>
                          <td className="py-1.5 text-right px-3 text-gray-700 dark:text-gray-300 tabular-nums">{pct(s.burdenShare)}%</td>
                          <td className={`py-1.5 text-right px-3 tabular-nums ${devCls}`}>{devPct}%</td>
                          <td className="py-1.5 text-right text-gray-500 dark:text-gray-400 tabular-nums">{(dev * dev * 10000).toFixed(3)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Derivation */}
              <div className="border-t dark:border-gray-700 bg-gray-50 dark:bg-gray-900 px-4 py-4 space-y-4 text-xs" dir="rtl">
                <p className="font-semibold text-gray-700 dark:text-gray-300">כיצד מגיעים לערך הפיזור?</p>

                <div>
                  <p className="font-medium text-indigo-700 dark:text-indigo-300 mb-1">שלב 1 — ממוצע (μ)</p>
                  <div className="bg-white dark:bg-gray-800 border border-indigo-100 dark:border-indigo-900 rounded-lg px-3 py-2 overflow-x-auto">
                    <InlineMath math={String.raw`\mu = \dfrac{${ellipsizedSum(meanTerms)}}{${n}} = ${pct(mean)}\%`} />
                  </div>
                </div>

                <div>
                  <p className="font-medium text-amber-700 dark:text-amber-300 mb-1">שלב 2 — סטיית תקן (σ)</p>
                  <div className="bg-white dark:bg-gray-800 border border-amber-100 dark:border-amber-900 rounded-lg px-3 py-2 overflow-x-auto">
                    <InlineMath math={String.raw`\sigma = \sqrt{\dfrac{${ellipsizedSum(varianceTerms)}}{${n}}} = ${pct(stddev)}\%`} />
                  </div>
                  <p className="text-gray-500 dark:text-gray-400 mt-1">
                    σ נמדד באותן יחידות כמו הנתון המקורי (אחוזי חלק בנטל) — זה בערך ״כמה, בממוצע, כל חייל רחוק מהממוצע״.
                  </p>
                </div>

                <div>
                  <p className="font-medium text-gray-700 dark:text-gray-300 mb-1">שלב 3 — מקדם הפיזור (CV): מה הקשר בין σ, μ ו-CV?</p>
                  <p className="text-gray-600 dark:text-gray-400 mb-2">
                    σ לבד לא מספיק כדי לדעת אם הפיזור ״גדול״ או ״קטן״ — סטיית תקן של 5% אחוז נקודות היא ענקית כשהממוצע הוא 10% (הכל כפול!),
                    אבל זניחה כשהממוצע הוא 80%. CV פותר את זה: הוא מחלק את σ ב-μ, כך שמקבלים ״אחוז מהממוצע״ במקום ״נקודות אחוז״ —
                    ערך שאפשר להשוות בין קבוצות עם ממוצעים שונים (ואפילו בין תקופות זמן שונות, אם הממוצע הכללי משתנה).
                  </p>
                  <div className="bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 rounded-lg px-3 py-2">
                    <p className="font-bold text-base text-indigo-700 dark:text-indigo-300 tabular-nums">
                      <InlineMath math={String.raw`CV = \dfrac{\sigma}{\mu} = \dfrac{${pct(stddev)}\%}{${pct(mean)}\%} = ${(cv * 100).toFixed(0)}\%`} />
                    </p>
                  </div>
                </div>

                <div>
                  <p className="font-medium text-gray-700 dark:text-gray-300 mb-1">מה זה אומר על הנתונים הנוכחיים</p>
                  <p className={`font-medium ${interpretation(cv).cls}`}>{interpretation(cv).label}</p>
                  <p className="text-gray-500 dark:text-gray-400 mt-1">
                    טווח בפועל: {pct(min)}%–{pct(max)}% מתוך {n} חיילים.
                  </p>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t dark:border-gray-700 bg-white dark:bg-gray-800 flex items-center justify-between text-sm">
          <span className="text-gray-500 dark:text-gray-400">פיזור CV:</span>
          <span className="text-xl font-bold text-indigo-700 dark:text-indigo-300">
            {n < 2 ? "—" : `${(cv * 100).toFixed(0)}%`}
          </span>
        </div>
      </div>
      {colTooltip && (
        <div
          className="fixed z-[60] w-48 whitespace-normal text-right bg-gray-900 text-white text-xs rounded px-2 py-1.5 shadow-lg"
          style={{
            top: colTooltip.rect.bottom + 4,
            left: Math.min(Math.max(colTooltip.rect.left, 8), window.innerWidth - 192 - 8),
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {COLUMN_INFO[colTooltip.id]}
        </div>
      )}
    </div>
  );
}
