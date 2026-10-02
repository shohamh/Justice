import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  acknowledgeHrIdentityConflict, chooseHrIdentityCandidate, clearHrPreferredRecord,
  listHrIdentityConflicts, listHrPreferredRecords,
} from "../../api/hrReview";
import type { HrIdentityCandidateDTO, HrIdentityConflictDTO, HrPreferredRecordDTO } from "../../api/hrReview";
import { translateApiError } from "../../utils/translateApiError";

const CONFLICTS_KEY = ["hr-sync-identity-conflicts"];
const PREFERRED_KEY = ["hr-sync-preferred-records"];

// Identifying HR fields first, in reading order; any other payload keys follow as-is.
const PAYLOAD_FIELD_ORDER = ["fullName", "personalNumber", "mail", "username", "tPersonId", "rank", "unit", "status"];

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function payloadEntries(payload: Record<string, unknown>): [string, string][] {
  const keys = Object.keys(payload);
  const ordered = [
    ...PAYLOAD_FIELD_ORDER.filter((k) => keys.includes(k)),
    ...keys.filter((k) => !PAYLOAD_FIELD_ORDER.includes(k)).sort(),
  ];
  return ordered
    .filter((k) => payload[k] !== null && payload[k] !== undefined && payload[k] !== "")
    .map((k) => [k, typeof payload[k] === "object" ? JSON.stringify(payload[k]) : String(payload[k])]);
}

export default function HrIdentityConflictsSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const conflictsQuery = useQuery({ queryKey: CONFLICTS_KEY, queryFn: () => listHrIdentityConflicts("open") });
  const preferredQuery = useQuery({ queryKey: PREFERRED_KEY, queryFn: listHrPreferredRecords });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: CONFLICTS_KEY });
    void queryClient.invalidateQueries({ queryKey: PREFERRED_KEY });
    void queryClient.invalidateQueries({ queryKey: ["hr-sync-runs"] });
  }

  const acknowledgeMutation = useMutation({
    mutationFn: (id: string) => acknowledgeHrIdentityConflict(id),
    onSuccess: refresh,
  });
  const chooseMutation = useMutation({
    mutationFn: ({ id, index }: { id: string; index: number }) => chooseHrIdentityCandidate(id, index),
    onSuccess: refresh,
  });
  const clearMutation = useMutation({
    mutationFn: (personalNumber: string) => clearHrPreferredRecord(personalNumber),
    onSuccess: refresh,
  });

  const actionError = acknowledgeMutation.error ?? chooseMutation.error ?? clearMutation.error;
  const busy = acknowledgeMutation.isPending || chooseMutation.isPending || clearMutation.isPending;

  function translateCode(code: string): string {
    const key = `errors.${code}`;
    const translated = t(key);
    return translated === key ? t("admin.hr_sync.invalid_unknown") : translated;
  }

  function renderPreferred(record: HrPreferredRecordDTO, testId: string) {
    return (
      <div
        className="flex flex-wrap items-center gap-2 rounded bg-indigo-50 dark:bg-indigo-950/40 text-indigo-900 dark:text-indigo-200 px-2 py-1 text-xs"
        data-testid={testId}
      >
        <span className="font-medium">{t("admin.hr_sync.remembered_choice")}</span>
        <span dir="ltr">{record.key_type}: {record.key_value}</span>
        {record.chosen_by_name && <span>{t("admin.hr_sync.remembered_by", { name: record.chosen_by_name })}</span>}
        <span>{formatDateTime(record.chosen_at)}</span>
        <button
          type="button"
          data-testid={`hr-identity-clear-${record.personal_number}`}
          className="px-2 py-0.5 rounded border border-indigo-300 dark:border-indigo-700 disabled:opacity-50"
          disabled={busy}
          onClick={() => clearMutation.mutate(record.personal_number)}
        >
          {t("admin.hr_sync.clear_choice")}
        </button>
      </div>
    );
  }

  function renderCandidate(conflict: HrIdentityConflictDTO, candidate: HrIdentityCandidateDTO) {
    const entries = payloadEntries(candidate.payload);
    return (
      <div
        key={candidate.index}
        className={
          "rounded border p-2 space-y-2 text-xs " +
          (candidate.is_applied
            ? "border-indigo-500 bg-indigo-50/60 dark:bg-indigo-950/30"
            : "border-gray-300 dark:border-gray-600")
        }
        data-testid={`hr-identity-candidate-${conflict.id}-${candidate.index}`}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="font-semibold">{t("admin.hr_sync.record_n", { n: candidate.index + 1 })}</span>
          {candidate.is_applied && (
            <span
              className="rounded bg-indigo-600 text-white px-1.5 py-0.5"
              data-testid={`hr-identity-applied-${conflict.id}-${candidate.index}`}
            >
              {t("admin.hr_sync.applied_record")}
            </span>
          )}
        </div>
        <dl className="space-y-0.5">
          {entries.map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <dt className="text-gray-500 dark:text-gray-400 shrink-0">{key}</dt>
              <dd dir="auto" className="break-all">{value}</dd>
            </div>
          ))}
        </dl>
        {candidate.choosable ? (
          <button
            type="button"
            data-testid={`hr-identity-choose-${conflict.id}-${candidate.index}`}
            className="px-2 py-1 rounded bg-indigo-600 text-white disabled:opacity-50"
            disabled={busy || conflict.status === "resolved"}
            onClick={() => chooseMutation.mutate({ id: conflict.id, index: candidate.index })}
          >
            {t("admin.hr_sync.choose_remember")}
          </button>
        ) : (
          <div className="text-amber-700 dark:text-amber-400" data-testid={`hr-identity-invalid-${conflict.id}-${candidate.index}`}>
            {t("admin.hr_sync.cannot_choose")}: {translateCode(candidate.invalid_reason ?? "unknown")}
          </div>
        )}
      </div>
    );
  }

  function renderConflict(conflict: HrIdentityConflictDTO) {
    const kindKey = `admin.hr_sync.kind_${conflict.kind}`;
    const reasonKey = `admin.hr_sync.reason_${conflict.reason}`;
    const kind = t(kindKey);
    const reason = t(reasonKey);
    return (
      <li
        key={conflict.id}
        className="rounded border border-amber-300 dark:border-amber-700 bg-amber-50/60 dark:bg-amber-950/20 p-3 space-y-2"
        data-testid={`hr-identity-conflict-${conflict.id}`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-semibold">
            {t("admin.hr_sync.personal_number")} <span dir="ltr">{conflict.personal_number}</span>
            {" · "}
            {kind === kindKey ? t("admin.hr_sync.kind_unknown") : kind}
          </div>
          {conflict.status === "open" && (
            <button
              type="button"
              data-testid={`hr-identity-acknowledge-${conflict.id}`}
              className="px-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600 disabled:opacity-50"
              disabled={busy}
              onClick={() => acknowledgeMutation.mutate(conflict.id)}
            >
              {t("admin.hr_sync.acknowledge")}
            </button>
          )}
        </div>
        <div className="text-xs text-gray-600 dark:text-gray-300">
          {reason === reasonKey ? t("admin.hr_sync.reason_unknown") : reason}
        </div>
        {conflict.colliding_soldiers.length > 0 && (
          <div className="text-xs">
            {t("admin.hr_sync.colliding_soldiers")}:{" "}
            {conflict.colliding_soldiers
              .map((s) => [s.full_name, s.personal_number].filter(Boolean).join(" · "))
              .join(", ")}
          </div>
        )}
        {conflict.preferred_record && renderPreferred(conflict.preferred_record, `hr-identity-remembered-${conflict.id}`)}
        <div className="grid gap-2 md:grid-cols-2" data-testid={`hr-identity-candidates-${conflict.id}`}>
          {conflict.candidates.map((c) => renderCandidate(conflict, c))}
        </div>
      </li>
    );
  }

  const conflicts = conflictsQuery.data?.items ?? [];
  // A remembered choice already shown inside its open conflict is not repeated below.
  const shownInConflicts = new Set(conflicts.filter((c) => c.preferred_record).map((c) => c.personal_number));
  const preferred = (preferredQuery.data?.items ?? []).filter((p) => !shownInConflicts.has(p.personal_number));

  return (
    <div className="space-y-3" data-testid="hr-identity-conflicts-section">
      {conflictsQuery.isError ? (
        <div className="text-sm text-red-600 dark:text-red-400" data-testid="hr-identity-conflicts-error">
          {t("admin.hr_sync.load_error")}
        </div>
      ) : conflictsQuery.isLoading ? (
        <div className="text-sm text-gray-500" data-testid="hr-identity-conflicts-loading">
          {t("admin.hr_sync.loading")}
        </div>
      ) : conflicts.length === 0 ? (
        <div className="text-sm text-gray-500" data-testid="hr-identity-conflicts-empty">
          {t("admin.hr_sync.identity_conflicts_empty")}
        </div>
      ) : (
        <ul className="space-y-3">{conflicts.map(renderConflict)}</ul>
      )}

      {actionError && (
        <div className="text-sm text-red-600 dark:text-red-400" role="alert" data-testid="hr-identity-action-error">
          {translateApiError(actionError, t, t("admin.hr_sync.action_error"))}
        </div>
      )}

      {preferred.length > 0 && (
        <div className="space-y-1" data-testid="hr-identity-preferred-list">
          <h4 className="text-xs font-semibold text-gray-600 dark:text-gray-300">{t("admin.hr_sync.remembered_choices")}</h4>
          {preferred.map((p) => (
            <div key={p.personal_number} className="flex flex-wrap items-center gap-2 text-xs">
              <span dir="ltr">{p.personal_number}</span>
              {renderPreferred(p, `hr-identity-preferred-${p.personal_number}`)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
