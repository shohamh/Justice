import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useModalBackClose } from "../hooks/useModalBackClose";
import {
  AheadBreakdown,
  CandidateInfo,
  DmExplanation,
  SoldierExplanation,
  getExplanation,
  getExplanationByAssignment,
} from "../api/algorithm";
import { DataTable, type ColDef } from "./DataTable";
import { lastDutyDay } from "../utils/formatDate";

interface EnrichedSoldierExplanation extends SoldierExplanation {
  score_at_assignment: number | null;
  eligible_count: number;
  rank_from_bottom: number | null;
  ahead_count: number | null;
  ahead_breakdown: AheadBreakdown | null;
}

const AHEAD_BREAKDOWN_ORDER: (keyof AheadBreakdown)[] = [
  "personal_constraint", "exemption", "weapon_ineligible", "overlap", "randomness",
];

interface Props {
  jobId?: string;
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
  useModalBackClose(onClose);
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
        setError(t("algorithm.explanation_error"));
      } finally {
        setLoading(false);
      }
    })();
  }, [jobId, assignmentId, t]);

  const ctx = data?.assignment_context;

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
        {/* Header */}
        <div className="flex justify-between items-center">
          <h3 className="text-base font-semibold">{t("algorithm.why_button")}</h3>
          <button
            onClick={onClose}
            aria-label={t("app.close")}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            ×
          </button>
        </div>

        {/* Context strip */}
        {ctx && (
          <div className="bg-gray-50 dark:bg-gray-700 rounded px-3 py-2 text-xs text-gray-600 dark:text-gray-300 flex flex-wrap gap-x-4 gap-y-1">
            <span><span className="text-gray-400">{t("algorithm.col_soldier")}:</span> <strong>{ctx.soldier_name}</strong></span>
            <span><span className="text-gray-400">{t("algorithm.col_type")}:</span> <strong>{ctx.duty_type_name}</strong></span>
            <span><span className="text-gray-400">{t("algorithm.col_date")}:</span> <strong>{ctx.start_date}{lastDutyDay(ctx.end_date) !== ctx.start_date ? ` – ${lastDutyDay(ctx.end_date)}` : ""}</strong></span>
          </div>
        )}

        {loading && <p className="text-gray-500">{t("app.loading")}</p>}
        {error && <p className="text-red-500">{error}</p>}

        {/* DM view */}
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
                  header: t("algorithm.explanation_candidate_col"),
                  cell: (c) => c.soldier_name || c.soldier_id.slice(0, 8),
                  sortValue: (c) => c.soldier_name || c.soldier_id,
                  filterValue: (c) => c.soldier_name || c.soldier_id,
                },
                {
                  id: "eligible",
                  header: t("algorithm.explanation_eligible_col"),
                  cell: (c) => (c.blocked ? "✗" : "✓"),
                  sortValue: (c) => (c.blocked ? 1 : 0),
                },
                {
                  id: "reason",
                  header: t("algorithm.explanation_reason_col"),
                  cell: (c) =>
                    c.blocking_constraints.map((k) => t(`algorithm.constraint_${k}`, k)).join(", "),
                },
                {
                  id: "norm_before",
                  header: t("algorithm.norm_before"),
                  cell: (c) => c.pre_norm_score != null ? (c.pre_norm_score * 100).toFixed(1) + "%" : "—",
                  sortValue: (c) => c.pre_norm_score ?? null,
                },
                {
                  id: "norm_after",
                  header: t("algorithm.norm_after"),
                  cell: (c) => c.post_norm_score != null ? (c.post_norm_score * 100).toFixed(1) + "%" : "—",
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
              <p className="text-gray-600 dark:text-gray-400 text-xs">
                {t("algorithm.explanation_tiebreaker_lowest")}
              </p>
            )}
          </div>
        )}

        {/* Soldier view */}
        {data && !isDmExplanation(data) && (() => {
          const enriched = isEnriched(data) ? data : null;

          if (!enriched || enriched.eligible_count === 0) {
            return (
              <p className="text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-700 rounded p-3">
                {t("algorithm.explanation_manual")}
              </p>
            );
          }

          return (
            <>
              {/* Standing table */}
              <div>
                <p className="font-medium text-gray-700 dark:text-gray-300 mb-2">{t("algorithm.explanation_standing")}</p>
                <table className="w-full text-xs border-collapse">
                  <tbody>
                    <tr className="border-b dark:border-gray-700">
                      <td className="py-1 text-gray-500 w-40">{t("algorithm.explanation_load")}</td>
                      <td className="py-1 font-medium">
                        {enriched.score_at_assignment != null
                          ? (enriched.score_at_assignment * 100).toFixed(1) + "%"
                          : "—"}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Rank + aggregate breakdown of who ranks ahead — counts only,
                  no other soldier's name/id/score is ever shown here. */}
              <div>
                <p className="font-medium text-gray-700 dark:text-gray-300 mb-2">
                  {enriched.rank_from_bottom != null && enriched.rank_from_bottom > 1
                    ? t("algorithm.explanation_rank_from_bottom", { rank: enriched.rank_from_bottom })
                    : t("algorithm.explanation_rank_from_bottom_top")}
                </p>
                {enriched.ahead_breakdown == null ? (
                  enriched.ahead_count != null && enriched.ahead_count > 0 && (
                    <p className="text-xs text-gray-500 dark:text-gray-400">{t("algorithm.explanation_ahead_unavailable")}</p>
                  )
                ) : enriched.ahead_count != null && enriched.ahead_count > 0 ? (
                  <ul className="space-y-1 text-xs text-gray-600 dark:text-gray-400">
                    <li className="font-medium text-gray-700 dark:text-gray-300">
                      {t("algorithm.explanation_ahead_intro", { count: enriched.ahead_count })}
                    </li>
                    {AHEAD_BREAKDOWN_ORDER.filter((key) => (enriched.ahead_breakdown as AheadBreakdown)[key] > 0).map((key) => (
                      <li key={key} className="flex gap-2">
                        <span className="text-gray-400">•</span>
                        <span>{t(`algorithm.explanation_ahead_${key}`, { count: (enriched.ahead_breakdown as AheadBreakdown)[key] })}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>

              {enriched.tiebreaker_note && (
                <p className="text-gray-500 dark:text-gray-400 text-xs">
                  {t("algorithm.explanation_tiebreaker_lowest")}
                </p>
              )}
            </>
          );
        })()}
      </div>
    </div>
  );
}
