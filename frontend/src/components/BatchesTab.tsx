import React, { useState } from "react";
import { BatchResult } from "../api/algorithm";

interface Props {
  batchResults: BatchResult[];
  shiftNames: Record<string, string>;
}

const OUTCOME_BADGE: Record<string, string> = {
  OPTIMAL: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
  FEASIBLE: "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
  INFEASIBLE: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300",
  CANCELLED: "bg-gray-100 dark:bg-gray-700 text-gray-500",
};

const OUTCOME_LABEL: Record<string, string> = {
  OPTIMAL: "אופטימלי",
  FEASIBLE: "אפשרי",
  INFEASIBLE: "לא ניתן",
  CANCELLED: "בוטל",
};

export default function BatchesTab({ batchResults, shiftNames }: Props) {
  const [expandedBatch, setExpandedBatch] = useState<number | null>(null);

  if (batchResults.length === 0) {
    return (
      <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-8" dir="rtl">
        אין נתוני קבוצות לריצה זו
      </p>
    );
  }

  const byComponent = batchResults.reduce<Record<number, BatchResult[]>>((acc, br) => {
    (acc[br.component_index] ??= []).push(br);
    return acc;
  }, {});

  const componentIndices = Object.keys(byComponent).map(Number).sort((a, b) => a - b);

  return (
    <div className="space-y-4 text-sm" dir="rtl">
      {componentIndices.map(compIdx => {
        const batches = byComponent[compIdx];
        const soldierCount = batches[0]?.soldier_count ?? 0;
        return (
          <div key={compIdx} className="border dark:border-gray-600 rounded-lg overflow-hidden">
            <div className="bg-gray-50 dark:bg-gray-700 px-4 py-2 font-medium text-xs text-gray-700 dark:text-gray-300">
              קבוצה {compIdx + 1} — {soldierCount} חיילים, {batches.length} קבוצות
            </div>
            <div className="overflow-x-auto">
            <table className="w-full text-xs min-w-max">
              <thead>
                <tr className="border-b dark:border-gray-600 text-gray-500 dark:text-gray-400">
                  <th className="px-3 py-2 text-right font-medium">תאריכים</th>
                  <th className="px-3 py-2 text-center font-medium">משמרות</th>
                  <th className="px-3 py-2 text-center font-medium">מקומות</th>
                  <th className="px-3 py-2 text-center font-medium">שובץ</th>
                  <th className="px-3 py-2 text-center font-medium">לא שובץ</th>
                  <th className="px-3 py-2 text-center font-medium">תוצאה</th>
                  <th className="px-3 py-2 text-center font-medium">הרפיות</th>
                  <th className="px-3 py-2 text-center font-medium">זמן</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {batches.map(br => (
                  <React.Fragment key={br.batch_index}>
                    <tr
                      className="border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer"
                      onClick={() => setExpandedBatch(expandedBatch === br.batch_index ? null : br.batch_index)}
                    >
                      <td className="px-3 py-2 text-right">{br.date_from} – {br.date_to}</td>
                      <td className="px-3 py-2 text-center">{br.shifts.length > 0 ? br.shifts.length : "—"}</td>
                      <td className="px-3 py-2 text-center">{br.duty_count}</td>
                      <td className="px-3 py-2 text-center text-green-700 dark:text-green-400">{br.assigned_count}</td>
                      <td className={`px-3 py-2 text-center ${br.unassigned_count > 0 ? "text-red-600 dark:text-red-400 font-medium" : "text-gray-400"}`}>
                        {br.unassigned_count}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${OUTCOME_BADGE[br.outcome] ?? OUTCOME_BADGE.CANCELLED}`}>
                          {OUTCOME_LABEL[br.outcome] ?? br.outcome}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center">
                        {br.relaxations.length > 0
                          ? <span className="text-amber-600 dark:text-amber-400">{br.relaxations.join(", ")}</span>
                          : <span className="text-gray-400">—</span>
                        }
                      </td>
                      <td className="px-3 py-2 text-center text-gray-500">{br.wall_time_seconds.toFixed(1)}s</td>
                      <td className="px-3 py-2 text-center text-gray-400">
                        {br.shifts.length > 0 ? (expandedBatch === br.batch_index ? "▲" : "▼") : ""}
                      </td>
                    </tr>
                    {expandedBatch === br.batch_index && br.shifts.length > 0 && (
                      <tr>
                        <td colSpan={9} className="bg-gray-50 dark:bg-gray-900/30 px-4 py-3">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="text-gray-400 dark:text-gray-500">
                                <th className="text-right pb-1 font-medium">משמרת</th>
                                <th className="text-center pb-1 font-medium">נדרש</th>
                                <th className="text-center pb-1 font-medium">שובץ</th>
                                <th className="text-center pb-1 font-medium">חסר</th>
                              </tr>
                            </thead>
                            <tbody>
                              {br.shifts.map((sf, i) => {
                                const missing = sf.required_count - sf.assigned_count;
                                const name = sf.shift_id ? (shiftNames[sf.shift_id] ?? sf.shift_id.slice(0, 8)) : "—";
                                return (
                                  <tr key={i} className="border-t dark:border-gray-700">
                                    <td className="py-1 text-right">{name}</td>
                                    <td className="py-1 text-center">{sf.required_count}</td>
                                    <td className="py-1 text-center text-green-700 dark:text-green-400">{sf.assigned_count}</td>
                                    <td className={`py-1 text-center ${missing > 0 ? "text-red-600 dark:text-red-400 font-medium" : "text-gray-400"}`}>
                                      {missing > 0 ? missing : "—"}
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
