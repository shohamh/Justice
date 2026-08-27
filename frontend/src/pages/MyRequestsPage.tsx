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
import SoldierLink from "../components/SoldierLink";
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
import type { SoldierRef, WaitingOnRef } from "../api/myRequests";

type StatusBucket = "pending" | "approved" | "rejected" | "cancelled";

const STATUS_BUCKETS: StatusBucket[] = ["pending", "approved", "rejected", "cancelled"];

/** Existing-tab groups in display order; ids double as URL ?type= values. */
const REQUEST_TYPE_GROUPS = [
  { id: "constraints", labelKey: "my_requests.section_constraints" },
  { id: "exemption_requests", labelKey: "exemption_requests.title" },
  { id: "field_updates", labelKey: "my_requests.group_field_updates" },
  { id: "swaps", labelKey: "my_requests.group_swaps" },
  { id: "transfers", labelKey: "my_requests.group_transfers" },
  { id: "enrollment", labelKey: "my_requests.group_enrollment" },
  { id: "range_excusals", labelKey: "my_requests.group_range_excusals" },
] as const;

type TypeFilterId = (typeof REQUEST_TYPE_GROUPS)[number]["id"];

/** Maps any request-row status into a filter bucket — every pending_* variant
 * counts as ממתין. */
function statusBucket(status: string): StatusBucket {
  if (status === "approved" || status === "rejected" || status === "cancelled") return status;
  return "pending";
}

interface RequestMetaProps {
  requestedAt?: string | null;
  /** Fallback for rows whose backend payload predates requested_at. */
  createdAt?: string | null;
  updatedAt?: string | null;
  waitingOn?: WaitingOnRef | null;
  decidedBy?: SoldierRef | null;
  /** Row status — picks אושר ע״י vs נדחה ע״י when decidedBy is present. */
  status?: string | null;
  commanderApprovedBy?: SoldierRef | null;
  testIdPrefix?: string;
}

/** Compact single metadata row shared by every request card in the existing
 * tab: request/update dates, who it's waiting on, and who decided. */
function RequestMetaRow({
  requestedAt,
  createdAt,
  updatedAt,
  waitingOn,
  decidedBy,
  status,
  commanderApprovedBy,
  testIdPrefix,
}: RequestMetaProps) {
  const { t } = useTranslation();
  const requestedIso = requestedAt ?? createdAt ?? null;
  const requestedDay = requestedIso ? formatDate(requestedIso.slice(0, 10)) : null;
  const updatedDay = updatedAt ? formatDate(updatedAt.slice(0, 10)) : null;
  // The update line only adds signal when it lands on a different day.
  const showUpdate = updatedDay !== null && updatedDay !== requestedDay;
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500 dark:text-gray-400"
      data-testid={testIdPrefix ? `${testIdPrefix}-meta` : undefined}
    >
      {requestedDay && (
        <span>
          {t("my_requests.requested_at")}: <span dir="ltr">{requestedDay}</span>
        </span>
      )}
      {showUpdate && (
        <span>
          {t("my_requests.updated_at")}: <span dir="ltr">{updatedDay}</span>
        </span>
      )}
      {waitingOn && (
        <span data-testid={testIdPrefix ? `${testIdPrefix}-waiting-on` : undefined}>
          {t("my_requests.waiting_approval")}{" "}
          <SoldierLink id={waitingOn.soldier_id} name={waitingOn.name} className="text-xs" />
          {" "}({t(`my_requests.role_${waitingOn.kind}`)})
        </span>
      )}
      {decidedBy && (status === "approved" || status === "rejected" || status === "cancelled") && (
        <span data-testid={testIdPrefix ? `${testIdPrefix}-decided-by` : undefined}>
          {t(
            status === "approved"
              ? "my_requests.approved_by"
              : status === "rejected"
              ? "my_requests.rejected_by"
              : "my_requests.cancelled_by",
          )}{" "}
          <SoldierLink id={decidedBy.soldier_id} name={decidedBy.name} className="text-xs" />
        </span>
      )}
      {commanderApprovedBy && (
        <span data-testid={testIdPrefix ? `${testIdPrefix}-commander-step` : undefined}>
          {t("my_requests.commander_step")}:{" "}
          <SoldierLink id={commanderApprovedBy.soldier_id} name={commanderApprovedBy.name} className="text-xs" />
        </span>
      )}
    </div>
  );
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

  // Existing-tab filters, persisted in the URL alongside ?tab=existing.
  const rawTypeFilter = searchParams.get("type");
  const typeFilter: TypeFilterId | "all" =
    rawTypeFilter && REQUEST_TYPE_GROUPS.some((g) => g.id === rawTypeFilter)
      ? (rawTypeFilter as TypeFilterId)
      : "all";
  const rawStatusFilter = searchParams.get("status");
  const statusFilter: StatusBucket | "all" =
    rawStatusFilter && STATUS_BUCKETS.includes(rawStatusFilter as StatusBucket)
      ? (rawStatusFilter as StatusBucket)
      : "all";

  function setFilter(key: "type" | "status", value: string) {
    setSearchParams((prev) => {
      if (value === "all") prev.delete(key); else prev.set(key, value);
      return prev;
    }, { replace: true });
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

  // Existing-tab rows after the type/status filters. Swaps never carry an
  // approved bucket — open/applied both count as ממתין.
  const matchesStatus = (status: string) =>
    statusFilter === "all" || statusBucket(status) === statusFilter;
  const showGroup = (id: TypeFilterId) => typeFilter === "all" || typeFilter === id;
  const visibleConstraints = items.filter((c) => matchesStatus(c.status));
  const visibleExemptionRequests = exemptionRequests.filter((er) => matchesStatus(er.status));
  const visibleFieldUpdates = fieldUpdates.filter((u) => matchesStatus(u.status));
  const visibleSwaps = inProcessSwaps.filter((s) => matchesStatus(s.status));
  const visibleTransfers = transfers.filter((tr) => matchesStatus(tr.status));
  const visibleRangeExcusals = rangeExcusals.filter((r) => matchesStatus(r.status));

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
      cancelled: "text-gray-500 dark:text-gray-400",
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
            {/* Type/status filters — persisted in URL query params alongside ?tab=existing. */}
            <div className="flex flex-wrap items-end gap-3" data-testid="requests-filters">
              <div className="flex flex-col gap-1">
                <label htmlFor="filter-type" className="text-xs text-gray-500 dark:text-gray-400">{t("my_requests.filter_type_label")}</label>
                <select
                  id="filter-type"
                  className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  data-testid="filter-type"
                  value={typeFilter}
                  onChange={(e) => setFilter("type", e.target.value)}
                >
                  <option value="all">{t("my_requests.filter_all")}</option>
                  {REQUEST_TYPE_GROUPS.map((g) => (
                    <option key={g.id} value={g.id}>{t(g.labelKey)}</option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor="filter-status" className="text-xs text-gray-500 dark:text-gray-400">{t("my_requests.filter_status_label")}</label>
                <select
                  id="filter-status"
                  className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  data-testid="filter-status"
                  value={statusFilter}
                  onChange={(e) => setFilter("status", e.target.value)}
                >
                  <option value="all">{t("my_requests.filter_all")}</option>
                  {STATUS_BUCKETS.map((b) => (
                    <option key={b} value={b}>{b === "pending" ? t("my_requests.filter_pending") : t(`my_requests.${b}`)}</option>
                  ))}
                </select>
              </div>
            </div>

            {typeFilter === "all" && (activeConstraints.length > 0 || activeExemptions.length > 0) && (
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
            {showGroup("constraints") && (
            <section className="space-y-3" data-testid="group-constraints">
              <h3 className="font-medium">{t("my_requests.section_constraints")}</h3>
              {visibleConstraints.length === 0 && <p className="text-sm text-gray-500" data-testid="no-constraints">{t("my_requests.none")}</p>}

              {visibleConstraints.filter((c) => statusBucket(c.status) === "pending").length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-1.5">{t("my_requests.pending_constraints")}</h4>
                  <ul className="space-y-2 text-sm" data-testid="constraints-list">
                    {visibleConstraints.filter((c) => statusBucket(c.status) === "pending").map((c) => (
                      <li key={c.id} className="border dark:border-gray-600 rounded-lg p-3 bg-white dark:bg-gray-800 flex flex-col gap-2" data-testid={`constraint-row-${c.id}`}>
                        <div className="flex items-center gap-3">
                          <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                          <DaysBadge start={c.start_date} end={c.end_date} />
                          <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                          {statusBadge(c.status)}
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
                        <RequestMetaRow
                          testIdPrefix={`constraint-${c.id}`}
                          requestedAt={c.requested_at}
                          createdAt={c.created_at}
                          updatedAt={c.updated_at}
                          waitingOn={c.waiting_on}
                          decidedBy={c.decided_by}
                          status={c.status}
                          commanderApprovedBy={c.commander_approved_by}
                        />
                        <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {visibleConstraints.filter((c) => c.status === "approved").length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-1.5">{t("my_requests.approved_constraints")}</h4>
                  <ul className="space-y-2 text-sm">
                    {visibleConstraints.filter((c) => c.status === "approved").map((c) => (
                      <li key={c.id} className="border border-green-200 dark:border-green-800 rounded-lg p-3 bg-green-50 dark:bg-green-950" data-testid={`constraint-row-${c.id}`}>
                        <div className="flex items-center gap-3">
                          <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                          <DaysBadge start={c.start_date} end={c.end_date} />
                          <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                          {statusBadge(c.status)}
                        </div>
                        <RequestMetaRow
                          testIdPrefix={`constraint-${c.id}`}
                          requestedAt={c.requested_at}
                          createdAt={c.created_at}
                          updatedAt={c.updated_at}
                          waitingOn={c.waiting_on}
                          decidedBy={c.decided_by}
                          status={c.status}
                          commanderApprovedBy={c.commander_approved_by}
                        />
                        <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {visibleConstraints.filter((c) => c.status === "rejected").length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-1.5">{t("my_requests.rejected_constraints")}</h4>
                  <ul className="space-y-2 text-sm">
                    {visibleConstraints.filter((c) => c.status === "rejected").map((c) => (
                      <li key={c.id} className="border border-red-200 dark:border-red-800 rounded-lg p-3 bg-red-50 dark:bg-red-950" data-testid={`constraint-row-${c.id}`}>
                        <div className="flex items-center gap-3">
                          <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                          <DaysBadge start={c.start_date} end={c.end_date} />
                          <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                          {statusBadge(c.status)}
                        </div>
                        <RequestMetaRow
                          testIdPrefix={`constraint-${c.id}`}
                          requestedAt={c.requested_at}
                          createdAt={c.created_at}
                          updatedAt={c.updated_at}
                          waitingOn={c.waiting_on}
                          decidedBy={c.decided_by}
                          status={c.status}
                          commanderApprovedBy={c.commander_approved_by}
                        />
                        {c.decision_note && (
                          <p className="text-xs text-red-700 dark:text-red-400 mt-1">{t("my_requests.decision_note")}: {c.decision_note}</p>
                        )}
                        <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {visibleConstraints.filter((c) => c.status === "cancelled").length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-1.5">{t("my_requests.cancelled_constraints")}</h4>
                  <ul className="space-y-2 text-sm" data-testid="cancelled-constraints-list">
                    {visibleConstraints.filter((c) => c.status === "cancelled").map((c) => (
                      <li key={c.id} className="border border-gray-200 dark:border-gray-700 rounded-lg p-3 bg-gray-50 dark:bg-gray-900" data-testid={`constraint-row-${c.id}`}>
                        <div className="flex items-center gap-3">
                          <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                          <DaysBadge start={c.start_date} end={c.end_date} />
                          <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                          {statusBadge(c.status)}
                        </div>
                        <RequestMetaRow
                          testIdPrefix={`constraint-${c.id}`}
                          requestedAt={c.requested_at}
                          createdAt={c.created_at}
                          updatedAt={c.updated_at}
                          waitingOn={c.waiting_on}
                          decidedBy={c.decided_by}
                          status={c.status}
                          commanderApprovedBy={c.commander_approved_by}
                        />
                        {c.decision_note && (
                          <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">{t("my_requests.decision_note")}: {c.decision_note}</p>
                        )}
                        <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
            )}

            {/* Exemption requests */}
            {showGroup("exemption_requests") && (
            <section className="space-y-2" data-testid="group-exemption-requests">
              <h3 className="font-medium">{t("exemption_requests.title")}</h3>
              {visibleExemptionRequests.length === 0 && <p className="text-sm text-gray-500">{t("exemption_requests.none")}</p>}
              <ul className="text-sm space-y-1" data-testid="er-list">
                {visibleExemptionRequests.map((er) => (
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
                    </div>
                    <RequestMetaRow
                      testIdPrefix={`er-${er.id}`}
                      requestedAt={er.requested_at}
                      createdAt={er.created_at}
                      updatedAt={er.updated_at}
                      waitingOn={er.waiting_on}
                      decidedBy={er.decided_by}
                      status={er.status}
                      commanderApprovedBy={er.commander_approved_by}
                    />
                    {er.status === "rejected" && er.decision_note && (
                      <p className="text-xs text-red-700 dark:text-red-400">{t("my_requests.decision_note")}: {er.decision_note}</p>
                    )}
                  </li>
                ))}
              </ul>
            </section>
            )}


            {/* Profile field updates */}
            {showGroup("field_updates") && (
            <section className="space-y-2" data-testid="group-field-updates">
              <h3 className="font-medium">{t("my_requests.group_field_updates")}</h3>
              {visibleFieldUpdates.length === 0 && <p className="text-sm text-gray-500">{t("my_requests.empty_field_updates")}</p>}
              <div className="space-y-2 text-sm">
                {visibleFieldUpdates.map((u) => (
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
                    <RequestMetaRow
                      testIdPrefix={`field-update-${u.id}`}
                      requestedAt={u.requested_at}
                      createdAt={u.created_at}
                      updatedAt={u.updated_at}
                      waitingOn={u.waiting_on}
                      decidedBy={u.decided_by}
                      status={u.status}
                    />
                    {u.decision_note && (
                      <p className="text-xs text-red-700 dark:text-red-400">{t("my_requests.decision_note")}: {u.decision_note}</p>
                    )}
                  </div>
                ))}
              </div>
            </section>
            )}


            {/* Swaps in process — full reuse of the SwapsPage card incl. actions */}
            {showGroup("swaps") && (
            <section className="space-y-2" data-testid="group-swaps">
              <h3 className="font-medium">{t("my_requests.group_swaps")}</h3>
              {visibleSwaps.length === 0 && <p className="text-sm text-gray-500">{t("my_requests.empty_swaps")}</p>}
              <ul className="space-y-2">
                {visibleSwaps.map((s) => <MySwapCard key={s.id} swap={s} />)}
              </ul>
            </section>
            )}


            {/* Hierarchy transfer requests */}
            {showGroup("transfers") && (
            <section className="space-y-2" data-testid="group-transfers">
              <h3 className="font-medium">{t("my_requests.group_transfers")}</h3>
              {visibleTransfers.length === 0 && <p className="text-sm text-gray-500">{t("my_requests.empty_transfers")}</p>}
              <ul className="space-y-2 text-sm">
                {visibleTransfers.map((tr) => (
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
                    <RequestMetaRow
                      testIdPrefix={`transfer-${tr.id}`}
                      requestedAt={tr.requested_at}
                      createdAt={tr.created_at}
                      updatedAt={tr.updated_at}
                      waitingOn={tr.waiting_on}
                      decidedBy={tr.decided_by}
                      status={tr.status}
                    />
                    {tr.decision_note && (
                      <p className="text-xs text-red-700 dark:text-red-400">{t("my_requests.decision_note")}: {tr.decision_note}</p>
                    )}
                  </li>
                ))}
              </ul>
            </section>
            )}


            {/* Enrollment request */}
            {showGroup("enrollment") && (
            <section className="space-y-2" data-testid="group-enrollment">
              <h3 className="font-medium">{t("my_requests.group_enrollment")}</h3>
              {enrollmentRequest && matchesStatus(enrollmentRequest.status) ? (
                <div data-testid="enrollment-row" className="border dark:border-gray-600 rounded-lg p-3 text-sm space-y-1">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="font-medium">{enrollmentRequest.requested_node_name}</span>
                    {statusBadge(enrollmentRequest.status)}
                  </div>
                  <RequestMetaRow
                    testIdPrefix={`enrollment-${enrollmentRequest.id}`}
                    requestedAt={enrollmentRequest.requested_at}
                    createdAt={enrollmentRequest.created_at}
                    updatedAt={enrollmentRequest.updated_at}
                    waitingOn={enrollmentRequest.waiting_on}
                    decidedBy={enrollmentRequest.decided_by}
                    status={enrollmentRequest.status}
                  />
                  {enrollmentRequest.decision_note && (
                    <p className="text-xs text-red-700 dark:text-red-400">{t("my_requests.decision_note")}: {enrollmentRequest.decision_note}</p>
                  )}
                </div>
              ) : !enrollmentRequest ? (
                <p className="text-sm text-gray-500">{t("my_requests.empty_enrollment")}</p>
              ) : null}
            </section>
            )}


            {/* Range excusal requests */}
            {showGroup("range_excusals") && (
            <section className="space-y-2" data-testid="group-range-excusals">
              <h3 className="font-medium">{t("my_requests.group_range_excusals")}</h3>
              {visibleRangeExcusals.length === 0 && <p className="text-sm text-gray-500">{t("my_requests.empty_range_excusals")}</p>}
              <ul className="space-y-2 text-sm">
                {visibleRangeExcusals.map((r) => (
                  <li key={r.id} data-testid={`range-excusal-row-${r.id}`} className="border dark:border-gray-600 rounded-lg p-3 space-y-1">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span dir="ltr">{r.range_date}</span>
                      <span>{RANGE_TYPE_LABELS[r.range_type] ?? r.range_type}</span>
                      {r.range_location_name && <span className="text-gray-500 dark:text-gray-400">{r.range_location_name}</span>}
                      <span className="text-gray-700 dark:text-gray-300 flex-1">{r.reason}</span>
                      {statusBadge(r.status)}
                    </div>
                    <RequestMetaRow
                      testIdPrefix={`range-excusal-${r.id}`}
                      requestedAt={r.requested_at}
                      createdAt={r.created_at}
                      updatedAt={r.updated_at}
                      waitingOn={r.waiting_on}
                      decidedBy={r.decided_by}
                      status={r.status}
                    />
                    {r.decision_note && (
                      <p className="text-xs text-red-700 dark:text-red-400">{t("my_requests.decision_note")}: {r.decision_note}</p>
                    )}
                  </li>
                ))}
              </ul>
            </section>
            )}
          </div>
        )}
      </section>
    </Layout>
  );
}
