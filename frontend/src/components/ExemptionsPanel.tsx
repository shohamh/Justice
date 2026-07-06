import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ExemptionType, listExemptionTypes, getAllExemptionDutyTypeMaps, listDutyTypes } from "../api/dutyConfig";
import {
  Exemption, ExemptionRequest, grantExemption, listExemptions, revokeExemption,
  listExemptionRequestsForSoldier, approveExemptionRequestCommanderStep,
  approveExemptionRequestDutyManagerStep, rejectExemptionRequest,
} from "../api/exemptions";
import { formatDate } from "../utils/formatDate";
import Combobox from "./Combobox";
import CommanderExemptionGrantForm from "./CommanderExemptionGrantForm";

function daysBetween(start: string, end: string | null | undefined): number | null {
  if (!end) return null;
  const a = new Date(start);
  const b = new Date(end);
  return Math.round((b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24)) + 1;
}

function DaysBadge({ start, end }: { start: string; end: string | null | undefined }) {
  const days = daysBetween(start, end);
  if (days === null) return null;
  const cls =
    days > 90
      ? "text-red-600 dark:text-red-400"
      : days > 30
      ? "text-yellow-600 dark:text-yellow-400"
      : "text-gray-400 dark:text-gray-500";
  return <span className={`text-xs ${cls}`}>({days} ימים)</span>;
}

export default function ExemptionsPanel({ soldierId, canManage }: { soldierId: string; canManage: boolean }) {
  const { t } = useTranslation();
  const [items, setItems] = useState<Exemption[]>([]);
  const [types, setTypes] = useState<ExemptionType[]>([]);
  const [dutyTypeMap, setDutyTypeMap] = useState<Record<string, string[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [typeId, setTypeId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [indefinite, setIndefinite] = useState(false);
  const [reason, setReason] = useState("");
  const [requests, setRequests] = useState<ExemptionRequest[]>([]);
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    setItems(await listExemptions(soldierId));
  }, [soldierId]);
  const refreshRequests = useCallback(async () => {
    setRequests(await listExemptionRequestsForSoldier(soldierId));
  }, [soldierId]);
  useEffect(() => { void refreshRequests(); }, [refreshRequests]);
  useEffect(() => {
    void refresh();
    void (async () => {
      try {
        const etypes = await listExemptionTypes();
        setTypes(etypes);
      } catch { /* types stay empty on error */ }
      try {
        const [maps, dtypes] = await Promise.all([getAllExemptionDutyTypeMaps(), listDutyTypes()]);
        const nameById = Object.fromEntries(dtypes.map((d) => [d.id, d.name]));
        const named: Record<string, string[]> = {};
        for (const [etId, dtIds] of Object.entries(maps)) {
          named[etId] = dtIds.map((id) => nameById[id] ?? id);
        }
        setDutyTypeMap(named);
      } catch { /* duty-type map stays empty on error */ }
    })();
  }, [refresh]);

  const typeName = (id: string) => types.find((tp) => tp.id === id)?.name ?? "—";
  const commanderExemptionTypes = types.filter((tp) => tp.is_commander_exemption === true);
  const officialExemptionTypes = types.filter((tp) => tp.is_commander_exemption !== true);

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function onGrant(e: FormEvent) {
    e.preventDefault();
    await grantExemption(soldierId, {
      exemption_type_id: typeId,
      start_date: start,
      end_date: end || null,
      reason: reason || null,
    });
    setTypeId(""); setStart(""); setEnd(""); setIndefinite(false); setReason("");
    await refresh();
  }

  async function onRevoke(id: string) {
    if (!confirm(t("exemptions.revoke") + "?")) return;
    await revokeExemption(soldierId, id);
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
    setRejectNotes((prev) => { const next = { ...prev }; delete next[id]; return next; });
    await refreshRequests();
  }

  const today = new Date().toISOString().slice(0, 10);
  const activeItems = items.filter(
    (ex) => ex.end_date == null || ex.end_date >= today
  );
  const expiredItems = items.filter(
    (ex) => ex.end_date != null && ex.end_date < today
  );

  return (
    <div data-testid="exemptions-panel" className="space-y-4">
      {/* Active exemptions — card section */}
      <div>
        <h3 className="font-semibold text-sm text-gray-700 dark:text-gray-200 mb-2">
          {t("exemptions.title")} ({activeItems.length})
        </h3>
        {activeItems.length === 0 ? (
          <p className="text-sm text-gray-500" data-testid="exemptions-empty">
            {t("exemptions.none")}
          </p>
        ) : (
          <ul className="space-y-2" data-testid="exemptions-list">
            {activeItems.map((ex) => {
              const names = ex.exemption_type_id ? (dutyTypeMap[ex.exemption_type_id] ?? []) : [];
              const isExpanded = expanded.has(ex.id);
              return (
                <li
                  key={ex.id}
                  className="border border-indigo-200 dark:border-indigo-700 bg-indigo-50 dark:bg-indigo-950 rounded-lg p-3 cursor-pointer hover:bg-indigo-100 dark:hover:bg-indigo-900 transition-colors"
                  onClick={() => toggleExpand(ex.id)}
                  data-testid={`exemption-row-${ex.id}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-0.5">
                      <p className="font-medium text-sm text-indigo-900 dark:text-indigo-100">
                        {ex.exemption_type_id ? typeName(ex.exemption_type_id) : "מידע פרטי"}
                      </p>
                      <p className="text-xs text-indigo-700 dark:text-indigo-300">
                        {formatDate(ex.start_date)} → {ex.end_date ? formatDate(ex.end_date) : t("exemptions.forever")}
                      </p>
                      <DaysBadge start={ex.start_date} end={ex.end_date} />
                    </div>
                    {canManage && (
                      <button
                        className="text-red-500 text-xs shrink-0"
                        onClick={(e) => { e.stopPropagation(); void onRevoke(ex.id); }}
                        data-testid={`revoke-${ex.id}`}
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
                  {isExpanded && ex.reason && (
                    <p className="mt-1 text-xs text-indigo-600 dark:text-indigo-400">{ex.reason}</p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Expired / past exemptions */}
      {expiredItems.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">
            {t("exemptions.past")}
          </h4>
          <ul className="space-y-1 text-sm" data-testid="exemptions-list-past">
            {expiredItems.map((ex) => {
              const names = ex.exemption_type_id ? (dutyTypeMap[ex.exemption_type_id] ?? []) : [];
              const isExpanded = expanded.has(ex.id);
              return (
                <li
                  key={ex.id}
                  className="border dark:border-gray-600 rounded p-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 opacity-60"
                  onClick={() => toggleExpand(ex.id)}
                  data-testid={`exemption-row-${ex.id}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{ex.exemption_type_id ? typeName(ex.exemption_type_id) : "מידע פרטי"}</span>
                    <span className="text-gray-500 dark:text-gray-400 text-xs">
                      {formatDate(ex.start_date)} → {ex.end_date ? formatDate(ex.end_date) : ""}
                    </span>
                    {canManage && (
                      <button
                        className="text-red-500 text-xs mr-auto"
                        onClick={(e) => { e.stopPropagation(); void onRevoke(ex.id); }}
                        data-testid={`revoke-${ex.id}`}
                      >
                        {t("exemptions.revoke")}
                      </button>
                    )}
                  </div>
                  {isExpanded && (
                    <div className="mt-1.5 space-y-0.5">
                      {ex.reason && <p className="text-xs text-gray-500">{ex.reason}</p>}
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

      {/* Exemption request history */}
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
            {requests.map((req) => (
              <li
                key={req.id}
                className="border dark:border-gray-600 rounded p-3"
                data-testid={`exemption-request-row-${req.id}`}
              >
                <p className="text-xs text-gray-500 mb-1" data-testid={`exemption-request-status-${req.id}`}>
                  {t(`exemptions.request_status_${req.status}`)}
                </p>
                <p className="text-sm flex items-center gap-2" dir="ltr">
                  <span>{formatDate(req.start_date)} → {req.end_date ? formatDate(req.end_date) : t("exemptions.forever")}</span>
                </p>
                {req.reason && <p className="text-xs text-gray-500 mb-2">{req.reason}</p>}
                {canManage && (req.status === "pending_commander" || req.status === "pending_duty_manager") && (
                  <div className="flex items-center gap-2">
                    {req.status === "pending_commander" && (
                      <button
                        className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                        onClick={() => void onApproveCommanderStep(req.id)}
                        data-testid={`exemption-request-approve-${req.id}`}
                      >
                        {t("exemptions.approve_commander_step")}
                      </button>
                    )}
                    {req.status === "pending_duty_manager" && (
                      <button
                        className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                        onClick={() => void onApproveDutyManagerStep(req.id)}
                        data-testid={`exemption-request-approve-${req.id}`}
                      >
                        {t("exemptions.approve_duty_manager_step")}
                      </button>
                    )}
                    <input
                      className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                      value={rejectNotes[req.id] ?? ""}
                      onChange={(e) => setRejectNotes((prev) => ({ ...prev, [req.id]: e.target.value }))}
                      placeholder={t("approvals.decision_note")}
                      data-testid={`exemption-request-reject-note-${req.id}`}
                    />
                    <button
                      className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                      disabled={!rejectNotes[req.id]}
                      onClick={() => void onRejectRequest(req.id)}
                      data-testid={`exemption-request-reject-${req.id}`}
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

      {/* Grant form */}
      {canManage && (
        <form onSubmit={onGrant} className="flex flex-wrap items-end gap-2 pt-2 border-t dark:border-gray-600" data-testid="grant-form">
          <Combobox
            items={types.map(tp => ({ id: tp.id, name: tp.name }))}
            value={typeId}
            onChange={setTypeId}
            placeholder={t("exemptions.type")}
            testId="grant-type"
          />
          <input type="date" lang="he" className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={start} onChange={(e) => setStart(e.target.value)} required data-testid="grant-start" />
          <div className="flex items-center gap-2">
            <input
              type="date" lang="he"
              className={`border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 ${indefinite ? "opacity-40 cursor-not-allowed" : ""}`}
              value={indefinite ? "" : end}
              onChange={(e) => setEnd(e.target.value)}
              disabled={indefinite}
              data-testid="grant-end"
            />
            <label className="flex items-center gap-1 text-sm whitespace-nowrap cursor-pointer">
              <input
                type="checkbox"
                checked={indefinite}
                onChange={(e) => {
                  setIndefinite(e.target.checked);
                  if (e.target.checked) setEnd("");
                }}
                data-testid="grant-indefinite"
              />
              ללא הגבלת זמן
            </label>
          </div>
          <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("exemptions.reason")} data-testid="grant-reason" />
          <button type="submit" disabled={!typeId} className="bg-indigo-600 text-white px-3 py-1 rounded disabled:opacity-50" data-testid="grant-submit">{t("exemptions.grant")}</button>
        </form>
      )}

      {/* Commander exemption grant form */}
      {canManage && commanderExemptionTypes.length > 0 && (
        <CommanderExemptionGrantForm
          soldierId={soldierId}
          commanderExemptionTypes={commanderExemptionTypes.map((tp) => ({ id: tp.id, name: tp.name }))}
          officialExemptionTypes={officialExemptionTypes.map((tp) => ({ id: tp.id, name: tp.name }))}
          onGranted={() => { void refresh(); void refreshRequests(); }}
        />
      )}
    </div>
  );
}
