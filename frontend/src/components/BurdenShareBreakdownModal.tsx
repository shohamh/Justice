import { useState } from "react";
import { InlineMath } from "react-katex";
import type { BurdenShareBreakdown } from "../api/scoring";
import { formatDate } from "../utils/formatDate";
import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  soldierName: string;
  breakdown: BurdenShareBreakdown;
  onClose: () => void;
}

export default function BurdenShareBreakdownModal({ soldierName, breakdown, onClose }: Props) {
  useModalBackClose(onClose);
  const [openQuarterInfo, setOpenQuarterInfo] = useState<string | null>(null);

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-xl max-h-[80vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
        dir="rtl"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b dark:border-gray-700">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">
            📊 פירוט חישוב חלק בנטל — {soldierName}
          </h2>
          <button
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xl leading-none"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        {/* Table + Derivation (scrollable together so header & footer always visible) */}
        <div className="overflow-y-auto flex-1">
          {/* Table */}
          <div className="py-3">
            {breakdown.quarters.length === 0 ? (
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
                    {breakdown.quarters.map((q) => {
                      const sharePct = (parseFloat(q.share) * 100).toFixed(2);
                      const activePct = (parseFloat(q.active_frac) * 100).toFixed(0);
                      const unitScore = parseFloat(q.unit_score);
                      const weightedSharePct = (parseFloat(q.weighted_share) * 100).toFixed(2);
                      const adjDelta = parseFloat(q.adjustment_delta ?? "0");
                      return (
                        <tr key={q.quarter_label} className={`border-b dark:border-gray-700 ${q.is_partial ? "bg-indigo-50/40 dark:bg-indigo-950/20" : ""}`}>
                          <td className="py-2 text-gray-700 dark:text-gray-300 font-medium relative">
                            <span className={q.is_partial ? "italic" : ""}>{q.quarter_label}</span>
                            <button
                              type="button"
                              className="mr-1 text-gray-400 dark:text-gray-500 text-xs cursor-help"
                              title={`${formatDate(q.quarter_start)} – ${formatDate(q.quarter_end)}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                setOpenQuarterInfo((prev) => (prev === q.quarter_label ? null : q.quarter_label));
                              }}
                            >
                              ⓘ
                            </button>
                            {openQuarterInfo === q.quarter_label && (
                              <div
                                className="absolute z-10 top-full right-0 mt-1 whitespace-nowrap bg-gray-900 text-white text-xs rounded px-2 py-1 shadow-lg"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {formatDate(q.quarter_start)} – {formatDate(q.quarter_end)}
                              </div>
                            )}
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
                  const partialQ = breakdown.quarters.find((q) => q.is_partial);
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
          {breakdown.quarters.length > 0 && (() => {
            const A = parseFloat(breakdown.A_i);
            const W = parseFloat(breakdown.W_i);
            const effort = parseFloat(breakdown.burden_share);
            const qs = breakdown.quarters;

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
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-0.5"><InlineMath math="\text{חלק בנטל} = \dfrac{A}{W}" /></p>
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
          <span className="text-gray-500 dark:text-gray-400">חלק בנטל מצטבר:</span>
          <span className="text-xl font-bold text-indigo-700 dark:text-indigo-300">
            {(parseFloat(breakdown.burden_share) * 100).toFixed(2)}%
          </span>
        </div>
      </div>
    </div>
  );
}
