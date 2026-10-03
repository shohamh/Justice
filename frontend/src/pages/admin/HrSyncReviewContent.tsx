import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import {
  listHeldForReview, dismissHeldForReview,
  listDivergences, clearFieldOverride,
  listVanished, listRankConflicts, listSyncRuns, runSyncNow,
} from "../../api/hrReview";
import { DataTable, ColDef } from "../../components/DataTable";
import HrIdentityConflictsSection from "./HrIdentityConflictsSection";
import type {
  HeldForReviewItemDTO, DivergenceItemDTO, VanishedItemDTO,
  RankConflictItemDTO, PersonSyncRunDTO, HierarchySyncRunDTO,
} from "../../api/hrReview";

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function soldierLabel(fullName: string | null, personalNumber: string | null): string {
  if (!fullName && !personalNumber) return "—";
  return [fullName, personalNumber].filter(Boolean).join(" · ");
}

function rawDtoFullName(rawDto: Record<string, unknown> | null): string | null {
  const value = rawDto?.fullName;
  return typeof value === "string" && value.trim() ? value : null;
}

function splitReasons(reviewReason: string | null): string[] {
  if (!reviewReason) return [];
  return reviewReason.split("; ").map((r) => r.trim()).filter(Boolean);
}

// Human-friendly labels for the HR payload's own field names (raw_dto is
// stored by HR's JSON aliases, e.g. "fullName"/"serviceType", not our
// snake_case names) — curated to the fields relevant for a held-for-review
// decision, in the order they should read.
const RAW_DTO_FIELD_LABELS: [key: string, label: string][] = [
  ["fullName", "שם מלא"],
  ["personalNumber", "מספר אישי"],
  ["rank", "דרגה"],
  ["gender", "מגדר"],
  ["serviceType", "סוג שירות"],
  ["dateOfBirth", "תאריך לידה"],
  ["serviceStartDate", "תאריך תחילת שירות"],
  ["serviceEndDate", "תאריך סיום שירות"],
  ["endHovaDate", "תאריך סיום חובה"],
  ["maritalStatus", "מצב משפחתי"],
  ["mail", "דוא\"ל"],
  ["phone", "טלפון"],
  ["status", "סטטוס"],
  ["unit", "יחידה"],
  ["branch", "מסגרת"],
  ["department", "מחלקה"],
  ["shetach", "שטח"],
  ["mador", "מדור"],
  ["team", "צוות"],
  ["hulia", "חוליה"],
  ["palga", "פלגה"],
];

// A held-for-review reason string names the offending field using either
// the raw HR key ("unmappable gender: 'X'") or a Justice-side snake_case
// name ("missing personal_number") — normalize both to the raw_dto key so
// the table can highlight the right row regardless of phrasing.
const REASON_FIELD_TO_RAW_DTO_KEY: Record<string, string> = {
  personal_number: "personalNumber",
  full_name: "fullName",
};

function reasonFieldKey(reason: string): string | null {
  const match = /^(?:unmappable|unparseable|missing)\s+([A-Za-z_]+)/.exec(reason);
  if (!match) return null;
  return REASON_FIELD_TO_RAW_DTO_KEY[match[1]] ?? match[1];
}

function formatRawDtoValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "כן" : "לא";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function errorMessage(error: unknown): string | null {
  if (!error) return null;
  if (error instanceof Error) return error.message;
  return String(error);
}

export default function HrSyncReviewContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [selectedHeld, setSelectedHeld] = useState<HeldForReviewItemDTO | null>(null);
  const [selectedRunErrors, setSelectedRunErrors] = useState<PersonSyncRunDTO | null>(null);

  const heldQuery = useQuery({ queryKey: ["hr-sync-held"], queryFn: listHeldForReview });
  const divergencesQuery = useQuery({ queryKey: ["hr-sync-divergences"], queryFn: listDivergences });
  const vanishedQuery = useQuery({ queryKey: ["hr-sync-vanished"], queryFn: listVanished });
  const conflictsQuery = useQuery({ queryKey: ["hr-sync-conflicts"], queryFn: listRankConflicts });
  const runsQuery = useQuery({ queryKey: ["hr-sync-runs"], queryFn: listSyncRuns });

  const dismissMutation = useMutation({
    mutationFn: (profileId: string) => dismissHeldForReview(profileId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["hr-sync-held"] }),
  });
  const clearOverrideMutation = useMutation({
    mutationFn: ({ profileId, fieldName }: { profileId: string; fieldName: string }) =>
      clearFieldOverride(profileId, fieldName),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["hr-sync-divergences"] }),
  });
  const runNowMutation = useMutation({
    mutationFn: runSyncNow,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-held"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-divergences"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-vanished"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-conflicts"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-identity-conflicts"] });
    },
  });

  const heldColumns: ColDef<HeldForReviewItemDTO>[] = [
    {
      id: "personal_number", header: t("admin.hr_sync.soldier"),
      cell: (r) => (
        <button
          type="button"
          data-testid={`hr-sync-held-detail-${r.id}`}
          className="text-indigo-600 dark:text-indigo-300 underline underline-offset-2 hover:text-indigo-800 dark:hover:text-indigo-200"
          onClick={() => setSelectedHeld(r)}
        >
          {soldierLabel(rawDtoFullName(r.raw_dto), r.personal_number)}
        </button>
      ),
    },
    {
      id: "review_reason", header: t("admin.hr_sync.reason"),
      cell: (r) => {
        const reasons = splitReasons(r.review_reason);
        if (reasons.length === 0) return "—";
        return reasons.length === 1 ? reasons[0] : `${reasons[0]} (+${reasons.length - 1})`;
      },
    },
    {
      id: "actions", header: "", cell: (r) => (
        <button
          type="button"
          data-testid={`hr-sync-dismiss-${r.id}`}
          className="px-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600"
          onClick={() => dismissMutation.mutate(r.id)}
        >
          {t("admin.hr_sync.dismiss")}
        </button>
      ),
    },
  ];

  const divergenceColumns: ColDef<DivergenceItemDTO>[] = [
    {
      id: "soldier", header: t("admin.hr_sync.soldier"),
      cell: (r) => soldierLabel(r.soldier_full_name, r.soldier_personal_number),
    },
    { id: "field_name", header: t("admin.hr_sync.field"), cell: (r) => r.field_name },
    { id: "hr_value", header: t("admin.hr_sync.hr_value"), cell: (r) => formatRawDtoValue(r.hr_value) },
    { id: "local_value", header: t("admin.hr_sync.local_value"), cell: (r) => formatRawDtoValue(r.local_value) },
    {
      id: "actions", header: "", cell: (r) => (
        <button
          type="button"
          data-testid={`hr-sync-clear-override-${r.id}`}
          className="px-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600"
          onClick={() => clearOverrideMutation.mutate({ profileId: r.soldier_hr_profile_id, fieldName: r.field_name })}
        >
          {t("admin.hr_sync.clear_override")}
        </button>
      ),
    },
  ];

  const vanishedColumns: ColDef<VanishedItemDTO>[] = [
    { id: "personal_number", header: t("admin.hr_sync.personal_number"), cell: (r) => r.personal_number },
  ];

  const conflictColumns: ColDef<RankConflictItemDTO>[] = [
    {
      id: "soldier", header: t("admin.hr_sync.soldier"),
      cell: (r) => soldierLabel(r.soldier_full_name, r.soldier_personal_number),
    },
    { id: "old_rank", header: t("admin.hr_sync.old_rank"), cell: (r) => r.old_rank ?? "—" },
    { id: "new_rank", header: t("admin.hr_sync.new_rank"), cell: (r) => r.new_rank ?? "—" },
    {
      id: "why", header: t("admin.hr_sync.why"),
      cell: (r) => {
        if (r.triggered_by_worker_decision && r.non_sequential_jump) {
          return `${t("admin.hr_sync.why_worker")}, ${t("admin.hr_sync.why_jump")}`;
        }
        return r.triggered_by_worker_decision ? t("admin.hr_sync.why_worker") : t("admin.hr_sync.why_jump");
      },
    },
  ];

  const runColumns: ColDef<PersonSyncRunDTO>[] = [
    { id: "started_at", header: t("admin.hr_sync.started_at"), cell: (r) => formatDateTime(r.started_at) },
    { id: "status", header: t("admin.hr_sync.status"), cell: (r) => r.status },
    { id: "total_fetched", header: t("admin.hr_sync.total_fetched"), cell: (r) => r.total_fetched },
    { id: "created_count", header: t("admin.hr_sync.created_count"), cell: (r) => r.created_count },
    { id: "updated_count", header: t("admin.hr_sync.updated_count"), cell: (r) => r.updated_count },
    { id: "held_count", header: t("admin.hr_sync.held_count"), cell: (r) => r.held_count },
    { id: "conflict_count", header: t("admin.hr_sync.identity_conflicts"), cell: (r) => r.conflict_count ?? 0 },
    {
      id: "errors", header: t("admin.hr_sync.errors"),
      cell: (r) => (
        r.errors.length > 0 ? (
          <button
            type="button"
            data-testid={`hr-sync-run-errors-${r.id}`}
            className="text-red-600 dark:text-red-400 underline underline-offset-2"
            onClick={() => setSelectedRunErrors(r)}
          >
            {r.errors.length}
          </button>
        ) : (
          "0"
        )
      ),
    },
  ];

  const hierarchyRunColumns: ColDef<HierarchySyncRunDTO>[] = [
    { id: "started_at", header: t("admin.hr_sync.started_at"), cell: (r) => formatDateTime(r.started_at) },
    { id: "status", header: t("admin.hr_sync.status"), cell: (r) => r.status },
    { id: "created_count", header: t("admin.hr_sync.created_count"), cell: (r) => r.created_count },
    { id: "held_count", header: t("admin.hr_sync.held_count"), cell: (r) => r.held_count },
    { id: "error_message", header: t("admin.hr_sync.error_message"), cell: (r) => r.error_message ?? "—" },
  ];

  function renderSection<T>(
    testId: string,
    query: { isError: boolean; isLoading: boolean; data?: { items: T[] } | undefined },
    columns: ColDef<T>[],
    data: T[],
  ) {
    if (query.isError) {
      return (
        <div className="text-sm text-red-600 dark:text-red-400" data-testid={`${testId}-error`}>
          {t("admin.hr_sync.load_error")}
        </div>
      );
    }
    if (query.isLoading) {
      return (
        <div className="text-sm text-gray-500" data-testid={`${testId}-loading`}>
          {t("admin.hr_sync.loading")}
        </div>
      );
    }
    return (
      <DataTable columns={columns} data={data} testId={testId} emptyMessage={t("admin.hr_sync.empty")} />
    );
  }

  const dismissError = errorMessage(dismissMutation.error);
  const clearOverrideError = errorMessage(clearOverrideMutation.error);
  const runNowError = errorMessage(runNowMutation.error);

  return (
    <div className="space-y-6" data-testid="hr-sync-review-content">
      <div className="flex flex-col items-end gap-1">
        <button
          type="button"
          data-testid="hr-sync-run-now"
          className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white disabled:opacity-50"
          disabled={runNowMutation.isPending}
          onClick={() => runNowMutation.mutate()}
        >
          {t("admin.hr_sync.run_now")}
        </button>
        {runNowError && (
          <div className="text-sm text-red-600 dark:text-red-400" data-testid="hr-sync-run-now-error">
            {runNowError}
          </div>
        )}
      </div>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.held_for_review")}</h3>
        {renderSection("hr-sync-held-table", heldQuery, heldColumns, heldQuery.data?.items ?? [])}
        {dismissError && (
          <div className="text-sm text-red-600 dark:text-red-400 mt-1" data-testid="hr-sync-dismiss-error">
            {dismissError}
          </div>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.divergences")}</h3>
        {renderSection("hr-sync-divergences-table", divergencesQuery, divergenceColumns, divergencesQuery.data?.items ?? [])}
        {clearOverrideError && (
          <div className="text-sm text-red-600 dark:text-red-400 mt-1" data-testid="hr-sync-clear-override-error">
            {clearOverrideError}
          </div>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.vanished")}</h3>
        {renderSection("hr-sync-vanished-table", vanishedQuery, vanishedColumns, vanishedQuery.data?.items ?? [])}
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.rank_conflicts")}</h3>
        {renderSection("hr-sync-conflicts-table", conflictsQuery, conflictColumns, conflictsQuery.data?.items ?? [])}
      </section>

      <section data-testid="hr-sync-identity-conflicts">
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.identity_conflicts")}</h3>
        <HrIdentityConflictsSection />
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.run_history")}</h3>
        {runsQuery.isError ? (
          <div className="text-sm text-red-600 dark:text-red-400" data-testid="hr-sync-runs-table-error">
            {t("admin.hr_sync.load_error")}
          </div>
        ) : runsQuery.isLoading ? (
          <div className="text-sm text-gray-500" data-testid="hr-sync-runs-table-loading">
            {t("admin.hr_sync.loading")}
          </div>
        ) : (
          <div className="space-y-3">
            <DataTable
              columns={runColumns}
              data={runsQuery.data?.person_syncs ?? []}
              testId="hr-sync-runs-table"
              emptyMessage={t("admin.hr_sync.empty")}
            />
            <DataTable
              columns={hierarchyRunColumns}
              data={runsQuery.data?.hierarchy_syncs ?? []}
              testId="hr-sync-hierarchy-runs-table"
              emptyMessage={t("admin.hr_sync.empty")}
            />
          </div>
        )}
      </section>

      {selectedHeld && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/50"
          data-testid="hr-sync-held-detail-modal"
          onClick={() => setSelectedHeld(null)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto p-4 space-y-3 text-sm"
            dir="rtl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-semibold">
                  {rawDtoFullName(selectedHeld.raw_dto) ?? selectedHeld.personal_number}
                </h3>
                {rawDtoFullName(selectedHeld.raw_dto) && (
                  <div dir="ltr" className="text-xs text-gray-500 dark:text-gray-400">
                    {selectedHeld.personal_number}
                  </div>
                )}
              </div>
              <button
                type="button"
                data-testid="hr-sync-held-detail-close"
                onClick={() => setSelectedHeld(null)}
                className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              >
                <X size={18} />
              </button>
            </div>

            <div>
              <div className="mb-1 text-gray-500 dark:text-gray-400">{t("admin.hr_sync.reasons")}</div>
              {splitReasons(selectedHeld.review_reason).length > 0 ? (
                <ul className="space-y-1" data-testid="hr-sync-held-detail-reasons">
                  {splitReasons(selectedHeld.review_reason).map((reason, i) => (
                    <li
                      key={i}
                      className="rounded bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-300 px-2 py-1"
                    >
                      {reason}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-gray-700 dark:text-gray-300">—</div>
              )}
            </div>

            {(() => {
              const rawDto = selectedHeld.raw_dto ?? {};
              const flagged = new Set(splitReasons(selectedHeld.review_reason).map(reasonFieldKey).filter(Boolean));
              const extraKeys = Object.keys(rawDto).filter(
                (k) => flagged.has(k) && !RAW_DTO_FIELD_LABELS.some(([key]) => key === k)
              );
              const rows: [string, string][] = [
                ...RAW_DTO_FIELD_LABELS,
                ...extraKeys.map((k): [string, string] => [k, k]),
              ];
              return (
                <div>
                  <div className="mb-1 text-gray-500 dark:text-gray-400">{t("admin.hr_sync.hr_data")}</div>
                  <table className="w-full text-xs border-collapse" data-testid="hr-sync-held-detail-fields">
                    <tbody>
                      {rows.map(([key, label]) => {
                        const isFlagged = flagged.has(key);
                        return (
                          <tr
                            key={key}
                            className={isFlagged ? "bg-red-50 dark:bg-red-950/40" : undefined}
                            data-testid={`hr-sync-held-detail-field-${key}`}
                          >
                            <td className="border dark:border-gray-600 px-2 py-1 font-medium whitespace-nowrap">
                              {label}
                            </td>
                            <td
                              dir="auto"
                              className={
                                "border dark:border-gray-600 px-2 py-1 " +
                                (isFlagged ? "text-red-800 dark:text-red-300 font-medium" : "")
                              }
                            >
                              {formatRawDtoValue(rawDto[key])}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>

                  <details className="mt-3">
                    <summary className="cursor-pointer text-gray-500 dark:text-gray-400">
                      {t("admin.hr_sync.raw_payload")}
                    </summary>
                    <pre
                      dir="ltr"
                      data-testid="hr-sync-held-detail-raw-dto"
                      className="bg-gray-50 dark:bg-gray-900 rounded p-2 text-xs overflow-x-auto whitespace-pre-wrap break-all mt-2"
                    >
                      {selectedHeld.raw_dto ? JSON.stringify(selectedHeld.raw_dto, null, 2) : "—"}
                    </pre>
                  </details>
                </div>
              );
            })()}
          </div>
        </div>
      )}

      {selectedRunErrors && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/50"
          data-testid="hr-sync-run-errors-modal"
          onClick={() => setSelectedRunErrors(null)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto p-4 space-y-2 text-sm"
            dir="rtl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold">{t("admin.hr_sync.errors")}</h3>
              <button
                type="button"
                data-testid="hr-sync-run-errors-close"
                onClick={() => setSelectedRunErrors(null)}
                className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              >
                <X size={18} />
              </button>
            </div>
            <ul className="space-y-1">
              {selectedRunErrors.errors.map((e, i) => (
                <li key={i} className="text-red-700 dark:text-red-300">
                  <span dir="ltr">{e.personal_number}</span>: {e.error_message}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
