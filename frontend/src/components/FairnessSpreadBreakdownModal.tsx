import { useState } from "react";
import { InlineMath, BlockMath } from "react-katex";
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
  /** Singular/plural noun for the row unit — a soldier everywhere except the
   * transparency page's per-sub-unit tab, where each row is a framework
   * (מסגרת) averaged over its own soldiers. */
  unitLabel?: string;
  unitLabelPlural?: string;
  /** Soldier rows link to that soldier's profile; framework rows have no
   * such destination, so they render as plain text instead. */
  linkToUnit?: boolean;
}

function columnInfo(unitLabel: string, linkToUnit: boolean): Record<string, string> {
  return {
    soldier: linkToUnit
      ? `שם ה${unitLabel}. לחיצה על השם פותחת את הפרופיל שלו.`
      : `שם ה${unitLabel}.`,
    share: `אחוז התורנויות שה${unitLabel} נושא, מתוך כלל הנטל של הקבוצה.`,
    deviation: `ההפרש בין חלק ה${unitLabel} בנטל לממוצע הקבוצה (μ). חיובי = נושא יותר מהממוצע.`,
    squared: "הסטייה בריבוע — כך שהפרשים בכיוונים הפוכים (מעל/מתחת לממוצע) לא מתבטלים זה את זה כשסוכמים אותם. זה הבסיס לחישוב סטיית התקן (σ) בשלב 2 למטה.",
  };
}

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

const THRESHOLDS = [
  { min: 0, max: 0.25, dot: "bg-green-500", range: "פחות מ-25%", label: "פיזור בריא — העומס מחולק בצורה שוויונית" },
  { min: 0.25, max: 0.5, dot: "bg-yellow-500", range: "25%–50%", label: "אי-שוויון בינוני — כדאי לבדוק" },
  { min: 0.5, max: Infinity, dot: "bg-red-500", range: "מעל 50%", label: "פיזור גבוה — חלק מהיחידות נושאות עומס שונה מאוד מהממוצע" },
];

function interpretation(cv: number) {
  return THRESHOLDS.find((t) => cv >= t.min && cv < t.max) ?? THRESHOLDS[THRESHOLDS.length - 1];
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

/** Explains what the burden-share spread (CV) metric means in general, then
 * walks through the exact same computation (mean/stddev/CV) for the group
 * actually on screen, using the burden_share values already loaded — no
 * extra fetch, unlike the per-soldier quarterly breakdown
 * (BurdenShareBreakdownModal), which needs its own API call. Previously this
 * general explanation and the group-specific numbers lived in two separate
 * modals (a "?" help icon vs. a "הצג פירוט חישוב" link); they were merged so
 * each concept is explained once and immediately illustrated with the real
 * data, instead of asking the reader to mentally connect two dialogs. */
export default function FairnessSpreadBreakdownModal({
  title, soldiers, onClose, unitLabel = "חייל", unitLabelPlural = "החיילים", linkToUnit = true,
}: Props) {
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
  const activeRange = n >= 2 ? interpretation(cv) : null;
  const colInfo = columnInfo(unitLabel, linkToUnit);

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-xl max-h-[85vh] flex flex-col overflow-hidden"
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
          <p className="text-sm text-gray-600 dark:text-gray-400 px-4 pt-3">
            מדד הפיזור (CV) מציג כמה שוויונית חלוקת התורנויות בין {unitLabelPlural}. ערך נמוך פירושו שכולם נושאים עומס דומה.
          </p>

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
                      <ColumnHeader id="soldier" label={unitLabel} openColId={colTooltip?.id ?? null} onToggle={toggleColInfo} className="w-16 sm:w-auto" />
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
                            {linkToUnit
                              ? <SoldierLink id={s.id} name={s.name} className="break-words text-gray-700 dark:text-gray-300" />
                              : <span className="break-words text-gray-700 dark:text-gray-300">{s.name}</span>}
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
                  <p className="font-medium text-emerald-700 dark:text-emerald-300 mb-1">שלב 1 — ממוצע (μ)</p>
                  <p className="text-gray-600 dark:text-gray-400 mb-2">
                    הערך הממוצע של חלק הנטל בין כל {unitLabelPlural} בקבוצה. זו נקודת הייחוס שממנה נמדד הפיזור בשלבים הבאים.
                  </p>
                  <div className="bg-white dark:bg-gray-800 border border-emerald-100 dark:border-emerald-900 rounded-lg px-3 py-2 overflow-x-auto whitespace-nowrap">
                    <InlineMath math={String.raw`\mu = \dfrac{${ellipsizedSum(meanTerms)}}{${n}} = ${pct(mean)}\%`} />
                  </div>
                </div>

                <div>
                  <p className="font-medium text-amber-700 dark:text-amber-300 mb-1">שלב 2 — סטיית תקן (σ)</p>
                  <p className="text-gray-600 dark:text-gray-400 mb-2">
                    לכל {unitLabel} מחשבים כמה הוא שונה מהממוצע, מעלים בריבוע (כדי שהפרשים בכיוונים הפוכים לא יתבטלו), מחשבים ממוצע של הריבועים, ולוקחים שורש ריבועי.
                  </p>
                  <div className="bg-gray-100 dark:bg-gray-950 rounded-lg px-3 py-2 mb-2 overflow-x-auto text-center">
                    <BlockMath math={String.raw`\sigma = \sqrt{\frac{\displaystyle\sum_{i=1}^{n}(x_i - \mu)^2}{n}}`} />
                  </div>
                  <div className="text-gray-500 dark:text-gray-400 space-y-0.5 pr-1 mb-2">
                    <p><InlineMath math="x_i" /> — חלק בנטל של {unitLabel} i · <InlineMath math="n" /> — מספר {unitLabelPlural}</p>
                  </div>
                  <p className="text-gray-500 dark:text-gray-400 mb-1">עבור הקבוצה הנוכחית:</p>
                  <div className="bg-white dark:bg-gray-800 border border-amber-100 dark:border-amber-900 rounded-lg px-3 py-2 overflow-x-auto whitespace-nowrap">
                    <InlineMath math={String.raw`\sigma = \sqrt{\dfrac{${ellipsizedSum(varianceTerms)}}{${n}}} = ${pct(stddev)}\%`} />
                  </div>
                  <p className="text-gray-500 dark:text-gray-400 mt-1">
                    σ נמדד באותן יחידות כמו הנתון המקורי (אחוזי חלק בנטל) — זה בערך ״כמה, בממוצע, כל {unitLabel} רחוק מהממוצע״.
                  </p>
                </div>

                <div>
                  <p className="font-medium text-indigo-700 dark:text-indigo-300 mb-1">שלב 3 — מקדם הפיזור (CV): מה הקשר בין σ, μ ו-CV?</p>
                  <p className="text-gray-600 dark:text-gray-400 mb-2">
                    σ לבד לא מספיק כדי לדעת אם הפיזור ״גדול״ או ״קטן״ — סטיית תקן של 5% אחוז נקודות היא ענקית כשהממוצע הוא 10% (הכל כפול!),
                    אבל זניחה כשהממוצע הוא 80%. CV פותר את זה: הוא מחלק את σ ב-μ, כך שמקבלים ״אחוז מהממוצע״ במקום ״נקודות אחוז״ —
                    ערך שאפשר להשוות בין קבוצות עם ממוצעים שונים (ואפילו בין תקופות זמן שונות, אם הממוצע הכללי משתנה).
                  </p>
                  <div className="bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 rounded-lg px-3 py-2 overflow-x-auto whitespace-nowrap">
                    <p className="font-bold text-base text-indigo-700 dark:text-indigo-300 tabular-nums">
                      <InlineMath math={String.raw`\text{CV} = \dfrac{\sigma}{\mu} = \dfrac{${pct(stddev)}\%}{${pct(mean)}\%} = ${(cv * 100).toFixed(0)}\%`} />
                    </p>
                  </div>
                </div>

                <div>
                  <p className="font-medium text-gray-700 dark:text-gray-300 mb-2">דוגמה ממחישה</p>
                  <p className="text-gray-600 dark:text-gray-400 mb-2">
                    שתי קבוצות של 4 {unitLabelPlural} עם אותו ממוצע עומס (25%), אבל פיזור שונה:
                  </p>
                  <div className="space-y-1.5">
                    <div className="flex items-start gap-2">
                      <span className="mt-1 inline-block w-2 h-2 rounded-full shrink-0 bg-green-500" />
                      <span className="text-gray-700 dark:text-gray-300">
                        <strong>24%, 25%, 26%, 25%</strong> — כולם קרובים לממוצע ← <strong>CV ≈ 3%</strong>, פיזור בריא.
                      </span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="mt-1 inline-block w-2 h-2 rounded-full shrink-0 bg-red-500" />
                      <span className="text-gray-700 dark:text-gray-300">
                        <strong>10%, 15%, 35%, 40%</strong> — אותו ממוצע, אבל שניים נושאים כמעט כפול מהשניים האחרים ← <strong>CV ≈ 51%</strong>, פיזור לא שוויוני.
                      </span>
                    </div>
                  </div>
                </div>

                <div>
                  <p className="font-medium text-gray-700 dark:text-gray-300 mb-2">מה זה אומר על הנתונים הנוכחיים</p>
                  <div className="space-y-1.5 mb-2">
                    {THRESHOLDS.map((t) => (
                      <div
                        key={t.range}
                        className={`flex items-start gap-2 rounded px-1.5 py-1 -mx-1.5 ${t === activeRange ? "bg-indigo-100 dark:bg-indigo-900" : ""}`}
                      >
                        <span className={`mt-1 inline-block w-2 h-2 rounded-full shrink-0 ${t.dot}`} />
                        <span className="text-gray-700 dark:text-gray-300">
                          <strong>{t.range}</strong> — {t.label}
                          {t === activeRange && <> · <strong>זה המצב הנוכחי</strong> ({(cv * 100).toFixed(0)}%)</>}
                        </span>
                      </div>
                    ))}
                  </div>
                  <p className="text-gray-500 dark:text-gray-400">
                    טווח בפועל: {pct(min)}%–{pct(max)}% מתוך {n} {n === 1 ? unitLabel : unitLabelPlural}.
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
          {colInfo[colTooltip.id]}
        </div>
      )}
    </div>
  );
}
