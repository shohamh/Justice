import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import DateInput from "../components/DateInput";
import Combobox from "../components/Combobox";
import TabBar from "../components/TabBar";
import { DaysBadge } from "../components/DaysBadge";
import AuditHistoryBlock from "../components/AuditHistoryBlock";
import { MySwapCard } from "../components/MySwapCard";
import { useAuth } from "../auth/AuthContext";
import { listExemptions } from "../api/exemptions";
import { ExemptionType, listExemptionTypes } from "../api/dutyConfig";
import {
  cancelConstraint,
  getRemainingConstraintDays,
  listMyConstraints,
  submitConstraint,
} from "../api/constraints";
import { formatDate, isDateInPast, isDateRangeValid, todayIso } from "../utils/formatDate";
import { translateApiError } from "../utils/translateApiError";
import { validateFileSignature, PDF_IMAGE_SIGNATURES } from "../utils/fileValidation";
import { formatFieldUpdateValue } from "../utils/formatFieldUpdateValue";
import { RANGE_TYPE_LABELS } from "../utils/rangeLabels";
import {
  listMyExemptionRequests,
  submitExemptionRequest,
} from "../api/exemptions";
import { listFieldUpdates } from "../api/soldiers";
import { listMySwaps } from "../api/swaps";
import {
  getMyEnrollment,
  getRequestsUnseenCount,
  listMyHierarchyTransfers,
  listMyRangeExcusalRequests,
  markRequestsSeen,
} from "../api/myRequests";

function waitingOnLabel(
  status: string,
  nearestCommander: { id: string; name: string } | null,
  nearestDutyManager: { id: string; name: string } | null,
): string | null {
  if (status === "pending_commander" || status === "pending") {
    return nearestCommander?.name ?? null;
  }
  if (status === "pending_duty_manager") {
    return nearestDutyManager?.name ?? null;
  }
  return null;
}

type RequestsTab = "new" | "existing";

const VALID_TABS: RequestsTab[] = ["new", "existing"];

/** How often the unseen-decisions badge polls, matching UnifiedNav's badge
 * refresh cadence. */
const UNSEEN_COUNT_POLL_MS = 30_000;

export default function MyRequestsPage() {
  const { t } = useTranslation();
  const { user, enrollmentPending } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const rawTab = searchParams.get("tab") as RequestsTab | null;
  const tab: RequestsTab = rawTab && VALID_TABS.includes(rawTab) ? rawTab : "new";

  function setTab(next: RequestsTab) {
    setSearchParams((prev) => { prev.set("tab", next); return prev; }, { replace: true });
  }

  const [constraintFormOpen, setConstraintFormOpen] = useState(false);
  const [erFormOpen, setErFormOpen] = useState(false);

  // Personal-constraint form state
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Exemption request form state
  const [erTypeId, setErTypeId] = useState("");
  const [erStart, setErStart] = useState("");
  const [erEnd, setErEnd] = useState("");
  const [erReason, setErReason] = useState("");
  const [erError, setErError] = useState<string | null>(null);
  const [erSubmitting, setErSubmitting] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadSizeErrors, setUploadSizeErrors] = useState<string[]>([]);
  const [erMedical, setErMedical] = useState(false);
  const [erPermanent, setErPermanent] = useState(false);

  const MAX_FILE_BYTES = 10 * 1024 * 1024; // 10 MB

  function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  const queryClient = useQueryClient();

  const constraintsQuery = useQuery({ queryKey: queryKeys.myConstraints(), queryFn: listMyConstraints });
  const items = constraintsQuery.data ?? [];

  const remainingQuery = useQuery({ queryKey: queryKeys.remainingConstraintDays(), queryFn: getRemainingConstraintDays });
  const remaining = remainingQuery.data;

  const exemptionRequestsQuery = useQuery({ queryKey: queryKeys.myExemptionRequests(), queryFn: listMyExemptionRequests });
  const exemptionRequests = exemptionRequestsQuery.data ?? [];

  const exemptionTypesQuery = useQuery({
    queryKey: queryKeys.exemptionTypes(),
    queryFn: () => listExemptionTypes().catch(() => [] as ExemptionType[]),
  });
  const exemptionTypes = exemptionTypesQuery.data ?? [];

  // Active exemptions power the compact "currently in force" panel (the
  // detailed list lives in ProfilePage's ExemptionsPanel).
  const exemptionsQuery = useQuery({
    queryKey: user ? queryKeys.myExemptions(user.id) : ["exemptions", "mine", "anonymous"],
    queryFn: () => listExemptions(user!.id),
    enabled: !!user,
  });
  const exemptions = exemptionsQuery.data ?? [];

  const unseenCountQuery = useQuery({
    queryKey: queryKeys.requestsUnseenCount(),
    queryFn: getRequestsUnseenCount,
    refetchInterval: UNSEEN_COUNT_POLL_MS,
  });
  const unseenCount = unseenCountQuery.data?.count ?? 0;

  const fieldUpdatesQuery = useQuery({
    queryKey: user ? queryKeys.fieldUpdates(user.id) : ["soldiers", "fieldUpdates", "anonymous"],
    queryFn: () => listFieldUpdates(user!.id),
    enabled: !!user,
  });
  const fieldUpdates = fieldUpdatesQuery.data ?? [];

  const mySwapsQuery = useQuery({ queryKey: queryKeys.mySwaps(), queryFn: listMySwaps });
  const inProcessSwaps = (mySwapsQuery.data ?? [])
    .filter((s) => s.status !== "cancelled")
    .sort((a, b) => b.created_at.localeCompare(a.created_at));

  const transfersQuery = useQuery({ queryKey: queryKeys.myHierarchyTransfers(), queryFn: listMyHierarchyTransfers });
  const transfers = transfersQuery.data ?? [];

  const enrollmentQuery = useQuery({ queryKey: queryKeys.myEnrollment(), queryFn: getMyEnrollment });
  const enrollmentRequest = enrollmentQuery.data?.request ?? null;

  const rangeExcusalsQuery = useQuery({ queryKey: queryKeys.myRangeExcusalRequests(), queryFn: listMyRangeExcusalRequests });
  const rangeExcusals = rangeExcusalsQuery.data ?? [];

  // Opening the existing-requests tab marks everything as seen so the badge
  // clears; deep-linking straight to ?tab=existing counts as opening it.
  useEffect(() => {
    if (tab !== "existing") return;
    void (async () => {
      await markRequestsSeen();
      await queryClient.invalidateQueries({ queryKey: queryKeys.requestsUnseenCount() });
    })();
  }, [tab, queryClient]);

  const selectedExemptionType = exemptionTypes.find(et => et.id === erTypeId);
  const isMedical = erMedical || (selectedExemptionType?.is_medical ?? false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (isDateInPast(start)) {
      setError(t("errors.start_date_in_past"));
      return;
    }
    if (!isDateRangeValid(start, end)) {
      setError(t("errors.date_range_invalid"));
      return;
    }
    setSubmitting(true);
    try {
      await submitConstraint({
        start_date: start,
        end_date: end,
        reason,
      });
      setStart(""); setEnd(""); setReason("");
      await queryClient.invalidateQueries({ queryKey: queryKeys.myConstraints() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.remainingConstraintDays() });
    } catch (err: unknown) {
      setError(translateApiError(err, t));
    } finally {
      setSubmitting(false);
    }
  }

  async function onCancel(id: string) {
    if (!confirm(t("my_requests.cancel") + "?")) return;
    await cancelConstraint(id);
    await queryClient.invalidateQueries({ queryKey: queryKeys.myConstraints() });
    await queryClient.invalidateQueries({ queryKey: queryKeys.remainingConstraintDays() });
  }

  async function onErSubmit(e: FormEvent) {
    e.preventDefault();
    setErError(null);
    if (!erPermanent && !isDateRangeValid(erStart, erEnd)) {
      setErError(t("errors.date_range_invalid"));
      return;
    }
    setErSubmitting(true);
    try {
      await submitExemptionRequest(
        {
          exemption_type_id: erTypeId,
          start_date: erPermanent ? null : erStart,
          end_date: erPermanent ? null : (erEnd || null),
          reason: erReason || null,
        },
        uploadFiles,
      );
      setErTypeId(""); setErStart(""); setErEnd(""); setErReason("");
      setUploadFiles([]); setUploadSizeErrors([]); setErMedical(false); setErPermanent(false);
      await queryClient.invalidateQueries({ queryKey: queryKeys.myExemptionRequests() });
    } catch (err: unknown) {
      setErError(translateApiError(err, t));
    } finally {
      setErSubmitting(false);
    }
  }

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: "text-amber-600 dark:text-amber-400",
      pending_commander: "text-amber-600 dark:text-amber-400",
      pending_duty_manager: "text-amber-600 dark:text-amber-400",
      approved: "text-green-600 dark:text-green-400",
      rejected: "text-red-600 dark:text-red-400",
    };
    return <span className={colors[status] ?? ""}>{t(`my_requests.${status}`)}</span>;
  };

  // Compact panel: what currently exempts or constrains the soldier, date-wise.
  const today = todayIso();
  const activeConstraints = items.filter(
    (c) => c.status === "approved" && c.start_date <= today && (!c.end_date || c.end_date >= today),
  );
  const activeExemptions = exemptions.filter(
    (ex) => ex.start_date <= today && (!ex.end_date || ex.end_date >= today),
  );

  const enrollmentPendingBanner = (
    <div className="rounded border border-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 px-3 py-2 text-sm text-yellow-800 dark:text-yellow-200">
      בקשת הקליטה שלך למסגרת עדיין ממתינה לאישור — לא ניתן להגיש בקשות חדשות עד לאישור.
    </div>
  );

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-6 dark:bg-gray-800">

        <TabBar
          tabs={[t("my_requests.tab_new"), t("my_requests.tab_existing")]}
          active={VALID_TABS.indexOf(tab)}
          onChange={(i) => setTab(VALID_TABS[i] ?? "new")}
          badges={[null, unseenCount > 0 ? unseenCount : null]}
        />

        {tab === "new" && (
          <div className="space-y-4" data-testid="new-requests-tab">
            {enrollmentPending && enrollmentPendingBanner}

            {/* Personal-constraint request card */}
            <div className="border dark:border-gray-600 rounded-lg overflow-hidden">
              <button
                type="button"
                onClick={() => setConstraintFormOpen((v) => !v)}
                aria-expanded={constraintFormOpen}
                data-testid="constraint-form-toggle"
                className="w-full flex items-center justify-between px-4 py-3 text-right bg-gray-50 dark:bg-gray-700/40 hover:bg-gray-100 dark:hover:bg-gray-700"
              >
                <span className="font-medium">{t("my_requests.card_constraint")}</span>
                <span aria-hidden>{constraintFormOpen ? "▲" : "▼"}</span>
              </button>
              {constraintFormOpen && (
                <div className="p-4 space-y-3 border-t dark:border-gray-600" data-testid="constraint-form-card">
                  {error && <div className="text-red-600 text-sm" data-testid="req-error">{error}</div>}
                  {remaining && (
                    <p className="text-sm text-gray-600 dark:text-gray-400" data-testid="constraints-remaining">
                      {t("constraints.remaining_summary", {
                        remaining: remaining.remaining_days,
                        cap: remaining.cap_days,
                        until: formatDate(remaining.period_end),
                      })}
                    </p>
                  )}
                  <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2">
                    <div className="flex flex-col gap-1">
                      <label className="text-xs text-gray-500 dark:text-gray-400">{t("my_requests.start_date")}</label>
                      <DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={start} onChange={(iso) => setStart(iso)} min={todayIso()} max={end || undefined} required data-testid="req-start" />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-xs text-gray-500 dark:text-gray-400">{t("my_requests.end_date")}</label>
                      <DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={end} onChange={(iso) => setEnd(iso)} min={start || undefined} required data-testid="req-end" />
                    </div>
                    <div className="flex flex-col gap-1 flex-1 min-w-32">
                      <label className="text-xs text-gray-500 dark:text-gray-400">{t("my_requests.reason")}</label>
                      <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 w-full" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("my_requests.reason")} required data-testid="req-reason" />
                    </div>
                    <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded disabled:opacity-50" disabled={submitting || enrollmentPending || isDateInPast(start) || !isDateRangeValid(start, end)} data-testid="req-submit">
                      {submitting ? t("app.loading") : t("my_requests.send")}
                    </button>
                  </form>
                </div>
              )}
            </div>

            {/* Exemption request card */}
            <div className="border dark:border-gray-600 rounded-lg overflow-hidden">
              <button
                type="button"
                onClick={() => setErFormOpen((v) => !v)}
                aria-expanded={erFormOpen}
                data-testid="er-form-toggle"
                className="w-full flex items-center justify-between px-4 py-3 text-right bg-gray-50 dark:bg-gray-700/40 hover:bg-gray-100 dark:hover:bg-gray-700"
              >
                <span className="font-medium">{t("my_requests.card_exemption")}</span>
                <span aria-hidden>{erFormOpen ? "▲" : "▼"}</span>
              </button>
              {erFormOpen && (
                <div className="p-4 space-y-3 border-t dark:border-gray-600" data-testid="er-form-card" dir="rtl">
                  {erError && <div className="text-red-600 dark:text-red-400 text-sm" data-testid="er-error">{erError}</div>}
                  <form onSubmit={onErSubmit} className="space-y-3">
                    <div className="flex flex-wrap gap-2 items-end">
                      <div className="flex flex-col gap-1">
                        <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.type")}</label>
                        <Combobox
                          items={exemptionTypes.map(et => ({ id: et.id, name: `${et.name}${et.is_medical ? " 🏥" : ""}` }))}
                          value={erTypeId}
                          onChange={(typeId) => {
                            setErTypeId(typeId);
                            setUploadFiles([]); setUploadSizeErrors([]);
                            const type = exemptionTypes.find(et => et.id === typeId);
                            setErMedical(type?.is_medical ?? false);
                          }}
                          placeholder={`— ${t("exemption_requests.type")} —`}
                          testId="er-type"
                        />
                      </div>
                      <div className="flex flex-col gap-1">
                        <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.start_date")}</label>
                        <DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={erPermanent ? "" : erStart} onChange={(iso) => setErStart(iso)} max={erEnd || undefined} disabled={erPermanent} required={!erPermanent} data-testid="er-start" />
                      </div>
                      <div className="flex flex-col gap-1">
                        <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.end_date")}</label>
                        <DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={erPermanent ? "" : erEnd} onChange={(iso) => setErEnd(iso)} min={erStart || undefined} disabled={erPermanent} required={!erPermanent} data-testid="er-end" />
                        <label className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400 mt-1">
                          <input
                            type="checkbox"
                            checked={erPermanent}
                            onChange={(e) => {
                              setErPermanent(e.target.checked);
                              if (e.target.checked) { setErStart(""); setErEnd(""); }
                            }}
                            data-testid="er-permanent"
                          />
                          {t("exemption_requests.permanent")}
                        </label>
                      </div>
                      <div className="flex flex-col gap-1 flex-1 min-w-32">
                        <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.reason")}</label>
                        <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 w-full" value={erReason} onChange={(e) => setErReason(e.target.value)} placeholder={t("exemption_requests.reason")} data-testid="er-reason" />
                      </div>
                    </div>

                    {/* Medical checkbox */}
                    <label className="flex items-center gap-2 cursor-pointer w-fit" data-testid="er-medical-check">
                      <input
                        type="checkbox"
                        checked={erMedical}
                        onChange={(e) => { setErMedical(e.target.checked); setUploadFiles([]); setUploadSizeErrors([]); }}
                        className="w-4 h-4 accent-blue-600"
                      />
                      <span className="text-sm font-medium text-blue-700 dark:text-blue-300">
                        🏥 {t("duty_config.medical")}
                      </span>
                    </label>

                    {/* File upload — always available, required for medical types */}
                    <div className={`rounded-lg border-2 border-dashed p-4 space-y-2 ${
                      isMedical
                        ? "border-blue-300 dark:border-blue-700 bg-blue-50 dark:bg-blue-950"
                        : "border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700"
                    }`}>
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{isMedical ? "🏥" : "📎"}</span>
                        <div>
                          <p className={`text-sm font-medium ${isMedical ? "text-blue-800 dark:text-blue-200" : "text-gray-700 dark:text-gray-300"}`}>
                            {isMedical ? t("exemption_requests.upload_required") : t("exemption_requests.upload_optional")}
                          </p>
                          <p className={`text-xs ${isMedical ? "text-blue-600 dark:text-blue-400" : "text-gray-500 dark:text-gray-400"}`}>
                            {t("exemption_requests.upload_hint")}
                          </p>
                        </div>
                      </div>
                      <label className={`flex flex-col items-center justify-center gap-2 cursor-pointer rounded-lg border p-3 transition-colors ${
                        isMedical
                          ? "border-blue-200 dark:border-blue-700 bg-white dark:bg-gray-800 hover:bg-blue-50 dark:hover:bg-gray-700"
                          : "border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700"
                      }`}>
                        <span className="text-2xl">📎</span>
                        <span className={`text-sm font-medium ${isMedical ? "text-blue-700 dark:text-blue-300" : "text-gray-600 dark:text-gray-300"}`}>
                          {uploadFiles.length > 0
                            ? `${uploadFiles.length} ${uploadFiles.length === 1 ? "קובץ נבחר" : "קבצים נבחרו"}`
                            : "בחר קבצים"}
                        </span>
                        <span className="text-xs text-gray-400">PDF, JPG, PNG, GIF · {t("exemption_requests.max_file_size")}</span>
                        <input
                          type="file"
                          multiple
                          accept=".pdf,image/*"
                          className="hidden"
                          onChange={async e => {
                            const picked = Array.from(e.target.files ?? []);
                            e.target.value = "";
                            const withinSize = picked.filter(f => f.size <= MAX_FILE_BYTES);
                            const oversized = picked.filter(f => f.size > MAX_FILE_BYTES).map(f => f.name);
                            const signatureChecks = await Promise.all(
                              withinSize.map(f => validateFileSignature(f, PDF_IMAGE_SIGNATURES)),
                            );
                            const valid = withinSize.filter((_, i) => signatureChecks[i]);
                            const invalidType = withinSize.filter((_, i) => !signatureChecks[i]).map(f => f.name);
                            setUploadFiles(prev => {
                              const merged = [...prev, ...valid.filter(v => !prev.some(p => p.name === v.name))];
                              return merged;
                            });
                            setUploadSizeErrors([...oversized, ...invalidType]);
                          }}
                          data-testid="er-files"
                        />
                      </label>
                      {uploadSizeErrors.length > 0 && (
                        <div className="rounded p-2 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800">
                          <p className="text-xs font-medium text-red-700 dark:text-red-300">{t("exemption_requests.file_too_large")}</p>
                          <ul className="text-xs text-red-600 dark:text-red-400 mt-0.5 list-disc list-inside">
                            {uploadSizeErrors.map(name => <li key={name}>{name}</li>)}
                          </ul>
                        </div>
                      )}
                      {uploadFiles.length > 0 && (
                        <ul className="text-xs space-y-0.5">
                          {uploadFiles.map((f, i) => (
                            <li key={i} className={`flex items-center gap-1 ${isMedical ? "text-blue-700 dark:text-blue-300" : "text-gray-600 dark:text-gray-300"}`}>
                              <span>📄</span>
                              <span className="truncate max-w-48">{f.name}</span>
                              <span className="text-gray-400 dark:text-gray-500 shrink-0">({formatBytes(f.size)})</span>
                              <button
                                type="button"
                                className="text-red-400 hover:text-red-600 mr-1 shrink-0"
                                onClick={() => setUploadFiles(prev => prev.filter((_, j) => j !== i))}
                              >✕</button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <button
                      type="submit"
                      className="bg-indigo-600 text-white px-4 py-1.5 rounded disabled:opacity-50 text-sm"
                      disabled={erSubmitting || !erTypeId || (isMedical && uploadFiles.length === 0) || enrollmentPending || (!erPermanent && (!isDateRangeValid(erStart, erEnd) || !erStart || !erEnd))}
                      data-testid="er-submit"
                    >
                      {erSubmitting ? t("app.loading") : t("exemption_requests.send")}
                    </button>
                    {isMedical && uploadFiles.length === 0 && (
                      <p className="text-xs text-amber-600 dark:text-amber-400">{t("exemption_requests.upload_required_hint")}</p>
                    )}
                  </form>
                </div>
              )}
            </div>
          </div>
        )}

        {tab === "existing" && (
          <div className="space-y-6" data-testid="existing-requests-tab">
            {(activeConstraints.length > 0 || activeExemptions.length > 0) && (
              <section className="rounded-lg border border-indigo-200 dark:border-indigo-900 bg-indigo-50 dark:bg-indigo-950 p-4 space-y-2" data-testid="active-panel">
                <h3 className="font-medium text-indigo-800 dark:text-indigo-200">{t("my_requests.active_now")}</h3>
                <ul className="space-y-1.5 text-sm">
                  {activeConstraints.map((c) => (
                    <li key={c.id} className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300">{t("my_requests.section_constraints")}</span>
                      <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                      <DaysBadge start={c.start_date} end={c.end_date} />
                      {c.reason && <span className="text-gray-700 dark:text-gray-300">{c.reason}</span>}
                    </li>
                  ))}
                  {activeExemptions.map((ex) => {
                    const exemptType = exemptionTypes.find((et) => et.id === ex.exemption_type_id);
                    return (
                      <li key={ex.id} className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300">{t("my_requests.my_exemptions")}</span>
                        <span className="text-gray-700 dark:text-gray-200">{exemptType?.name ?? ex.exemption_type_id}</span>
                        <span dir="ltr" className="text-gray-700 dark:text-gray-200">{ex.start_date} → {ex.end_date ?? t("exemptions.forever")}</span>
                        <DaysBadge start={ex.start_date} end={ex.end_date} />
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}

            {/* Personal constraints */}
            <section className="space-y-3" data-testid="group-constraints">
              <h3 className="font-medium">{t("my_requests.section_constraints")}</h3>
              {items.length === 0 && <p className="text-sm text-gray-500" data-testid="no-constraints">{t("my_requests.none")}</p>}

              {items.filter((c) => c.status === "pending" || c.status === "pending_commander" || c.status === "pending_duty_manager").length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-1.5">{t("my_requests.pending_constraints")}</h4>
                  <ul className="space-y-2 text-sm" data-testid="constraints-list">
                    {items.filter((c) => c.status === "pending" || c.status === "pending_commander" || c.status === "pending_duty_manager").map((c) => (
                      <li key={c.id} className="border dark:border-gray-600 rounded-lg p-3 bg-white dark:bg-gray-800 flex flex-col gap-2" data-testid={`constraint-row-${c.id}`}>
                        <div className="flex items-center gap-3">
                          <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                          <DaysBadge start={c.start_date} end={c.end_date} />
                          <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                          {statusBadge(c.status)}
                          {(() => {
                            const waitingOn = waitingOnLabel(c.status, c.nearest_commander, c.nearest_duty_manager);
                            return waitingOn ? (
                              <span className="text-xs text-gray-500 dark:text-gray-400" data-testid={`constraint-waiting-on-${c.id}`}>
                                ממתין ל: {waitingOn}
                              </span>
                            ) : null;
                          })()}
                          {/* Either pending step is cancelable — see cancel_constraint
                              in backend/app/services/constraints.py. Once approved or
                              rejected it's final, so hide the button to avoid a call
                              that would 400. */}
                          {(c.status === "pending" || c.status === "pending_commander" || c.status === "pending_duty_manager") && (
                            <button className="text-red-500 text-xs" onClick={() => onCancel(c.id)} data-testid={`cancel-${c.id}`}>
                              {t("my_requests.cancel")}
                            </button>
                          )}
                        </div>
                        <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {items.filter((c) => c.status === "approved").length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-1.5">{t("my_requests.approved_constraints")}</h4>
                  <ul className="space-y-2 text-sm">
                    {items.filter((c) => c.status === "approved").map((c) => (
                      <li key={c.id} className="border border-green-200 dark:border-green-800 rounded-lg p-3 bg-green-50 dark:bg-green-950" data-testid={`constraint-row-${c.id}`}>
                        <div className="flex items-center gap-3">
                          <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                          <DaysBadge start={c.start_date} end={c.end_date} />
                          <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                          {statusBadge(c.status)}
                        </div>
                        <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {items.filter((c) => c.status === "rejected").length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-1.5">{t("my_requests.rejected_constraints")}</h4>
                  <ul className="space-y-2 text-sm">
                    {items.filter((c) => c.status === "rejected").map((c) => (
                      <li key={c.id} className="border border-red-200 dark:border-red-800 rounded-lg p-3 bg-red-50 dark:bg-red-950" data-testid={`constraint-row-${c.id}`}>
                        <div className="flex items-center gap-3">
                          <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                          <DaysBadge start={c.start_date} end={c.end_date} />
                          <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                          {statusBadge(c.status)}
                        </div>
                        {c.decision_note && (
                          <p className="text-xs text-red-700 dark:text-red-400 mt-1">{t("my_requests.decision_note")}: {c.decision_note}</p>
                        )}
                        <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>

            {/* Exemption requests */}
            <section className="space-y-2" data-testid="group-exemption-requests">
              <h3 className="font-medium">{t("exemption_requests.title")}</h3>
              {exemptionRequests.length === 0 && <p className="text-sm text-gray-500">{t("exemption_requests.none")}</p>}
              <ul className="text-sm space-y-1" data-testid="er-list">
                {exemptionRequests.map((er) => (
                  <li key={er.id} className="flex flex-col gap-0.5">
                    <div className="flex items-center gap-3">
                      <span>{exemptionTypes.find((et) => et.id === er.exemption_type_id)?.name ?? er.exemption_type_id}</span>
                      <span dir="ltr">{er.start_date ?? t("exemption_requests.start_date_pending_approval")} → {er.end_date ?? t("exemptions.forever")}</span>
                      {er.start_date && <DaysBadge start={er.start_date} end={er.end_date} />}
                      {er.reason && <span className="text-gray-700 dark:text-gray-300">{er.reason}</span>}
                      <span className={`text-xs ${
                        er.status === "approved" ? "text-green-600 dark:text-green-400" :
                        er.status === "rejected" ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"
                      }`}>{t(`exemption_requests.${er.status}`)}</span>
                      {(() => {
                        const waitingOn = waitingOnLabel(er.status, er.nearest_commander, er.nearest_duty_manager);
                        return waitingOn ? (
                          <span className="text-xs text-gray-500 dark:text-gray-400" data-testid={`er-waiting-on-${er.id}`}>
                            ממתין ל: {waitingOn}
                          </span>
                        ) : null;
                      })()}
                    </div>
                    {er.status === "rejected" && er.decision_note && (
                      <p className="text-xs text-red-700 dark:text-red-400">{t("my_requests.decision_note")}: {er.decision_note}</p>
                    )}
                  </li>
                ))}
              </ul>
            </section>

            {/* Profile field updates */}
            <section className="space-y-2" data-testid="group-field-updates">
              <h3 className="font-medium">{t("my_requests.group_field_updates")}</h3>
              {fieldUpdates.length === 0 && <p className="text-sm text-gray-500">{t("my_requests.empty_field_updates")}</p>}
              <div className="space-y-2 text-sm">
                {fieldUpdates.map((u) => (
                  <div key={u.id} data-testid={`field-update-row-${u.id}`} className="border dark:border-gray-600 rounded p-3 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{t(`soldier_profile.${u.field_name}`)}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${u.status === "pending" ? "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200" : u.status === "approved" ? "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" : "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200"}`}>
                        {t(`soldier_profile.update_${u.status}`)}
                      </span>
                    </div>
                    <div className="text-gray-500">
                      {t("soldier_profile.previous_value")}: <span className="font-mono">{formatFieldUpdateValue(u.field_name, u.previous_value, t)}</span>
                    </div>
                    <div className="text-gray-500">
                      {t("soldier_profile.new_value")}: <span className="font-mono">{formatFieldUpdateValue(u.field_name, u.new_value, t)}</span>
                    </div>
                    {u.decision_note && (
                      <p className="text-xs text-red-700 dark:text-red-400">{t("my_requests.decision_note")}: {u.decision_note}</p>
                    )}
                  </div>
                ))}
              </div>
            </section>

            {/* Swaps in process — full reuse of the SwapsPage card incl. actions */}
            <section className="space-y-2" data-testid="group-swaps">
              <h3 className="font-medium">{t("my_requests.group_swaps")}</h3>
              {inProcessSwaps.length === 0 && <p className="text-sm text-gray-500">{t("my_requests.empty_swaps")}</p>}
              <ul className="space-y-2">
                {inProcessSwaps.map((s) => <MySwapCard key={s.id} swap={s} />)}
              </ul>
            </section>

            {/* Hierarchy transfer requests */}
            <section className="space-y-2" data-testid="group-transfers">
              <h3 className="font-medium">{t("my_requests.group_transfers")}</h3>
              {transfers.length === 0 && <p className="text-sm text-gray-500">{t("my_requests.empty_transfers")}</p>}
              <ul className="space-y-2 text-sm">
                {transfers.map((tr) => (
                  <li key={tr.id} data-testid={`transfer-row-${tr.id}`} className="border dark:border-gray-600 rounded-lg p-3 space-y-1">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span>
                        <span className="text-gray-500 dark:text-gray-400">{t("approvals.transfer_from")}: </span>
                        {tr.from_node?.name ?? "—"}
                        <span className="mx-1" dir="ltr">→</span>
                        <span className="text-gray-500 dark:text-gray-400">{t("approvals.transfer_to")}: </span>
                        {tr.to_node?.name ?? "—"}
                      </span>
                      {statusBadge(tr.status)}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {t("my_requests.submitted")}: {formatDate(tr.created_at)}
                    </div>
                    {tr.decision_note && (
                      <p className="text-xs text-red-700 dark:text-red-400">{t("my_requests.decision_note")}: {tr.decision_note}</p>
                    )}
                  </li>
                ))}
              </ul>
            </section>

            {/* Enrollment request */}
            <section className="space-y-2" data-testid="group-enrollment">
              <h3 className="font-medium">{t("my_requests.group_enrollment")}</h3>
              {enrollmentRequest ? (
                <div data-testid="enrollment-row" className="border dark:border-gray-600 rounded-lg p-3 text-sm space-y-1">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="font-medium">{enrollmentRequest.requested_node_name}</span>
                    {statusBadge(enrollmentRequest.status)}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {t("my_requests.submitted")}: {formatDate(enrollmentRequest.created_at)}
                  </div>
                  {enrollmentRequest.decision_note && (
                    <p className="text-xs text-red-700 dark:text-red-400">{t("my_requests.decision_note")}: {enrollmentRequest.decision_note}</p>
                  )}
                </div>
              ) : (
                <p className="text-sm text-gray-500">{t("my_requests.empty_enrollment")}</p>
              )}
            </section>

            {/* Range excusal requests */}
            <section className="space-y-2" data-testid="group-range-excusals">
              <h3 className="font-medium">{t("my_requests.group_range_excusals")}</h3>
              {rangeExcusals.length === 0 && <p className="text-sm text-gray-500">{t("my_requests.empty_range_excusals")}</p>}
              <ul className="space-y-2 text-sm">
                {rangeExcusals.map((r) => (
                  <li key={r.id} data-testid={`range-excusal-row-${r.id}`} className="border dark:border-gray-600 rounded-lg p-3 space-y-1">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span dir="ltr">{r.range_date}</span>
                      <span>{RANGE_TYPE_LABELS[r.range_type] ?? r.range_type}</span>
                      {r.range_location_name && <span className="text-gray-500 dark:text-gray-400">{r.range_location_name}</span>}
                      <span className="text-gray-700 dark:text-gray-300 flex-1">{r.reason}</span>
                      {statusBadge(r.status)}
                    </div>
                    {r.decision_note && (
                      <p className="text-xs text-red-700 dark:text-red-400">{t("my_requests.decision_note")}: {r.decision_note}</p>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </section>
    </Layout>
  );
}
