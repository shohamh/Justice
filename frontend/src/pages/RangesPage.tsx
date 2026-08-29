import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { cancelRangeEvent, createRangeEvent, decideRangeExcusal, deleteRangeEvent, excuseRangeAssignment, getRangeEvent, getRangeExcusalRequests, getRanges, removeRangeAssignment, CreateRangeEventBody, UpdateRangeEventBody, RangeEvent, RangeType, updateRangeEvent } from "../api/ranges";
import { queryKeys } from "../queryKeys";
import { useAuth } from "../auth/AuthContext";
import { canPlan } from "../auth/permissions";
import Layout from "../components/Layout";
import { EventDetailModal } from "../components/planning";
import RangePlanningTable from "../components/ranges/RangePlanningTable";
import RangeDetailContent from "../components/ranges/RangeDetailContent";
import RangeEditAssignmentsModal from "../components/ranges/RangeEditAssignmentsModal";
import RangeFormModal from "../components/ranges/RangeFormModal";
import RangeCancelDialog from "../components/ranges/RangeCancelDialog";
import RangeBulkCancelDialog from "../components/ranges/RangeBulkCancelDialog";
import RangeBulkAutoAssignModal from "../components/ranges/RangeBulkAutoAssignModal";
import ConfirmDialog from "../components/ranges/ConfirmDialog";
import { IneligibleSoldiersTable } from "../components/ranges/IneligibleSoldiersTable";
import RangeLocationsContent from "../components/ranges/RangeLocationsContent";
import { listSoldiers } from "../api/soldiers";
import { createRangeLocation, deleteRangeLocation, listRangeLocations, updateRangeLocation } from "../api/rangeLocations";
import { getIneligibleSoldiers } from "../api/ineligibleSoldiers";
import { RANGE_TYPE_LABELS, RANGE_EVENT_STATUS_LABELS } from "../utils/rangeLabels";
import { translateApiError } from "../utils/translateApiError";

export default function RangesPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState<string | null>(params.get("event"));
  const showIneligible = params.get("tab") === "ineligible";
  const showLocations = params.get("tab") === "locations";
  const showSchedule = !showIneligible && !showLocations;
  const [editAssignments, setEditAssignments] = useState<RangeEvent | null>(null);
  const [formEvent, setFormEvent] = useState<RangeEvent | null | undefined>(undefined);
  const [cancelId, setCancelId] = useState<string | null>(null);
  const [type, setType] = useState<RangeType | "">("");
  const [status, setStatus] = useState("");
  const [fill, setFill] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [sortAsc, setSortAsc] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkCancelOpen, setBulkCancelOpen] = useState(false);
  const [bulkDeleteConfirmOpen, setBulkDeleteConfirmOpen] = useState(false);
  const [bulkClearConfirmOpen, setBulkClearConfirmOpen] = useState(false);
  const [bulkAutoAssignOpen, setBulkAutoAssignOpen] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState("");
  function toggleSelected(id: string) {
    const selectedEvent = rows.find(event => event.id === id);
    if (selectedEvent?.can_manage === false) return;
    setSelectedIds(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }
  const qc = useQueryClient();
  const { user } = useAuth();
  const nodeId = user?.hierarchy_node_id ?? null;
  const manage = canPlan(user);
  const ranges = useQuery({ queryKey: queryKeys.ranges(), queryFn: () => getRanges(nodeId as string), enabled: !!nodeId && !showLocations });
  const ineligibleSoldiers = useQuery({ queryKey: queryKeys.ineligibleSoldiers("planning"), queryFn: () => getIneligibleSoldiers("planning"), enabled: showIneligible });
  const event = useQuery({ queryKey: queryKeys.rangeEvent(selected as string), queryFn: () => getRangeEvent(selected as string), enabled: !!selected });
  const excusal = useQuery({ queryKey: queryKeys.rangeExcusalRequests(selected as string), queryFn: () => getRangeExcusalRequests(selected as string), enabled: !!selected && !!user?.is_duty_manager });
  const soldiers = useQuery({ queryKey: queryKeys.soldiers(), queryFn: listSoldiers });
  const rangeLocations = useQuery({ queryKey: queryKeys.rangeLocations(), queryFn: listRangeLocations });
  const names = (id: string) => soldiers.data?.find(s => s.id === id)?.full_name ?? id;
  const count = (e: RangeEvent, reserve: boolean) => {
    const summary = reserve ? e.reserve_filled : e.primary_filled;
    if (e.assignments.length > 0) return e.assignments.filter(a => a.is_reserve === reserve && !a.is_draft).length;
    return summary ?? e.assignments.filter(a => a.is_reserve === reserve && !a.is_draft).length;
  };
  const rows = useMemo(() => {
    const visible = (ranges.data ?? []).filter(e =>
      (!type || e.range_type === type) && (!status || e.status === status) && (!from || e.date >= from) && (!to || e.date <= to) &&
      (fill === "" || (fill === "open" && (count(e, false) < e.required_count || count(e, true) < e.reserve_count)) || (fill === "full" && count(e, false) >= e.required_count && count(e, true) >= e.reserve_count)),
    );
    return visible.sort((a, b) => a.date.localeCompare(b.date) * (sortAsc ? 1 : -1));
  }, [ranges.data, type, status, fill, from, to, sortAsc]);
  const selectedEvents = useMemo(() => rows.filter(r => selectedIds.has(r.id)), [rows, selectedIds]);
  const invalidate = async (id?: string) => {
    await qc.invalidateQueries({ queryKey: queryKeys.ranges() });
    if (id) await qc.invalidateQueries({ queryKey: queryKeys.rangeEvent(id) });
  };
  const plannedSelectedEvents = useMemo(() => selectedEvents.filter(e => e.status === "planned"), [selectedEvents]);
  const manageablePlannedSelectedEvents = useMemo(
    () => plannedSelectedEvents.filter(e => e.can_manage !== false),
    [plannedSelectedEvents],
  );
  const todayIso = new Date().toISOString().slice(0, 10);
  const clearableSelectedEvents = useMemo(
    () => selectedEvents.filter(e => e.status === "planned" && e.date >= todayIso && e.can_manage !== false),
    [selectedEvents, todayIso],
  );
  const skippedClearEvents = selectedEvents.length - clearableSelectedEvents.length;
  const deletableCount = selectedEvents.filter(e => count(e, false) === 0 && count(e, true) === 0).length;
  async function bulkDelete() {
    const deletable = selectedEvents.filter(e => count(e, false) === 0 && count(e, true) === 0);
    setBulkBusy(true);
    setBulkError("");
    try {
      await Promise.allSettled(deletable.map(e => deleteRangeEvent(e.id)));
      setSelectedIds(new Set());
      await invalidate();
    } catch {
      setBulkError(t("ranges.errors.bulk_delete"));
    } finally {
      setBulkBusy(false);
      setBulkDeleteConfirmOpen(false);
    }
  }
  async function bulkCancel(reason: string) {
    const planned = plannedSelectedEvents;
    if (planned.length === 0) return;
    setBulkBusy(true);
    setBulkError("");
    try {
      await Promise.all(planned.map(e => cancelRangeEvent(e.id, reason)));
      setSelectedIds(new Set());
      await invalidate();
    } catch {
      setBulkError(t("ranges.errors.bulk_cancel"));
    } finally {
      setBulkBusy(false);
    }
  }
  async function bulkClear(reason: string) {
    if (clearableSelectedEvents.length === 0) {
      setBulkError(t("ranges.errors.bulk_clear_no_past", "לא ניתן לנקות שיבוצים ממטווחים שכבר התקיימו או שאינם מתוכננים."));
      return;
    }
    setBulkBusy(true);
    setBulkError("");
    try {
      const results = await Promise.allSettled(clearableSelectedEvents.map(async e => {
        const detail = await getRangeEvent(e.id);
        await Promise.all(detail.assignments.map(a => removeRangeAssignment(e.id, a.id, reason)));
        return e;
      }));
      const failures = results.flatMap((result, index) => result.status === "rejected"
        ? (() => {
          const reason = result.reason as { response?: { data?: { detail?: unknown } }; message?: string };
          const detail = reason.response?.data?.detail;
          const errorText = detail === "event_not_planned"
            ? t("ranges.errors.clear_event_not_planned", "לא ניתן לנקות מטווח שכבר התקיים או שאינו מתוכנן")
            : translateApiError(reason, t, reason.message ?? "שגיאה לא ידועה");
          return [`${clearableSelectedEvents[index].location} (${clearableSelectedEvents[index].date}): ${errorText}`];
        })()
        : []);
      if (failures.length > 0) {
        setBulkError(`${t("ranges.errors.bulk_clear_partial", "ניקוי השיבוצים הושלם חלקית. הכשלים:")} ${failures.join("; ")}`);
      } else {
        setSelectedIds(new Set());
      }
      await invalidate();
    } finally {
      setBulkBusy(false);
      setBulkClearConfirmOpen(false);
    }
  }
  async function create(body: CreateRangeEventBody) { await createRangeEvent(body); await invalidate(); }
  async function save(body: CreateRangeEventBody | UpdateRangeEventBody) {
    if (formEvent) await updateRangeEvent(formEvent.id, body);
    else {
      const createBody = body as CreateRangeEventBody;
      await create({ hierarchy_node_id: createBody.hierarchy_node_id, range_type: createBody.range_type, date: createBody.date, range_location_id: createBody.range_location_id, start_time: createBody.start_time, end_time: createBody.end_time, arrival_instructions: createBody.arrival_instructions, contact_name: createBody.contact_name, contact_phone: createBody.contact_phone, notes: createBody.notes, required_count: Number(createBody.required_count), reserve_count: Number(createBody.reserve_count) });
    }
    await invalidate(formEvent?.id);
  }
  async function attendance() { await invalidate(selected ?? undefined); }
  async function createLocation(name: string) { await createRangeLocation({ name }); await qc.invalidateQueries({ queryKey: queryKeys.rangeLocations() }); }
  async function updateLocation(id: string, input: { name?: string; active?: boolean }) { await updateRangeLocation(id, input); await qc.invalidateQueries({ queryKey: queryKeys.rangeLocations() }); }
  async function deleteLocation(id: string) { await deleteRangeLocation(id); await qc.invalidateQueries({ queryKey: queryKeys.rangeLocations() }); }

  return <Layout><section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl" data-testid="ranges-page">
    <div className="flex flex-wrap justify-between items-center gap-2"><h1 className="text-xl font-semibold">{t("ranges.page_title")}</h1><div className="flex items-center gap-3">{manage && <><Link to="/planning/export" className="text-indigo-600 hover:underline text-sm">{t("ranges.export_link")}</Link><Link to="/import" className="text-indigo-600 hover:underline text-sm">{t("ranges.import_link")}</Link></>}{showSchedule && manage && <button type="button" data-testid="create-event-button" onClick={() => setFormEvent(null)} className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700">{t("ranges.create_button")}</button>}</div></div>
     <div className="flex gap-2 border-b border-gray-200 dark:border-gray-700" role="tablist" aria-label={t("range_qualification.tablistLabel")}>
       <button type="button" role="tab" aria-selected={showSchedule} onClick={() => setParams(current => { const next = new URLSearchParams(current); next.delete("tab"); return next; })} className={`border-b-2 px-3 py-2 text-sm ${showSchedule ? "border-indigo-600 text-indigo-700 dark:text-indigo-300" : "border-transparent text-gray-600 dark:text-gray-300"}`}>{t("range_qualification.tabs.schedule")}</button>
       <button type="button" role="tab" aria-selected={showIneligible} onClick={() => setParams(current => { const next = new URLSearchParams(current); next.set("tab", "ineligible"); return next; })} className={`border-b-2 px-3 py-2 text-sm ${showIneligible ? "border-indigo-600 text-indigo-700 dark:text-indigo-300" : "border-transparent text-gray-600 dark:text-gray-300"}`}>{t("range_qualification.tabs.qualification")}</button>
       <button type="button" role="tab" aria-selected={showLocations} onClick={() => setParams(current => { const next = new URLSearchParams(current); next.set("tab", "locations"); return next; })} className={`border-b-2 px-3 py-2 text-sm ${showLocations ? "border-indigo-600 text-indigo-700 dark:text-indigo-300" : "border-transparent text-gray-600 dark:text-gray-300"}`}>מיקומי מטווחים</button>
    </div>
    {showIneligible && <IneligibleSoldiersTable data={ineligibleSoldiers.data} loading={ineligibleSoldiers.isLoading} error={ineligibleSoldiers.isError} />}
    {showLocations && <RangeLocationsContent locations={rangeLocations.data ?? []} loading={rangeLocations.isLoading} error={rangeLocations.isError} canManage={manage} onCreate={createLocation} onUpdate={updateLocation} onDelete={deleteLocation} />}
    <div className={showSchedule ? undefined : "hidden"}>
    {manage && selectedIds.size > 0 && <div data-testid="range-bulk-action-bar" className="flex flex-col gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 dark:border-indigo-800 dark:bg-indigo-950" dir="rtl">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-indigo-700 dark:text-indigo-300">{t("ranges.bulk_selected_count", { count: selectedIds.size })}</span>
        <button type="button" data-testid="bulk-clear-button" disabled={bulkBusy || clearableSelectedEvents.length === 0} onClick={() => setBulkClearConfirmOpen(true)} className="rounded bg-orange-500 px-3 py-1 text-sm font-medium text-white hover:bg-orange-600 disabled:opacity-40">{t("ranges.bulk_clear_button")}</button>
        <button type="button" data-testid="bulk-auto-assign-button" disabled={bulkBusy || manageablePlannedSelectedEvents.length === 0} onClick={() => setBulkAutoAssignOpen(true)} className="rounded bg-green-600 px-3 py-1 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-40">{t("ranges.bulk_auto_assign", "שיבוץ אוטומטי")}</button>
        <button type="button" data-testid="bulk-cancel-button" disabled={bulkBusy || plannedSelectedEvents.length === 0} onClick={() => setBulkCancelOpen(true)} className="rounded bg-amber-500 px-3 py-1 text-sm font-medium text-white hover:bg-amber-600 disabled:opacity-40">{t("ranges.bulk_cancel_button", { suffix: plannedSelectedEvents.length < selectedEvents.length ? ` (${plannedSelectedEvents.length})` : "" })}</button>
        <button type="button" data-testid="bulk-delete-button" disabled={bulkBusy} onClick={() => { if (deletableCount === 0) { setBulkError(t("ranges.bulk_delete_no_deletable")); return; } setBulkDeleteConfirmOpen(true); }} className="rounded bg-red-600 px-3 py-1 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-40">{t("ranges.bulk_delete_button")}</button>
      </div>
      {skippedClearEvents > 0 && <p className="text-sm text-amber-700 dark:text-amber-300">{t("ranges.bulk_clear_skipped_past", { count: skippedClearEvents, defaultValue: `לא ניתן לנקות מטווחים שכבר התקיימו או שאינם ניתנים לניהול (${skippedClearEvents}).` })}</p>}
      {bulkError && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{bulkError}</p>}
    </div>}
    <RangePlanningTable rows={rows} loading={ranges.isLoading} error={ranges.isError ? t("ranges.load_error") : undefined} selectedIds={manage ? selectedIds : undefined} onToggleSelect={manage ? toggleSelected : undefined} onRowClick={e => { setSelected(e.id); setEditAssignments(null); }} rowActions={e =><div className="flex gap-1 items-center"><button type="button" data-testid={`view-assignments-${e.id}`} onClick={async () => { const detail = await getRangeEvent(e.id); setEditAssignments(detail); }} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-600">{t("ranges.view_assignments_button")}</button>{manage && e.status === "planned" && <><button type="button" data-testid={`edit-range-${e.id}`} onClick={async () => { const detail = await getRangeEvent(e.id); setFormEvent(detail); }} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-300 hover:bg-blue-200 dark:hover:bg-blue-800">{t("ranges.edit_button")}</button><button type="button" disabled={count(e, false) > 0 || count(e, true) > 0} data-testid={`delete-range-${e.id}`} onClick={() => setDeleteConfirmId(e.id)} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-800 disabled:opacity-40 disabled:cursor-not-allowed">{t("ranges.delete_button")}</button><button type="button" data-testid={`cancel-range-${e.id}`} onClick={() => setCancelId(e.id)} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-800">{t("ranges.cancel_button")}</button></>}</div>} filters={<div className="flex flex-wrap gap-x-4 gap-y-2 items-center text-sm"><label className="flex items-center gap-2">{t("ranges.filter_from_date")}<input aria-label={t("ranges.filter_from_date")} type="date" value={from} onChange={e => setFrom(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" /></label><label className="flex items-center gap-2">{t("ranges.filter_to_date")}<input aria-label={t("ranges.filter_to_date")} type="date" value={to} onChange={e => setTo(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" /></label><label className="flex items-center gap-2">{t("ranges.filter_type_label")}<select aria-label={t("ranges.filter_type_label")} value={type} onChange={e => setType(e.target.value as RangeType | "")} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"><option value="">{t("ranges.filter_type_all")}</option>{Object.entries(RANGE_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><label className="flex items-center gap-2">{t("ranges.filter_status_label")}<select aria-label={t("ranges.filter_status_label")} value={status} onChange={e => setStatus(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"><option value="">{t("ranges.filter_status_all")}</option>{Object.entries(RANGE_EVENT_STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><label className="flex items-center gap-2">{t("ranges.filter_fill_label")}<select aria-label={t("ranges.filter_fill_label")} value={fill} onChange={e => setFill(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"><option value="">{t("ranges.filter_fill_all")}</option><option value="open">{t("ranges.filter_fill_open")}</option><option value="full">{t("ranges.filter_fill_full")}</option></select></label></div>} sort={<button type="button" onClick={() => setSortAsc(v => !v)} className="text-blue-600 dark:text-blue-400 hover:underline">{t("ranges.sort_by_date")} {sortAsc ? "↑" : "↓"}</button>} />
    </div>
    {!editAssignments && formEvent === undefined && !cancelId && event.data && <EventDetailModal open title={event.data.location} subtitle={`${RANGE_TYPE_LABELS[event.data.range_type] ?? event.data.range_type} · ${event.data.date}`} onClose={() => { setSelected(null); setEditAssignments(null); }} metadata={[{ label: t("ranges.metadata_status"), value: RANGE_EVENT_STATUS_LABELS[event.data.status] ?? event.data.status }, { label: t("ranges.metadata_hours"), value: `${event.data.start_time ?? "—"}–${event.data.end_time ?? "—"}` }]}><RangeDetailContent event={event.data} canManage={manage} isDutyManager={user?.role === "admin" || !!user?.is_duty_manager} canEditAttendance={event.data.can_edit_attendance} userId={user?.id} soldierName={names} excusalRequests={excusal.data} onExcuse={async (id, reason) => { await excuseRangeAssignment(event.data!.id, id, reason); await invalidate(event.data!.id); await qc.invalidateQueries({ queryKey: queryKeys.rangeExcusalRequests(event.data!.id) }); }} onDecide={async (id, approve) => { await decideRangeExcusal(event.data!.id, id, approve); await invalidate(event.data!.id); await qc.invalidateQueries({ queryKey: queryKeys.rangeExcusalRequests(event.data!.id) }); }} onAttendance={attendance} /></EventDetailModal>}
    {editAssignments && <RangeEditAssignmentsModal open event={editAssignments} soldiers={soldiers.data ?? []} canManage={manage} onClose={() => setEditAssignments(null)} onChanged={async () => { await invalidate(editAssignments.id); }} />}
    <RangeFormModal open={formEvent !== undefined} event={formEvent} hierarchyNodeId={nodeId ?? ""} locations={rangeLocations.data ?? []} onClose={() => setFormEvent(undefined)} onSubmit={save} /><RangeCancelDialog open={!!cancelId} onClose={() => setCancelId(null)} onConfirm={async reason => { if (cancelId) { await cancelRangeEvent(cancelId, reason); await invalidate(cancelId); } }} />
    <RangeBulkCancelDialog open={bulkCancelOpen} count={plannedSelectedEvents.length} onClose={() => setBulkCancelOpen(false)} onConfirm={bulkCancel} />
    <RangeBulkAutoAssignModal open={bulkAutoAssignOpen} events={manageablePlannedSelectedEvents} canManage={manage} onClose={() => setBulkAutoAssignOpen(false)} onChanged={invalidate} />
    <ConfirmDialog
      open={bulkDeleteConfirmOpen}
      title={t("ranges.confirm_bulk_delete_title")}
      message={t("ranges.confirm_bulk_delete_message", { count: deletableCount })}
      danger
      confirmLabel={t("ranges.confirm_delete_label")}
      onConfirm={() => void bulkDelete()}
      onClose={() => setBulkDeleteConfirmOpen(false)}
    />
    <ConfirmDialog
      open={bulkClearConfirmOpen}
      title={t("ranges.confirm_bulk_clear_title")}
      message={t("ranges.confirm_bulk_clear_message", { count: clearableSelectedEvents.length })}
      reasonLabel={t("ranges.confirm_bulk_clear_reason_label")}
      confirmLabel={t("ranges.confirm_bulk_clear_label")}
      danger
      onConfirm={(reason) => void bulkClear(reason ?? "")}
      onClose={() => setBulkClearConfirmOpen(false)}
    />
    <ConfirmDialog
      open={!!deleteConfirmId}
      title={t("ranges.confirm_single_delete_title")}
      message={t("ranges.confirm_single_delete_message")}
      danger
      confirmLabel={t("ranges.confirm_delete_label")}
      onConfirm={async () => {
        if (!deleteConfirmId) return;
        setSelected(current => current === deleteConfirmId ? null : current);
        await deleteRangeEvent(deleteConfirmId);
        await invalidate();
        setDeleteConfirmId(null);
      }}
      onClose={() => setDeleteConfirmId(null)}
    />
  </section></Layout>;
}
