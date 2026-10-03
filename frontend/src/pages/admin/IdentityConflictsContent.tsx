import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { dismissIdentityConflict, listIdentityConflicts, resolveIdentityConflict } from "../../api/identityConflicts";
import type { IdentityConflictCandidateDTO, IdentityConflictDTO } from "../../api/identityConflicts";
import { translateApiError } from "../../utils/translateApiError";

const QUERY_KEY = ["admin-identity-conflicts"];

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function IdentityConflictsContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [reasons, setReasons] = useState<Record<string, string>>({});

  const query = useQuery({ queryKey: QUERY_KEY, queryFn: () => listIdentityConflicts("open") });

  const refresh = () => void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
  const resolveMutation = useMutation({
    mutationFn: ({ id, soldierId }: { id: string; soldierId: string }) => resolveIdentityConflict(id, soldierId),
    onSuccess: refresh,
  });
  const dismissMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => dismissIdentityConflict(id, reason),
    onSuccess: refresh,
  });
  const actionError = resolveMutation.error ?? dismissMutation.error;
  const busy = resolveMutation.isPending || dismissMutation.isPending;

  function sourceLabel(source: string): string {
    const key = `admin.identity_conflicts.source_${source}`;
    const label = t(key);
    return label === key ? t("admin.identity_conflicts.source_unknown") : label;
  }

  function matchedLabel(field: string): string {
    const key = `admin.identity_conflicts.matched_${field}`;
    const label = t(key);
    return label === key ? field : label;
  }

  function renderCandidate(conflict: IdentityConflictDTO, c: IdentityConflictCandidateDTO) {
    return (
      <li
        key={c.soldier_id}
        className="flex flex-wrap items-center justify-between gap-2 rounded border border-gray-200 dark:border-gray-600 p-2 text-sm"
        data-testid={`identity-candidate-${conflict.id}-${c.soldier_id}`}
      >
        <div className="space-y-0.5">
          <div>
            {[c.full_name, c.personal_number].filter(Boolean).join(" · ") || "—"}
            {!c.active && (
              <span
                className="ms-2 rounded bg-gray-200 dark:bg-gray-600 px-1.5 py-0.5 text-xs"
                data-testid={`identity-inactive-${conflict.id}-${c.soldier_id}`}
              >
                {t("admin.identity_conflicts.inactive")}
              </span>
            )}
          </div>
          <div className="text-xs text-gray-500 dark:text-gray-400">
            <span dir="ltr">{c.email_masked ?? "—"}</span>
            {c.matched_fields.length > 0 && (
              <> · {t("admin.identity_conflicts.matched_on")}: {c.matched_fields.map(matchedLabel).join(", ")}</>
            )}
          </div>
        </div>
        <button
          type="button"
          data-testid={`identity-resolve-${conflict.id}-${c.soldier_id}`}
          className="px-2 py-1 rounded bg-indigo-600 text-white text-sm disabled:opacity-50"
          disabled={busy}
          onClick={() => resolveMutation.mutate({ id: conflict.id, soldierId: c.soldier_id })}
        >
          {t("admin.identity_conflicts.resolve")}
        </button>
      </li>
    );
  }

  function renderConflict(conflict: IdentityConflictDTO) {
    const reason = (reasons[conflict.id] ?? "").trim();
    return (
      <li
        key={conflict.id}
        className="rounded border border-amber-300 dark:border-amber-700 bg-amber-50/60 dark:bg-amber-950/20 p-3 space-y-2"
        data-testid={`identity-conflict-${conflict.id}`}
      >
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="font-semibold">{sourceLabel(conflict.source)}</span>
          <span>
            {t("admin.identity_conflicts.ad_username")}: <span dir="ltr" className="font-mono">{conflict.ad_username}</span>
          </span>
          <span className="text-gray-500 dark:text-gray-400">
            {t("admin.identity_conflicts.created_at")}: {formatDateTime(conflict.created_at)}
          </span>
        </div>
        <h4 className="text-xs font-semibold text-gray-600 dark:text-gray-300">{t("admin.identity_conflicts.candidates")}</h4>
        <ul className="space-y-1">{conflict.candidates.map((c) => renderCandidate(conflict, c))}</ul>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="text"
            maxLength={500}
            value={reasons[conflict.id] ?? ""}
            placeholder={t("admin.identity_conflicts.dismiss_reason")}
            data-testid={`identity-dismiss-reason-${conflict.id}`}
            className="flex-1 min-w-[12rem] rounded border border-gray-300 dark:border-gray-600 dark:bg-gray-700 p-1.5 text-sm"
            onChange={(e) => setReasons((prev) => ({ ...prev, [conflict.id]: e.target.value }))}
          />
          <button
            type="button"
            data-testid={`identity-dismiss-submit-${conflict.id}`}
            className="px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-sm disabled:opacity-50"
            disabled={busy || reason.length === 0}
            onClick={() => dismissMutation.mutate({ id: conflict.id, reason })}
          >
            {t("admin.identity_conflicts.dismiss_confirm")}
          </button>
        </div>
      </li>
    );
  }

  const items = query.data?.items ?? [];

  return (
    <div className="space-y-4" data-testid="identity-conflicts-content">
      <div>
        <h3 className="text-sm font-semibold">{t("admin.identity_conflicts.title")}</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400">{t("admin.identity_conflicts.hint")}</p>
      </div>
      {query.isError ? (
        <div className="text-sm text-red-600 dark:text-red-400" data-testid="identity-conflicts-error">
          {t("admin.identity_conflicts.load_error")}
        </div>
      ) : query.isLoading ? (
        <div className="text-sm text-gray-500" data-testid="identity-conflicts-loading">
          {t("admin.identity_conflicts.loading")}
        </div>
      ) : items.length === 0 ? (
        <div className="text-sm text-gray-500" data-testid="identity-conflicts-empty">
          {t("admin.identity_conflicts.empty")}
        </div>
      ) : (
        <ul className="space-y-3">{items.map(renderConflict)}</ul>
      )}
      {actionError && (
        <div className="text-sm text-red-600 dark:text-red-400" role="alert" data-testid="identity-conflicts-action-error">
          {translateApiError(actionError, t, t("admin.identity_conflicts.action_error"))}
        </div>
      )}
    </div>
  );
}
