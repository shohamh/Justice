import { FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import DateInput from "../components/DateInput";
import Combobox from "../components/Combobox";
import { DaysBadge } from "../components/DaysBadge";
import { useAuth } from "../auth/AuthContext";
import { listExemptions } from "../api/exemptions";
import { ExemptionType, listExemptionTypes, getAllExemptionDutyTypeMaps, listDutyTypes } from "../api/dutyConfig";
import {
  cancelConstraint,
  getRemainingConstraintDays,
  listMyConstraints,
  submitConstraint,
} from "../api/constraints";
import { formatDate, isDateInPast, isDateRangeValid, todayIso } from "../utils/formatDate";
import { translateApiError } from "../utils/translateApiError";
import { validateFileSignature, PDF_IMAGE_SIGNATURES } from "../utils/fileValidation";
import {
  listMyExemptionRequests,
  submitExemptionRequest,
  uploadExemptionFile,
} from "../api/exemptions";
import { getMyBugReports, BugReportSeverity, BugReportStatus } from "../api/bugReports";
import BugReportDetailModal from "../components/BugReportDetailModal";

export default function MyRequestsPage() {
  const { t } = useTranslation();
  const { user, enrollmentPending } = useAuth();
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Exemption request state
  const [erTypeId, setErTypeId] = useState("");
  const [erStart, setErStart] = useState("");
  const [erEnd, setErEnd] = useState("");
  const [erReason, setErReason] = useState("");
  const [erError, setErError] = useState<string | null>(null);
  const [erSubmitting, setErSubmitting] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadSizeErrors, setUploadSizeErrors] = useState<string[]>([]);
  const [erMedical, setErMedical] = useState(false);
  const [expandedExemption, setExpandedExemption] = useState<Set<string>>(new Set());
  const [openBugReportComments, setOpenBugReportComments] = useState<string | null>(null);

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

  const dutyTypeMapQuery = useQuery({
    queryKey: queryKeys.exemptionDutyTypeMap(),
    queryFn: () => getAllExemptionDutyTypeMaps().catch(() => ({} as Record<string, string[]>)),
  });

  const dutyTypesForMapQuery = useQuery({
    queryKey: queryKeys.dutyTypes(),
    queryFn: () => listDutyTypes().catch(() => [] as { id: string; name: string }[]),
  });

  const dutyTypeMap = useMemo(() => {
    const nameById = Object.fromEntries((dutyTypesForMapQuery.data ?? []).map((d) => [d.id, d.name]));
    const named: Record<string, string[]> = {};
    for (const [etId, dtIds] of Object.entries(dutyTypeMapQuery.data ?? {})) {
      named[etId] = (dtIds as string[]).map((id) => nameById[id] ?? id);
    }
    return named;
  }, [dutyTypeMapQuery.data, dutyTypesForMapQuery.data]);

  const myBugReportsQuery = useQuery({ queryKey: queryKeys.myBugReports(), queryFn: getMyBugReports });
  const myBugReports = myBugReportsQuery.data?.items ?? [];

  const exemptionsQuery = useQuery({
    queryKey: user ? queryKeys.myExemptions(user.id) : ["exemptions", "mine", "anonymous"],
    queryFn: () => listExemptions(user!.id),
    enabled: !!user,
  });
  const exemptions = exemptionsQuery.data ?? [];

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
    if (!isDateRangeValid(erStart, erEnd)) {
      setErError(t("errors.date_range_invalid"));
      return;
    }
    setErSubmitting(true);
    try {
      const createdReq = await submitExemptionRequest({
        exemption_type_id: erTypeId,
        start_date: erStart,
        end_date: erEnd || null,
        reason: erReason || null,
      });
      // Upload any attached files automatically
      for (const f of uploadFiles) {
        await uploadExemptionFile(createdReq.id, f);
      }
      setErTypeId(""); setErStart(""); setErEnd(""); setErReason("");
      setUploadFiles([]); setUploadSizeErrors([]); setErMedical(false);
      await queryClient.invalidateQueries({ queryKey: queryKeys.myExemptionRequests() });
    } catch (err: unknown) {
      setErError(translateApiError(err, t));
    } finally {
      setErSubmitting(false);
    }
  }

  const bugReportSeverityLabel = (severity: BugReportSeverity) => t(`bug_reports.severity_${severity}`);
  const bugReportStatusLabel = (status: BugReportStatus) => t(`bug_reports.status_${status}`);

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

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-6 dark:bg-gray-800">
        <h2 className="text-xl font-semibold">{t("my_requests.title")}</h2>

        <div className="border-b dark:border-gray-600 pb-4 space-y-3">
          <h3 className="font-medium">{t("my_requests.section_constraints")}</h3>
          {error && <div className="text-red-600 text-sm" data-testid="req-error">{error}</div>}
        </div>

        {enrollmentPending && (
          <div className="rounded border border-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 px-3 py-2 text-sm text-yellow-800 dark:text-yellow-200 mb-2">
            בקשת הקליטה שלך למסגרת עדיין ממתינה לאישור — לא ניתן להגיש בקשות חדשות עד לאישור.
          </div>
        )}
        {remaining && (
          <p className="text-sm text-gray-600 dark:text-gray-400" data-testid="constraints-remaining">
            {t("constraints.remaining_summary", {
              remaining: remaining.remaining_days,
              cap: remaining.cap_days,
              until: formatDate(remaining.period_end),
            })}
          </p>
        )}
        <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2 border-b dark:border-gray-600 pb-4">
          <DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={start} onChange={(iso) => setStart(iso)} min={todayIso()} max={end || undefined} required data-testid="req-start" />
          <DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={end} onChange={(iso) => setEnd(iso)} min={start || undefined} required data-testid="req-end" />
          <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("my_requests.reason")} required data-testid="req-reason" />
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded disabled:opacity-50" disabled={submitting || enrollmentPending || isDateInPast(start) || !isDateRangeValid(start, end)} data-testid="req-submit">
            {submitting ? t("app.loading") : t("my_requests.send")}
          </button>
        </form>

        {items.length === 0 && <p className="text-sm text-gray-500" data-testid="no-constraints">{t("my_requests.none")}</p>}

        {items.filter((c) => c.status === "pending" || c.status === "pending_commander" || c.status === "pending_duty_manager").length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-1.5">{t("my_requests.pending_constraints")}</h4>
            <ul className="space-y-2 text-sm" data-testid="constraints-list">
              {items.filter((c) => c.status === "pending" || c.status === "pending_commander" || c.status === "pending_duty_manager").map((c) => (
                <li key={c.id} className="border dark:border-gray-600 rounded-lg p-3 bg-white dark:bg-gray-800 flex items-center gap-3" data-testid={`constraint-row-${c.id}`}>
                  <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                  <DaysBadge start={c.start_date} end={c.end_date} />
                  <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                  {statusBadge(c.status)}
                  {/* Only the first approval step (pending_commander) is cancelable —
                      see cancel_constraint in backend/app/services/constraints.py.
                      Once it reaches pending_duty_manager it can no longer be
                      withdrawn unilaterally, so hide the button to avoid a call
                      that would 400. */}
                  {(c.status === "pending" || c.status === "pending_commander") && (
                    <button className="text-red-500 text-xs" onClick={() => onCancel(c.id)} data-testid={`cancel-${c.id}`}>
                      {t("my_requests.cancel")}
                    </button>
                  )}
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
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="pt-4 border-t dark:border-gray-600">
          <h3 className="font-medium">{t("exemption_requests.title")}</h3>
          {erError && <div className="text-red-600 dark:text-red-400 text-sm" data-testid="er-error">{erError}</div>}
          {enrollmentPending && (
            <div className="rounded border border-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 px-3 py-2 text-sm text-yellow-800 dark:text-yellow-200 mb-2 mt-2">
              בקשת הקליטה שלך למסגרת עדיין ממתינה לאישור — לא ניתן להגיש בקשות חדשות עד לאישור.
            </div>
          )}
          <form onSubmit={onErSubmit} className="mt-2 space-y-3" dir="rtl">
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
                <DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={erStart} onChange={(iso) => setErStart(iso)} max={erEnd || undefined} required data-testid="er-start" />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.end_date")}</label>
                <DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={erEnd} onChange={(iso) => setErEnd(iso)} min={erStart || undefined} data-testid="er-end" />
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
              disabled={erSubmitting || !erTypeId || (isMedical && uploadFiles.length === 0) || enrollmentPending || !isDateRangeValid(erStart, erEnd)}
              data-testid="er-submit"
            >
              {erSubmitting ? t("app.loading") : t("exemption_requests.send")}
            </button>
            {isMedical && uploadFiles.length === 0 && (
              <p className="text-xs text-amber-600 dark:text-amber-400">{t("exemption_requests.upload_required_hint")}</p>
            )}
          </form>

          {exemptionRequests.length === 0 && <p className="text-sm text-gray-500 mt-2">{t("exemption_requests.none")}</p>}
          <ul className="text-sm space-y-1 mt-2" data-testid="er-list">
            {exemptionRequests.map((er) => (
              <li key={er.id} className="flex flex-col gap-0.5">
                <div className="flex items-center gap-3">
                  <span>{exemptionTypes.find((et) => et.id === er.exemption_type_id)?.name ?? er.exemption_type_id}</span>
                  <span dir="ltr">{er.start_date} → {er.end_date ?? t("exemptions.forever")}</span>
                  <DaysBadge start={er.start_date} end={er.end_date} />
                  {er.reason && <span className="text-gray-700 dark:text-gray-300">{er.reason}</span>}
                  <span className={`text-xs ${
                    er.status === "approved" ? "text-green-600 dark:text-green-400" :
                    er.status === "rejected" ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"
                  }`}>{t(`exemption_requests.${er.status}`)}</span>
                </div>
                {er.status === "rejected" && er.decision_note && (
                  <p className="text-xs text-red-700 dark:text-red-400">{t("my_requests.decision_note")}: {er.decision_note}</p>
                )}
              </li>
            ))}
          </ul>
        </div>

        <div className="pt-4 border-t dark:border-gray-600">
          <h3 className="font-medium mb-2">{t("my_requests.my_exemptions")}</h3>
          {exemptions.length === 0 && <p className="text-sm text-gray-500">{t("exemptions.none")}</p>}
          <ul className="space-y-2">
            {exemptions.map((ex) => {
              const exemptType = exemptionTypes.find((et) => et.id === ex.exemption_type_id);
              const dutyNames = ex.exemption_type_id ? dutyTypeMap[ex.exemption_type_id] ?? [] : [];
              const isMedical = exemptType?.is_medical ?? false;
              const isExpanded = expandedExemption.has(ex.id);
              return (
                <li key={ex.id} className="border dark:border-gray-600 rounded-lg p-3 space-y-1.5 text-sm bg-white dark:bg-gray-800">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium">{exemptType?.name ?? ex.exemption_type_id}</span>
                      {isMedical && (
                        <span className="text-xs bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 px-1.5 py-0.5 rounded">
                          {t("my_requests.medical_exemption")}
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-gray-500 dark:text-gray-400 shrink-0 flex items-center gap-1" dir="ltr">
                      {ex.start_date} → {ex.end_date ?? t("exemptions.forever")}
                      <DaysBadge start={ex.start_date} end={ex.end_date} />
                    </span>
                  </div>

                  {isMedical && (
                    <div className="flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 rounded px-2 py-1">
                      <span>🔒</span>
                      <span>{t("my_requests.medical_privacy_note")}</span>
                    </div>
                  )}

                  {(ex.reason || dutyNames.length > 0) && (
                    <button
                      className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1"
                      onClick={() => setExpandedExemption((prev) => {
                        const next = new Set(prev);
                        if (next.has(ex.id)) next.delete(ex.id); else next.add(ex.id);
                        return next;
                      })}
                    >
                      {isExpanded ? "▲" : "▼"} {t("my_requests.exemption_details")}
                    </button>
                  )}

                  {isExpanded && (
                    <div className="space-y-1 text-xs text-gray-600 dark:text-gray-300 pt-1 border-t dark:border-gray-700">
                      {ex.reason && (
                        <p><span className="font-medium text-gray-500 dark:text-gray-400">{t("my_requests.reason")}:</span> {ex.reason}</p>
                      )}
                      {dutyNames.length > 0 && (
                        <p>
                          <span className="font-medium text-gray-500 dark:text-gray-400">{t("exemptions.exempts_from")}:</span>{" "}
                          {dutyNames.join("، ")}
                        </p>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>

        <div className="pt-4 border-t dark:border-gray-600">
          <h3 className="font-medium mb-2">{t("my_requests.section_bug_reports")}</h3>
          {myBugReports.length === 0 && (
            <p className="text-sm text-gray-500" data-testid="no-bug-reports">{t("bug_reports.none")}</p>
          )}
          <ul className="space-y-2 text-sm" data-testid="my-bug-reports-list">
            {myBugReports.map((report) => (
              <li
                key={report.id}
                className="border dark:border-gray-600 rounded-lg p-3 flex items-center gap-3 bg-white dark:bg-gray-800"
                data-testid={`bug-report-row-${report.id}`}
              >
                <span dir="ltr" className="text-xs text-gray-500 dark:text-gray-400 shrink-0">
                  {new Date(report.created_at).toLocaleString("he-IL")}
                </span>
                <span className="text-xs px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 shrink-0">
                  {bugReportSeverityLabel(report.severity)}
                </span>
                <span className="text-xs px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 shrink-0">
                  {bugReportStatusLabel(report.status)}
                </span>
                <span className="flex-1 truncate">{report.description}</span>
                <button
                  className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline shrink-0"
                  onClick={() => setOpenBugReportComments(report.id)}
                  data-testid={`bug-report-comments-${report.id}`}
                >
                  {t("bug_reports.comment_button")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {openBugReportComments && (
        <BugReportDetailModal reportId={openBugReportComments} onClose={() => setOpenBugReportComments(null)} />
      )}
    </Layout>
  );
}
