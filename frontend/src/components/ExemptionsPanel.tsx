import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AxiosError } from "axios";

import {
  ExemptionType,
  getAllExemptionDutyTypeMaps,
  listDutyTypes,
  listExemptionTypes,
} from "../api/dutyConfig";
import {
  Exemption,
  ExemptionRequest,
  approveExemptionRequestCommanderStep,
  approveExemptionRequestDutyManagerStep,
  escalateCommanderExemption,
  grantCommanderExemption,
  grantExemption,
  listExemptions,
  listExemptionRequestsForSoldier,
  rejectExemptionRequest,
  revokeExemption,
  uploadSoldierExemptionFile,
} from "../api/exemptions";
import { useAuth } from "../auth/AuthContext";
import DateInput from "../components/DateInput";
import { formatDate, isDateRangeValid } from "../utils/formatDate";
import { PDF_IMAGE_SIGNATURES, validateFileSignature } from "../utils/fileValidation";
import { translateApiError } from "../utils/translateApiError";
import ApprovalStageIcons from "./ApprovalStageIcons";
import Combobox from "./Combobox";
import { DaysBadge } from "./DaysBadge";
import ReasonPromptModal from "./ReasonPromptModal";

const MAX_FILE_BYTES = 10 * 1024 * 1024;

export default function ExemptionsPanel({
  soldierId,
  canManage,
  canApproveDutyManagerStep,
}: {
  soldierId: string;
  canManage: boolean;
  canApproveDutyManagerStep: boolean;
}) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const canApplyImmediately =
    user?.role === "admin" || (user?.can_apply_commander_exemption_immediately ?? false);
  const [items, setItems] = useState<Exemption[]>([]);
  const [types, setTypes] = useState<ExemptionType[]>([]);
  const [dutyTypeMap, setDutyTypeMap] = useState<Record<string, string[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [typeId, setTypeId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [indefinite, setIndefinite] = useState(false);
  const [reason, setReason] = useState("");
  const [medicalClassification, setMedicalClassification] = useState(false);
  const [grantFiles, setGrantFiles] = useState<File[]>([]);
  const [grantFileValidationErrors, setGrantFileValidationErrors] = useState<string[]>([]);
  const [grantError, setGrantError] = useState<string | null>(null);
  const [grantSubmitting, setGrantSubmitting] = useState(false);
  const [requests, setRequests] = useState<ExemptionRequest[]>([]);
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({});
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);
  const [commanderReason, setCommanderReason] = useState("");
  const [commanderError, setCommanderError] = useState<string | null>(null);
  const [commanderEscalate, setCommanderEscalate] = useState(!canApplyImmediately);
  const [commanderOfficialTypeId, setCommanderOfficialTypeId] = useState("");
  const [commanderApplyImmediately, setCommanderApplyImmediately] = useState(false);
  const [showCommanderConfirm, setShowCommanderConfirm] = useState(false);
  const [commanderAcknowledged, setCommanderAcknowledged] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setItems(await listExemptions(soldierId));
      setDenied(false);
    } catch (err) {
      if ((err as AxiosError)?.response?.status === 403) {
        setDenied(true);
        setItems([]);
      } else {
        throw err;
      }
    }
  }, [soldierId]);

  const refreshRequests = useCallback(async () => {
    try {
      setRequests(await listExemptionRequestsForSoldier(soldierId));
    } catch (err) {
      if ((err as AxiosError)?.response?.status === 403) {
        setDenied(true);
        setRequests([]);
      } else {
        throw err;
      }
    }
  }, [soldierId]);

  useEffect(() => {
    void refreshRequests();
  }, [refreshRequests]);

  useEffect(() => {
    void refresh();
    void (async () => {
      try {
        const exemptionTypes = await listExemptionTypes();
        setTypes(exemptionTypes);
      } catch {
        // Types stay empty on error.
      }
      try {
        const [maps, dutyTypes] = await Promise.all([
          getAllExemptionDutyTypeMaps(),
          listDutyTypes(),
        ]);
        const nameById = Object.fromEntries(dutyTypes.map((dutyType) => [dutyType.id, dutyType.name]));
        const named: Record<string, string[]> = {};
        for (const [exemptionTypeId, dutyTypeIds] of Object.entries(maps)) {
          named[exemptionTypeId] = dutyTypeIds.map((id) => nameById[id] ?? id);
        }
        setDutyTypeMap(named);
      } catch {
        // Duty-type map stays empty on error.
      }
    })();
  }, [refresh]);

  const typeName = (id: string) => types.find((type) => type.id === id)?.name ?? "—";
  const activeTypes = types.filter((type) => type.active);
  const officialExemptionTypes = activeTypes.filter((type) => type.is_commander_exemption !== true);
  const selectedType = activeTypes.find((type) => type.id === typeId) ?? null;
  const isCommanderGrant = selectedType?.is_commander_exemption === true;
  const lockedMedicalClassification = selectedType?.is_medical === true;
  const isMedicalGrant = !isCommanderGrant && (lockedMedicalClassification || medicalClassification);

  useEffect(() => {
    if (!canApplyImmediately) {
      setCommanderEscalate(true);
      setCommanderApplyImmediately(false);
    }
  }, [canApplyImmediately]);

  useEffect(() => {
    if (!isCommanderGrant) {
      setShowCommanderConfirm(false);
      setCommanderAcknowledged(false);
      return;
    }
    setGrantError(null);
    if (
      commanderOfficialTypeId &&
      officialExemptionTypes.some((type) => type.id === commanderOfficialTypeId)
    ) {
      return;
    }
    setCommanderOfficialTypeId(officialExemptionTypes[0]?.id ?? "");
  }, [commanderOfficialTypeId, isCommanderGrant, officialExemptionTypes]);

  function resetGrantForm() {
    setTypeId("");
    setStart("");
    setEnd("");
    setIndefinite(false);
    setReason("");
    setMedicalClassification(false);
    setGrantFiles([]);
    setGrantFileValidationErrors([]);
    setGrantError(null);
    setCommanderReason("");
    setCommanderError(null);
    setCommanderEscalate(!canApplyImmediately);
    setCommanderOfficialTypeId(officialExemptionTypes[0]?.id ?? "");
    setCommanderApplyImmediately(false);
    setShowCommanderConfirm(false);
    setCommanderAcknowledged(false);
  }

  function toggleExpand(id: string) {
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function onGrantFilesChange(files: FileList | null) {
    const picked = Array.from(files ?? []);
    if (picked.length === 0) return;
    const withinSize = picked.filter((file) => file.size <= MAX_FILE_BYTES);
    const oversized = picked.filter((file) => file.size > MAX_FILE_BYTES).map((file) => file.name);
    const signatureChecks = await Promise.all(
      withinSize.map((file) => validateFileSignature(file, PDF_IMAGE_SIGNATURES)),
    );
    const valid = withinSize.filter((_, index) => signatureChecks[index]);
    const invalidType = withinSize
      .filter((_, index) => !signatureChecks[index])
      .map((file) => file.name);
    setGrantFiles((previous) => [...previous, ...valid]);
    setGrantFileValidationErrors([...oversized, ...invalidType]);
  }

  async function onGrant(event: FormEvent) {
    event.preventDefault();
    if (isCommanderGrant) return;
    setGrantError(null);
    if (!start) {
      setGrantError(t("errors.start_date_required"));
      return;
    }
    if (!isDateRangeValid(start, end)) {
      setGrantError(t("errors.date_range_invalid"));
      return;
    }
    if (isMedicalGrant && grantFiles.length === 0) {
      setGrantError(t("exemption_requests.upload_required_hint"));
      return;
    }

    setGrantSubmitting(true);
    try {
      const createdExemption = await grantExemption(soldierId, {
        exemption_type_id: typeId,
        is_medical: isMedicalGrant,
        start_date: start,
        end_date: end || null,
        reason: reason || null,
      });

      try {
        for (const file of grantFiles) {
          await uploadSoldierExemptionFile(soldierId, createdExemption.id, file);
        }
      } catch {
        const uploadError = t("exemption_requests.upload_error");
        resetGrantForm();
        setGrantError(uploadError);
        await Promise.all([refresh(), refreshRequests()]);
        return;
      }

      resetGrantForm();
      await Promise.all([refresh(), refreshRequests()]);
    } catch (err) {
      setGrantError(translateApiError(err, t));
    } finally {
      setGrantSubmitting(false);
    }
  }

  async function onRevoke(id: string, revokeReason: string) {
    await revokeExemption(soldierId, id, revokeReason);
    setRevokingId(null);
    await refresh();
  }

  async function onApproveCommanderStep(id: string) {
    await approveExemptionRequestCommanderStep(id);
    await refreshRequests();
  }

  async function onApproveDutyManagerStep(id: string) {
    await approveExemptionRequestDutyManagerStep(id);
    await refreshRequests();
  }

  async function onRejectRequest(id: string) {
    const note = rejectNotes[id];
    if (!note) return;
    await rejectExemptionRequest(id, note);
    setRejectNotes((previous) => {
      const next = { ...previous };
      delete next[id];
      return next;
    });
    await refreshRequests();
  }

  function openCommanderConfirm() {
    setCommanderError(null);
    if (!start) {
      setCommanderError(t("errors.start_date_required"));
      return;
    }
    if (!commanderReason.trim()) {
      setCommanderError(t("exemptions.commander_reason_required"));
      return;
    }
    if (commanderEscalate && !commanderOfficialTypeId) {
      setCommanderError(t("exemptions.commander_official_type_required"));
      return;
    }
    if (!isDateRangeValid(start, end)) {
      setCommanderError(t("errors.date_range_invalid"));
      return;
    }
    setCommanderAcknowledged(false);
    setShowCommanderConfirm(true);
  }

  async function handleCommanderConfirm() {
    setCommanderError(null);
    try {
      if (commanderEscalate) {
        await escalateCommanderExemption(soldierId, {
          official_exemption_type_id: commanderOfficialTypeId,
          commander_exemption_type_id: commanderApplyImmediately ? typeId : undefined,
          start_date: start,
          end_date: end || null,
          reason: commanderReason,
          apply_immediately: commanderApplyImmediately,
        });
      } else if (canApplyImmediately) {
        await grantCommanderExemption(soldierId, {
          exemption_type_id: typeId,
          start_date: start,
          end_date: end || null,
          reason: commanderReason,
        });
      }

      resetGrantForm();
      await Promise.all([refresh(), refreshRequests()]);
    } catch (err) {
      setCommanderError(translateApiError(err, t, t("exemptions.commander_submit_error")));
      setShowCommanderConfirm(false);
    }
  }

  const today = new Date().toISOString().slice(0, 10);
  const activeItems = items.filter(
    (exemption) => !exemption.revoked_by_name && (exemption.end_date == null || exemption.end_date >= today),
  );
  const expiredItems = items.filter(
    (exemption) => exemption.revoked_by_name || (exemption.end_date != null && exemption.end_date < today),
  );
  const regularSubmitDisabled =
    grantSubmitting ||
    !typeId ||
    !start ||
    !isDateRangeValid(start, end) ||
    (isMedicalGrant && grantFiles.length === 0);

  return (
    <div data-testid="exemptions-panel" className="space-y-4">
      <div>
        <h3 className="font-semibold text-sm text-gray-700 dark:text-gray-200 mb-2">
          {denied ? (
            <>
              {t("exemptions.title")}{" "}
              <span
                className="text-gray-400 dark:text-gray-500 font-normal"
                data-testid="exemptions-denied"
              >
                ({t("exemptions.hidden")})
              </span>
            </>
          ) : (
            <>{t("exemptions.title")} ({activeItems.length})</>
          )}
        </h3>
        {denied ? null : activeItems.length === 0 ? (
          <p className="text-sm text-gray-500" data-testid="exemptions-empty">
            {t("exemptions.none")}
          </p>
        ) : (
          <ul className="space-y-2" data-testid="exemptions-list">
            {activeItems.map((exemption) => {
              const names = exemption.exemption_type_id
                ? (dutyTypeMap[exemption.exemption_type_id] ?? [])
                : [];
              const isExpanded = expanded.has(exemption.id);
              return (
                <li
                  key={exemption.id}
                  className="border border-indigo-200 dark:border-indigo-700 bg-indigo-50 dark:bg-indigo-950 rounded-lg p-3 cursor-pointer hover:bg-indigo-100 dark:hover:bg-indigo-900 transition-colors"
                  onClick={() => toggleExpand(exemption.id)}
                  data-testid={`exemption-row-${exemption.id}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-0.5">
                      <p className="font-medium text-sm text-indigo-900 dark:text-indigo-100">
                        {exemption.exemption_type_id ? typeName(exemption.exemption_type_id) : "מידע פרטי"}
                      </p>
                      <p className="text-xs text-indigo-700 dark:text-indigo-300" dir="ltr">
                        {formatDate(exemption.start_date)} →{" "}
                        {exemption.end_date ? formatDate(exemption.end_date) : t("exemptions.forever")}
                      </p>
                      <DaysBadge start={exemption.start_date} end={exemption.end_date} />
                    </div>
                    {(exemption.can_cancel || canManage) && (
                      <button
                        className="text-red-500 text-xs shrink-0"
                        onClick={(event) => {
                          event.stopPropagation();
                          setRevokingId(exemption.id);
                        }}
                        data-testid={`revoke-${exemption.id}`}
                      >
                        {t("exemptions.revoke")}
                      </button>
                    )}
                  </div>
                  {isExpanded && names.length > 0 && (
                    <div className="mt-2 text-xs text-indigo-700 dark:text-indigo-300 border-t border-indigo-200 dark:border-indigo-700 pt-1">
                      <span className="font-medium">{t("exemptions.exempts_from")}:</span>{" "}
                      {names.join("، ")}
                    </div>
                  )}
                  {isExpanded && exemption.reason && (
                    <p className="mt-1 text-xs text-indigo-600 dark:text-indigo-400">{exemption.reason}</p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {expiredItems.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">
            {t("exemptions.past")}
          </h4>
          <ul className="space-y-1 text-sm" data-testid="exemptions-list-past">
            {expiredItems.map((exemption) => {
              const names = exemption.exemption_type_id
                ? (dutyTypeMap[exemption.exemption_type_id] ?? [])
                : [];
              const isExpanded = expanded.has(exemption.id);
              return (
                <li
                  key={exemption.id}
                  className="border dark:border-gray-600 rounded p-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 opacity-60"
                  onClick={() => toggleExpand(exemption.id)}
                  data-testid={`exemption-row-${exemption.id}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium">
                      {exemption.exemption_type_id ? typeName(exemption.exemption_type_id) : "מידע פרטי"}
                    </span>
                    <span className="text-gray-500 dark:text-gray-400 text-xs" dir="ltr">
                      {formatDate(exemption.start_date)} →{" "}
                      {exemption.end_date ? formatDate(exemption.end_date) : ""}
                    </span>
                    <DaysBadge start={exemption.start_date} end={exemption.end_date} />
                  </div>
                  {isExpanded && (
                    <div className="mt-1.5 space-y-0.5">
                      {exemption.reason && <p className="text-xs text-gray-500">{exemption.reason}</p>}
                      {names.length > 0 && (
                        <p className="text-xs text-gray-500">
                          <span className="font-medium">{t("exemptions.exempts_from")}:</span>{" "}
                          {names.join("، ")}
                        </p>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {!denied && (
        <div>
          <h3 className="font-semibold text-sm text-gray-700 dark:text-gray-200 mb-2">
            {t("exemptions.requests_title")} ({requests.length})
          </h3>
          {requests.length === 0 ? (
            <p className="text-sm text-gray-500" data-testid="exemption-requests-empty">
              {t("exemptions.requests_none")}
            </p>
          ) : (
            <ul className="space-y-2" data-testid="exemption-requests-list">
              {requests.map((request) => (
                <li
                  key={request.id}
                  className="border dark:border-gray-600 rounded p-3"
                  data-testid={`exemption-request-row-${request.id}`}
                >
                  <p
                    className="text-xs text-gray-500 mb-1 flex items-center gap-2"
                    data-testid={`exemption-request-status-${request.id}`}
                  >
                    <span>{t(`exemptions.request_status_${request.status}`)}</span>
                    <ApprovalStageIcons
                      request={{
                        ...request,
                        decision_by: request.decided_by,
                        decision_at: request.decided_at,
                        decision_note: request.decision_note,
                      }}
                    />
                  </p>
                  <p className="text-sm flex items-center gap-2" dir="ltr">
                    <span>
                      {request.start_date
                        ? formatDate(request.start_date)
                        : t("exemption_requests.start_date_pending_approval")}{" "}
                      →{" "}
                      {request.end_date ? formatDate(request.end_date) : t("exemptions.forever")}
                    </span>
                    {request.start_date && <DaysBadge start={request.start_date} end={request.end_date} />}
                  </p>
                  {request.reason && <p className="text-xs text-gray-500 mb-2">{request.reason}</p>}
                  {canManage &&
                    (request.status === "pending_commander" || request.status === "pending_duty_manager") && (
                      <div className="flex items-center gap-2">
                        {request.status === "pending_commander" && request.can_approve_commander_step && (
                          <button
                            className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                            onClick={() => void onApproveCommanderStep(request.id)}
                            data-testid={`exemption-request-approve-${request.id}`}
                          >
                            {t("exemptions.approve_commander_step")}
                          </button>
                        )}
                        {request.status === "pending_duty_manager" &&
                          canApproveDutyManagerStep &&
                          request.can_approve_duty_manager_step && (
                            <button
                              className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                              onClick={() => void onApproveDutyManagerStep(request.id)}
                              data-testid={`exemption-request-approve-${request.id}`}
                            >
                              {t("exemptions.approve_duty_manager_step")}
                            </button>
                          )}
                        <input
                          className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                          value={rejectNotes[request.id] ?? ""}
                          onChange={(event) =>
                            setRejectNotes((previous) => ({
                              ...previous,
                              [request.id]: event.target.value,
                            }))
                          }
                          placeholder={t("approvals.decision_note")}
                          data-testid={`exemption-request-reject-note-${request.id}`}
                        />
                        <button
                          className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                          disabled={!rejectNotes[request.id]}
                          onClick={() => void onRejectRequest(request.id)}
                          data-testid={`exemption-request-reject-${request.id}`}
                        >
                          {t("exemptions.reject")}
                        </button>
                      </div>
                    )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {canManage && (
        <form
          onSubmit={onGrant}
          className="space-y-3 pt-2 border-t dark:border-gray-600"
          data-testid="grant-form"
        >
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[12rem] flex-1">
              <Combobox
                items={activeTypes.map((type) => ({ id: type.id, name: type.name }))}
                value={typeId}
                onChange={(nextTypeId) => {
                  setTypeId(nextTypeId);
                  setGrantError(null);
                  setCommanderError(null);
                }}
                placeholder={t("exemptions.type")}
                testId="grant-type"
              />
            </div>
            <DateInput
              className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              value={start}
              onChange={setStart}
              max={!indefinite && end ? end : undefined}
              required
              showHolidays
              data-testid="grant-start"
            />
            <div className="flex items-center gap-2">
              <DateInput
                className={`border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 ${indefinite ? "opacity-40 cursor-not-allowed" : ""}`}
                value={indefinite ? "" : end}
                onChange={setEnd}
                min={start || undefined}
                disabled={indefinite}
                showHolidays
                data-testid="grant-end"
              />
              <label className="flex items-center gap-1 text-sm whitespace-nowrap cursor-pointer">
                <input
                  type="checkbox"
                  checked={indefinite}
                  onChange={(event) => {
                    setIndefinite(event.target.checked);
                    if (event.target.checked) setEnd("");
                  }}
                  data-testid="grant-indefinite"
                />
                {t("exemptions.forever")}
              </label>
            </div>
          </div>

          {!isCommanderGrant && (
            <div className="space-y-3">
              <input
                className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder={t("exemptions.reason")}
                data-testid="grant-reason"
              />
              <label className="flex items-center gap-2 text-sm cursor-pointer w-fit">
                <input
                  type="checkbox"
                  checked={isMedicalGrant}
                  disabled={lockedMedicalClassification}
                  onChange={(event) => setMedicalClassification(event.target.checked)}
                  data-testid="grant-medical-classification"
                />
                {t("exemptions.medical_classification")}
              </label>
              <div
                className={`rounded border-2 border-dashed p-3 space-y-2 ${isMedicalGrant ? "border-blue-300 dark:border-blue-700 bg-blue-50 dark:bg-blue-950" : "border-gray-200 dark:border-gray-600"}`}
              >
                <p className="text-xs">
                  {isMedicalGrant
                    ? t("exemption_requests.upload_required")
                    : t("exemption_requests.upload_optional")}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {t("exemption_requests.upload_hint")}
                </p>
                <input
                  type="file"
                  multiple
                  accept=".pdf,image/*"
                  data-testid="grant-files"
                  onChange={(event) => {
                    void onGrantFilesChange(event.target.files);
                    event.target.value = "";
                  }}
                />
                <span className="text-xs text-gray-400">
                  PDF, JPG, PNG, GIF · {t("exemption_requests.max_file_size")}
                </span>
                {grantFileValidationErrors.length > 0 && (
                  <div className="rounded p-2 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800">
                    <p className="text-xs font-medium text-red-700 dark:text-red-300">
                      {t("exemption_requests.file_too_large")}
                    </p>
                    <ul className="text-xs text-red-600 dark:text-red-400 mt-0.5 list-disc list-inside">
                      {grantFileValidationErrors.map((name) => (
                        <li key={name}>{name}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {grantFiles.length > 0 && (
                  <ul className="text-xs space-y-0.5">
                    {grantFiles.map((file, index) => (
                      <li key={`${file.name}-${index}`} className="flex items-center gap-2">
                        <span className="truncate max-w-52">{file.name}</span>
                        <button
                          type="button"
                          className="text-red-500"
                          onClick={() =>
                            setGrantFiles((previous) => previous.filter((_, fileIndex) => fileIndex !== index))
                          }
                        >
                          {t("team.remove")}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {isMedicalGrant && grantFiles.length === 0 && (
                  <p className="text-xs text-amber-600 dark:text-amber-400">
                    {t("exemption_requests.upload_required_hint")}
                  </p>
                )}
              </div>
              {grantError && <p className="text-sm text-red-600">{grantError}</p>}
              <button
                type="submit"
                disabled={regularSubmitDisabled}
                className="bg-indigo-600 text-white px-3 py-1 rounded disabled:opacity-50"
                data-testid="grant-submit"
              >
                {grantSubmitting ? t("app.loading") : t("exemptions.grant")}
              </button>
            </div>
          )}

          {isCommanderGrant && (
            <div className="space-y-3" dir="rtl">
              <p className="text-sm text-gray-600 dark:text-gray-300">
                {t("exemptions.commander_grant_warning")}
              </p>
              <textarea
                value={commanderReason}
                onChange={(event) => setCommanderReason(event.target.value)}
                placeholder={t("exemptions.commander_reason_placeholder")}
                className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                data-testid="commander-exemption-reason"
              />

              {canApplyImmediately && (
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={commanderEscalate}
                    onChange={(event) => {
                      setCommanderEscalate(event.target.checked);
                      if (!event.target.checked) setCommanderApplyImmediately(false);
                    }}
                    data-testid="commander-exemption-escalate-checkbox"
                  />
                  {t("exemptions.commander_escalate")}
                </label>
              )}

              {commanderEscalate && (
                <div className="space-y-2 pr-4 border-r-2 border-indigo-200 dark:border-indigo-700">
                  <select
                    value={commanderOfficialTypeId}
                    onChange={(event) => setCommanderOfficialTypeId(event.target.value)}
                    className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    data-testid="commander-exemption-official-type"
                  >
                    {officialExemptionTypes.map((type) => (
                      <option key={type.id} value={type.id}>
                        {type.name}
                      </option>
                    ))}
                  </select>
                  {canApplyImmediately && (
                    <label className="flex items-center gap-2 text-sm cursor-pointer">
                      <input
                        type="checkbox"
                        checked={commanderApplyImmediately}
                        onChange={(event) => setCommanderApplyImmediately(event.target.checked)}
                        data-testid="commander-exemption-apply-immediately-checkbox"
                      />
                      {t("exemptions.commander_apply_immediately")}
                    </label>
                  )}
                </div>
              )}

              {commanderError && <p className="text-sm text-red-600">{commanderError}</p>}
              <button
                type="button"
                onClick={openCommanderConfirm}
                disabled={grantSubmitting || !typeId || !start || !isDateRangeValid(start, end)}
                className="bg-blue-600 text-white rounded px-3 py-1 disabled:opacity-50"
                data-testid="commander-exemption-submit"
              >
                {t("exemptions.commander_submit")}
              </button>
            </div>
          )}
        </form>
      )}

      {showCommanderConfirm && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
          onClick={() => setShowCommanderConfirm(false)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-md w-full mx-4"
            dir="rtl"
            onClick={(event) => event.stopPropagation()}
          >
            <h4 className="font-bold text-lg mb-3">{t("exemptions.commander_confirm_title")}</h4>
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-4">
              {t("exemptions.commander_confirm_warning")}
            </p>
            <label className="flex items-center gap-2 text-sm cursor-pointer mb-4">
              <input
                type="checkbox"
                checked={commanderAcknowledged}
                onChange={(event) => setCommanderAcknowledged(event.target.checked)}
                data-testid="commander-exemption-ack-checkbox"
              />
              {t("exemptions.commander_acknowledgement")}
            </label>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowCommanderConfirm(false)}
                className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-600 dark:text-gray-300"
              >
                {t("common.cancel", { defaultValue: "ביטול" })}
              </button>
              <button
                onClick={() => void handleCommanderConfirm()}
                disabled={!commanderAcknowledged}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg disabled:opacity-40"
                data-testid="commander-exemption-confirm"
              >
                {t("common.confirm", { defaultValue: "אשר" })}
              </button>
            </div>
          </div>
        </div>
      )}

      {revokingId && (
        <ReasonPromptModal
          title={t("exemptions.revoke")}
          description={t("exemptions.revoke_active_warning")}
          variant="warning"
          onConfirm={(revokeReason) => onRevoke(revokingId, revokeReason)}
          onClose={() => setRevokingId(null)}
        />
      )}
    </div>
  );
}
