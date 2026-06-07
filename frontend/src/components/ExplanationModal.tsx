import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CandidateInfo,
  DmExplanation,
  SoldierExplanation,
  getExplanation,
  getExplanationByAssignment,
} from "../api/algorithm";
import { DataTable, type ColDef } from "./DataTable";

interface RankedCandidate {
  soldier_id: string;
  full_name: string;
  score: number | null;
  reason_excluded: string | null;
}

interface EnrichedSoldierExplanation extends SoldierExplanation {
  score_at_assignment: number | null;
  eligible_count: number;
  soldier_rank: number;
  constraint_count: number;
  ranked_candidates: RankedCandidate[];
}

interface Props {
  jobId?: string;          // optional — if omitted, uses direct lookup
  assignmentId: string;
  onClose: () => void;
}

function isDmExplanation(e: SoldierExplanation | DmExplanation): e is DmExplanation {
  return "candidates" in e;
}

function isEnriched(e: SoldierExplanation): e is EnrichedSoldierExplanation {
  return "eligible_count" in e;
}

export default function ExplanationModal({ jobId, assignmentId, onClose }: Props) {
  const { t } = useTranslation();
  const [data, setData] = useState<SoldierExplanation | DmExplanation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const result = jobId
          ? await getExplanation(jobId, assignmentId)
          : await getExplanationByAssignment(assignmentId);
        setData(result);
      } catch {
        setError("שגיאה בטעינת ההסבר");
      } finally {
        setLoading(false);
      }
    })();
  }, [jobId, assignmentId]);

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-5 max-w-lg w-full mx-4 space-y-4 text-sm max-h-[90vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center">
          <h3 className="text-base font-semibold">{t("algorithm.why_button")}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        {loading && <p className="text-gray-500">{t("app.loading")}</p>}
        {error && <p className="text-red-500">{error}</p>}

        {/* DM view — full candidate table (unchanged) */}
        {data && isDmExplanation(data) && (
          <div className="space-y-4 text-sm">
            <div className="grid grid-cols-2 gap-4 bg-gray-50 dark:bg-gray-700 p-3 rounded text-xs">
              <p>
                {t("algorithm.min_gap_before")}: <strong>{data.global_before?.min_gap}</strong>
              </p>
              <p>
                {t("algorithm.min_gap_after")}: <strong>{data.global_after?.min_gap}</strong>
              </p>
            </div>
            {(() => {
              const candidateCols: ColDef<CandidateInfo>[] = [
                {
                  id: "name",
                  header: "חייל",
                  cell: (c) => c.soldier_name || c.soldier_id.slice(0, 8),
                  sortValue: (c) => c.soldier_name || c.soldier_id,
                  filterValue: (c) => c.soldier_name || c.soldier_id,
                },
                {
                  id: "blocked",
                  header: "חסום?",
                  cell: (c) => (c.blocked ? "✗" : "✓"),
                  sortValue: (c) => (c.blocked ? 1 : 0),
                },
                {
                  id: "reason",
                  header: "סיבה",
                  cell: (c) =>
                    c.blocking_constraints.map((k) => t(`algorithm.constraint_${k}`, k)).join(", "),
                },
                {
                  id: "norm_before",
                  header: t("algorithm.norm_before"),
                  cell: (c) => c.pre_norm_score?.toFixed(3) ?? "—",
                  sortValue: (c) => c.pre_norm_score ?? null,
                },
                {
                  id: "norm_after",
                  header: t("algorithm.norm_after"),
                  cell: (c) => c.post_norm_score?.toFixed(3) ?? "—",
                  sortValue: (c) => c.post_norm_score ?? null,
                },
              ];
              return (
                <DataTable
                  columns={candidateCols}
                  data={data.candidates}
                  filterPlaceholder={t("table.filter_placeholder")}
                  rowClassName={(c) => (c.blocked ? "bg-red-50 dark:bg-red-950" : "bg-green-50 dark:bg-green-950")}
                />
              );
            })()}
            {data.tiebreaker_note && (
              <p className="text-gray-600 text-xs">בורר: {data.tiebreaker_note}</p>
            )}
          </div>
        )}

        {/* Soldier view — redesigned */}
        {data && !isDmExplanation(data) && (() => {
          const enriched = isEnriched(data) ? data : null;

          if (!enriched || enriched.eligible_count === 0) {
            return (
              <p className="text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-700 rounded p-3">
                תורנות זו שובצה ידנית — אין הסבר אלגוריתמי.
              </p>
            );
          }

          return (
            <>
              {/* Summary banner */}
              <div className="bg-indigo-50 dark:bg-indigo-950 rounded p-3 font-medium text-indigo-700 dark:text-indigo-300">
                קיבלת תורנות זו כי היה לך הניקוד הנמוך ביותר מבין {enriched.eligible_count} חיילים כשירים בתאריך זה.
              </div>

              {/* Standing table */}
              <div>
                <p className="font-medium text-gray-700 dark:text-gray-300 mb-2">המצב שלך בעת השיבוץ:</p>
                <table className="w-full text-xs border-collapse">
                  <tbody>
                    <tr className="border-b dark:border-gray-700">
                      <td className="py-1 text-gray-500 w-40">ניקוד מצטבר</td>
                      <td className="py-1 font-medium">
                        {enriched.score_at_assignment != null ? enriched.score_at_assignment.toFixed(3) : "—"}
                      </td>
                    </tr>
                    <tr className="border-b dark:border-gray-700">
                      <td className="py-1 text-gray-500">דירוג בין כשירים</td>
                      <td className="py-1 font-medium">{enriched.soldier_rank} / {enriched.eligible_count}</td>
                    </tr>
                    <tr>
                      <td className="py-1 text-gray-500">אילוצים פעילים</td>
                      <td className="py-1 font-medium">{enriched.constraint_count === 0 ? "אין" : enriched.constraint_count}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Rejected candidates */}
              {enriched.ranked_candidates.length > 0 && (
                <div>
                  <p className="font-medium text-gray-700 dark:text-gray-300 mb-2">מדוע אחרים לא נבחרו:</p>
                  <ul className="space-y-1 text-xs text-gray-600 dark:text-gray-400">
                    {enriched.ranked_candidates.map((c) => (
                      <li key={c.soldier_id} className="flex gap-2">
                        <span className="text-gray-400">•</span>
                        <span>
                          <span className="font-medium">{c.full_name}</span>
                          {c.reason_excluded
                            ? ` — ${c.reason_excluded}`
                            : c.score != null
                              ? ` — ניקוד גבוה יותר (${c.score.toFixed(3)})`
                              : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          );
        })()}
      </div>
    </div>
  );
}
