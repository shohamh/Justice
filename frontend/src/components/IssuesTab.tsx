import { AlgorithmJob, BatchResult } from "../api/algorithm";
import { DutyType } from "../api/dutyConfig";
import { DutyShift } from "../api/shifts";
import FailurePanel from "./FailurePanel";

interface Props {
  job: AlgorithmJob;
  dutyTypes: DutyType[];
  shiftNames: Record<string, string>;
  shiftsById: Record<string, DutyShift>;
  onRerun?: (overrides: Record<string, number>) => void;
}

interface UnfilledShift {
  shiftId: string | null;
  shiftName: string;
  batchIndex: number;
  dateFrom: string;
  dateTo: string;
  required: number;
  assigned: number;
  missing: number;
  reason: string;
}

function collectUnfilledShifts(
  batchResults: BatchResult[],
  shiftNames: Record<string, string>,
  shiftsById: Record<string, DutyShift>,
): UnfilledShift[] {
  const result: UnfilledShift[] = [];
  for (const br of batchResults) {
    for (const sf of br.shifts) {
      const missing = sf.required_count - sf.assigned_count;
      if (missing <= 0) continue;
      let reason = "לא ידוע";
      if (br.outcome === "INFEASIBLE") reason = "אין פתרון אפשרי — חסרים חיילים כשירים או קיימים אילוצים מנוגדים";
      else if (br.relaxations.length > 0) reason = `מגבלות הוגמשו (${br.relaxations.join(", ")}) אך לא נמצאו מספיק חיילים`;
      else reason = "אין מספיק חיילים כשירים לאותה תקופה";
      const shift = sf.shift_id ? shiftsById[sf.shift_id] : undefined;
      result.push({
        shiftId: sf.shift_id,
        shiftName: sf.shift_id ? (shiftNames[sf.shift_id] ?? sf.shift_id.slice(0, 8)) : "—",
        batchIndex: br.batch_index,
        dateFrom: shift?.start_date ?? br.date_from,
        dateTo: shift?.end_date ?? br.date_to,
        required: sf.required_count,
        assigned: sf.assigned_count,
        missing,
        reason,
      });
    }
  }
  return result;
}

interface DiagnosticResult {
  rCeilingHitCount: number;
  tCeilingHitCount: number;
  infeasibleCount: number;
  currentRCeiling: number | null;
  currentTCeiling: number | null;
}

function analyzeBatches(batchResults: BatchResult[]): DiagnosticResult {
  let rCeilingHitCount = 0;
  let tCeilingHitCount = 0;
  let infeasibleCount = 0;
  let maxR: number | null = null;
  let maxT: number | null = null;

  for (const br of batchResults) {
    if (br.outcome === "INFEASIBLE") infeasibleCount++;
    for (const rel of br.relaxations) {
      const rMatch = rel.match(/^R→(\d+)$/);
      const tMatch = rel.match(/^T→(\d+)$/);
      if (rMatch) {
        rCeilingHitCount++;
        const val = parseInt(rMatch[1]);
        if (maxR === null || val > maxR) maxR = val;
      }
      if (tMatch) {
        tCeilingHitCount++;
        const val = parseInt(tMatch[1]);
        if (maxT === null || val > maxT) maxT = val;
      }
    }
  }
  return { rCeilingHitCount, tCeilingHitCount, infeasibleCount, currentRCeiling: maxR, currentTCeiling: maxT };
}

export default function IssuesTab({ job, dutyTypes: _dutyTypes, shiftNames, shiftsById, onRerun }: Props) {
  const batchResults = job.batch_results ?? [];
  const unfilledShifts = collectUnfilledShifts(batchResults, shiftNames, shiftsById);
  const diagnostics = analyzeBatches(batchResults);

  const hasAnyIssue =
    unfilledShifts.length > 0 ||
    diagnostics.infeasibleCount > 0 ||
    job.status === "failed";

  const recommendations: { label: string; key: string; value: number }[] = [];
  if (diagnostics.rCeilingHitCount > 0 && diagnostics.currentRCeiling !== null) {
    recommendations.push({
      label: `הגדל relax_r_ceiling ל-${diagnostics.currentRCeiling + 4}`,
      key: "relax_r_ceiling",
      value: diagnostics.currentRCeiling + 4,
    });
  }
  if (diagnostics.tCeilingHitCount > 0 && diagnostics.currentTCeiling !== null) {
    recommendations.push({
      label: `הגדל relax_t_ceiling ל-${diagnostics.currentTCeiling + 2}`,
      key: "relax_t_ceiling",
      value: diagnostics.currentTCeiling + 2,
    });
  }

  if (!hasAnyIssue) {
    return (
      <p className="text-sm text-green-600 dark:text-green-400 text-center py-8" dir="rtl">
        ✓ לא נמצאו בעיות בריצה זו
      </p>
    );
  }

  return (
    <div className="space-y-6 text-sm" dir="rtl">
      {job.status === "failed" && job.error_message !== "cancelled_by_user" && (
        <FailurePanel relaxed={job.relaxed} reasons={job.reasons} />
      )}

      {unfilledShifts.length > 0 && (
        <div>
          <h3 className="font-semibold mb-2 text-gray-800 dark:text-gray-200">
            משמרות לא מאוישות במלואן
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs border dark:border-gray-600 rounded">
              <thead className="bg-gray-50 dark:bg-gray-700">
                <tr className="text-gray-500 dark:text-gray-400">
                  <th className="px-3 py-2 text-right font-medium">משמרת</th>
                  <th className="px-3 py-2 text-center font-medium">תאריכים</th>
                  <th className="px-3 py-2 text-center font-medium">נדרש</th>
                  <th className="px-3 py-2 text-center font-medium">שובץ</th>
                  <th className="px-3 py-2 text-center font-medium text-red-600 dark:text-red-400">חסר</th>
                  <th className="px-3 py-2 text-center font-medium">אצווה</th>
                  <th className="px-3 py-2 text-right font-medium">סיבה</th>
                </tr>
              </thead>
              <tbody>
                {unfilledShifts.map((sf, i) => (
                  <tr key={i} className="border-t dark:border-gray-700">
                    <td className="px-3 py-1.5 text-right">{sf.shiftName}</td>
                    <td className="px-3 py-1.5 text-center">{sf.dateFrom} – {sf.dateTo}</td>
                    <td className="px-3 py-1.5 text-center">{sf.required}</td>
                    <td className="px-3 py-1.5 text-center text-green-700 dark:text-green-400">{sf.assigned}</td>
                    <td className="px-3 py-1.5 text-center text-red-600 dark:text-red-400 font-medium">{sf.missing}</td>
                    <td className="px-3 py-1.5 text-center text-gray-500">B{sf.batchIndex + 1}</td>
                    <td className="px-3 py-1.5 text-right text-gray-600 dark:text-gray-400">{sf.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {(diagnostics.rCeilingHitCount > 0 || diagnostics.tCeilingHitCount > 0 || diagnostics.infeasibleCount > 0) && (
        <div>
          <h3 className="font-semibold mb-2 text-gray-800 dark:text-gray-200">אבחון</h3>
          <ul className="space-y-2 text-gray-700 dark:text-gray-300 text-xs">
            {diagnostics.rCeilingHitCount > 0 && diagnostics.currentRCeiling !== null && (
              <li className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded p-2">
                <span className="font-medium">⚠ מגבלת שיבוצים לחלון ארוך-טווח (R={diagnostics.currentRCeiling}) הוגמשה ב-{diagnostics.rCeilingHitCount} אצוות</span>
                <span className="block mt-0.5 text-gray-500 dark:text-gray-400">
                  האלגוריתם שיבץ יותר תורנויות מהמותר בחלון הזמן הארוך. ניתן להגדיל את R בהגדרות מתקדמות, או לצמצם את כמות המשמרות.
                </span>
              </li>
            )}
            {diagnostics.tCeilingHitCount > 0 && diagnostics.currentTCeiling !== null && (
              <li className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded p-2">
                <span className="font-medium">⚠ מגבלת צפיפות שיבוצים (T={diagnostics.currentTCeiling}) הוגמשה ב-{diagnostics.tCeilingHitCount} אצוות</span>
                <span className="block mt-0.5 text-gray-500 dark:text-gray-400">
                  האלגוריתם שיבץ יותר תורנויות מהמותר בחלון קצר-טווח. ניתן להגדיל את T בהגדרות מתקדמות.
                </span>
              </li>
            )}
            {diagnostics.infeasibleCount > 0 && (
              <li className="bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded p-2">
                <span className="font-medium">✗ {diagnostics.infeasibleCount} אצוות נשארו ללא פתרון</span>
                <span className="block mt-0.5 text-gray-500 dark:text-gray-400">
                  האלגוריתם לא הצליח לאייש את כל המשמרות גם לאחר הגמשת המגבלות. הסיבות הנפוצות: אין מספיק חיילים כשירים לאותה תקופה, יותר מדי אילוצים אישיים מאושרים, או שמספר המשמרות גבוה מדי ביחס לגודל הכוח.
                </span>
              </li>
            )}
          </ul>
        </div>
      )}

      {recommendations.length > 0 && onRerun && (
        <div>
          <h3 className="font-semibold mb-2 text-gray-800 dark:text-gray-200">המלצות</h3>
          <ul className="space-y-1 text-xs text-gray-700 dark:text-gray-300 mb-3">
            {recommendations.map((r, i) => (
              <li key={i}>→ {r.label}</li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => onRerun(Object.fromEntries(recommendations.map(r => [r.key, r.value])))}
            className="px-4 py-2 bg-indigo-600 text-white text-xs rounded hover:bg-indigo-700"
          >
            הרץ שוב עם הגדרות מומלצות
          </button>
        </div>
      )}

      {diagnostics.infeasibleCount > 0 && recommendations.length === 0 && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          לא ניתן להציע שינוי פרמטרים — ייתכן שחסרים חיילים כשירים לחלק מהמשמרות.
        </p>
      )}
    </div>
  );
}
