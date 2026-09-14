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
import SoldierLink from "./SoldierLink";
import { lastDutyDay } from "../utils/formatDate";

interface EnrichedSoldierExplanation extends SoldierExplanation {
  score_at_assignment: number | null;
  eligible_count: number;
  rank_from_bottom: number | null;
  ahead_count: number | null;
  ahead_breakdown: AheadBreakdown | null;
}

interface DecisionSummaryData {
  score_at_assignment: number | null;
  eligible_count: number | null;
  rank_from_bottom: number | null;
  ahead_count: number | null;
  ahead_breakdown: AheadBreakdown | null;
  tiebreaker_note: string | null;
}

const AHEAD_BREAKDOWN_ORDER: (keyof AheadBreakdown)[] = [
  "personal_constraint", "exemption", "weapon_ineligible", "overlap", "randomness",
];

function formatBurdenShare(value: number | null | undefined): string {
  return value == null ? "—" : `${(value * 100).toFixed(2)}%`;
}

function aheadBreakdownLabelKey(key: keyof AheadBreakdown, count: number): string {
  return `algorithm.explanation_ahead_${key}_${count === 1 ? "one" : "other"}`;
}

interface Props {
  jobId?: string;
  assignmentId: string;
  title?: string;
  onClose: () => void;
}

function isDmExplanation(e: SoldierExplanation | DmExplanation): e is DmExplanation {
  return "candidates" in e;
}

function isEnriched(e: SoldierExplanation): e is EnrichedSoldierExplanation {
  return "eligible_count" in e;
}

function getManagerDecisionSummary(data: DmExplanation): DecisionSummaryData {
  const assignedCandidate = data.candidates.find(
    (candidate) => candidate.soldier_id === data.assigned_soldier_id && !candidate.blocked,
  );
  const rankFromBottom = data.rank_from_bottom ?? data.assigned_rank ?? null;

  return {
    score_at_assignment: data.score_at_assignment ?? assignedCandidate?.pre_norm_score ?? null,
    eligible_count: data.eligible_count ?? data.pool_size ?? null,
    rank_from_bottom: rankFromBottom,
    ahead_count: data.ahead_count ?? (rankFromBottom == null ? null : rankFromBottom - 1),
    ahead_breakdown: data.ahead_breakdown ?? null,
    tiebreaker_note: data.tiebreaker_note,
  };
}

function DecisionSummary({ data }: { data: DecisionSummaryData }) {
  const { t } = useTranslation();

  if (!data.eligible_count) {
    return (
      <p className="text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-700 rounded p-3">
        {t("algorithm.explanation_manual")}
      </p>
    );
  }

  return (
    <div data-testid="explanation-decision-summary" className="space-y-4">
      <div>
        <p className="font-medium text-gray-700 dark:text-gray-300 mb-2">{t("algorithm.explanation_standing")}</p>
        <table className="w-full text-xs border-collapse">
          <tbody>
            <tr className="border-b dark:border-gray-700">
              <td className="py-1 text-gray-500 w-40">{t("algorithm.explanation_load")}</td>
              <td className="py-1 font-medium">
                {formatBurdenShare(data.score_at_assignment)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div>
        <p className="font-medium text-gray-700 dark:text-gray-300 mb-2">
          {data.rank_from_bottom == null ? (
            t("algorithm.explanation_rank_unavailable")
          ) : data.rank_from_bottom > 1
            ? t("algorithm.explanation_rank_from_bottom", { rank: data.rank_from_bottom })
            : t("algorithm.explanation_rank_from_bottom_top")}
        </p>
        {data.ahead_breakdown == null ? (
          data.ahead_count != null && data.ahead_count > 0 && (
            <p className="text-xs text-gray-500 dark:text-gray-400">{t("algorithm.explanation_ahead_unavailable")}</p>
          )
        ) : data.ahead_count != null && data.ahead_count > 0 ? (
          <ul className="space-y-1 text-xs text-gray-600 dark:text-gray-400">
            <li className="font-medium text-gray-700 dark:text-gray-300">
              {t(
                data.ahead_count === 1
                  ? "algorithm.explanation_ahead_intro_one"
                  : "algorithm.explanation_ahead_intro_other",
                { count: data.ahead_count },
              )}
            </li>
            {AHEAD_BREAKDOWN_ORDER.filter((key) => data.ahead_breakdown![key] > 0).map((key) => (
              <li key={key} className="flex gap-2">
                <span className="text-gray-400">•</span>
                <span>
                  {t(aheadBreakdownLabelKey(key, data.ahead_breakdown![key]), {
                    count: data.ahead_breakdown![key],
                  })}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {data.tiebreaker_note && (
        <p className="text-gray-500 dark:text-gray-400 text-xs">
          {t("algorithm.explanation_tiebreaker_lowest")}
        </p>
      )}
    </div>
  );
}

export default function ExplanationModal({ jobId, assignmentId, title, onClose }: Props) {
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
          <h3 className="text-base font-semibold">{title ?? t("algorithm.why_button")}</h3>
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
        {data?.explanation_available === false && (
          <p className="text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-700 rounded p-3">
            {t("algorithm.explanation_manual")}
          </p>
        )}

        {/* DM view */}
        {data && data.explanation_available !== false && isDmExplanation(data) && (
          <div className="space-y-4 text-sm">
            <DecisionSummary data={getManagerDecisionSummary(data)} />
            <div className="grid grid-cols-2 gap-4 bg-gray-50 dark:bg-gray-700 p-3 rounded text-xs">
              <p>
                {t("algorithm.min_gap_before")}: <strong data-testid="explanation-min-gap-before">{data.global_before?.min_gap ?? "—"}</strong>
              </p>
              <p>
                {t("algorithm.min_gap_after")}: <strong data-testid="explanation-min-gap-after">{data.global_after?.min_gap ?? "—"}</strong>
              </p>
            </div>
            {(() => {
              const candidateCols: ColDef<CandidateInfo>[] = [
                {
                  id: "name",
                  header: t("algorithm.explanation_candidate_col"),
                  cell: (c) => (
                    <SoldierLink
                      id={c.soldier_id}
                      name={c.soldier_name || c.soldier_id.slice(0, 8)}
                    />
                  ),
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
                    c.blocking_constraints.length > 0
                      ? c.blocking_constraints.map((k) => t(`algorithm.constraint_${k}`, k)).join(", ")
                      : c.soldier_id === data.assigned_soldier_id
                        ? t("algorithm.explanation_reason_assigned")
                        : t("algorithm.explanation_reason_eligible_not_selected"),
                },
                {
                  id: "burden_share_before",
                  header: t("algorithm.burden_share_before"),
                  cell: (c) => formatBurdenShare(c.pre_norm_score),
                  sortValue: (c) => c.pre_norm_score ?? null,
                },
                {
                  id: "burden_share_after",
                  header: t("algorithm.burden_share_after"),
                  cell: (c) => formatBurdenShare(c.post_norm_score),
                  sortValue: (c) => c.post_norm_score ?? null,
                },
              ];
              return (
                <DataTable
                  columns={candidateCols}
                  data={data.candidates}
                  filterPlaceholder={t("table.filter_placeholder")}
                  tableClassName="min-w-[600px]"
                  rowClassName={(c) => (c.blocked ? "bg-red-50 dark:bg-red-950" : "bg-green-50 dark:bg-green-950")}
                />
              );
            })()}
          </div>
        )}

        {/* Soldier view */}
        {data && data.explanation_available !== false && !isDmExplanation(data) && (() => {
          const enriched = isEnriched(data) ? data : null;

          if (!enriched || enriched.eligible_count === 0) {
            return (
              <p className="text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-700 rounded p-3">
                {t("algorithm.explanation_manual")}
              </p>
            );
          }

          return <DecisionSummary data={enriched} />;
        })()}
      </div>
    </div>
  );
}
