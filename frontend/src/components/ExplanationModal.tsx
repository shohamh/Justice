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

interface Props {
  jobId?: string;          // optional — if omitted, uses direct lookup
  assignmentId: string;
  onClose: () => void;
}

function isDmExplanation(e: SoldierExplanation | DmExplanation): e is DmExplanation {
  return "candidates" in e;
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
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-2xl w-full mx-4 max-h-[80vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">{t("algorithm.why_button")}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-xl">
            ✕
          </button>
        </div>

        {loading && <p className="text-gray-500">{t("app.loading")}</p>}
        {error && <p className="text-red-500">{error}</p>}

        {data && !isDmExplanation(data) && (
          <div className="space-y-3 text-sm">
            <p>{t("algorithm.blocked_count", { count: data.blocked_count })}</p>
            {data.norm_score_before !== null && (
              <p>
                {t("algorithm.norm_before")}:{" "}
                <strong>{data.norm_score_before?.toFixed(3)}</strong>
              </p>
            )}
            {data.norm_score_after !== null && (
              <p>
                {t("algorithm.norm_after")}:{" "}
                <strong>{data.norm_score_after?.toFixed(3)}</strong>
              </p>
            )}
            <p>
              {t("algorithm.min_gap_before")}:{" "}
              <strong>{data.global_before?.min_gap}</strong>
            </p>
            <p>
              {t("algorithm.min_gap_after")}:{" "}
              <strong>{data.global_after?.min_gap}</strong>
            </p>
          </div>
        )}

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
      </div>
    </div>
  );
}
