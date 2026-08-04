import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { cancelRangeEvent, createRangeEvent, decideRangeExcusal, deleteRangeEvent, excuseRangeAssignment, getRangeEvent, getRangeExcusalRequests, getRanges, CreateRangeEventBody, UpdateRangeEventBody, RangeEvent, RangeType, updateRangeEvent } from "../api/ranges";
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
import { listSoldiers } from "../api/soldiers";
import { RANGE_TYPE_LABELS, RANGE_EVENT_STATUS_LABELS } from "../utils/rangeLabels";

export default function RangesPage() {
  const [params] = useSearchParams();
  const [selected, setSelected] = useState<string | null>(params.get("event"));
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
  function toggleSelected(id: string) { setSelectedIds(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; }); }
  const qc = useQueryClient();
  const { user } = useAuth();
  const nodeId = user?.hierarchy_node_id ?? null;
  const manage = canPlan(user);
  const ranges = useQuery({ queryKey: queryKeys.ranges(), queryFn: () => getRanges(nodeId as string), enabled: !!nodeId });
  const event = useQuery({ queryKey: queryKeys.rangeEvent(selected as string), queryFn: () => getRangeEvent(selected as string), enabled: !!selected });
  const excusal = useQuery({ queryKey: queryKeys.rangeExcusalRequests(selected as string), queryFn: () => getRangeExcusalRequests(selected as string), enabled: !!selected && !!user?.is_duty_manager });
  const soldiers = useQuery({ queryKey: queryKeys.soldiers(), queryFn: listSoldiers });
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
  const invalidate = async (id?: string) => {
    await qc.invalidateQueries({ queryKey: queryKeys.ranges() });
    if (id) await qc.invalidateQueries({ queryKey: queryKeys.rangeEvent(id) });
  };
  async function create(body: CreateRangeEventBody) { await createRangeEvent(body); await invalidate(); }
  async function save(body: CreateRangeEventBody | UpdateRangeEventBody) {
    if (formEvent) await updateRangeEvent(formEvent.id, body);
    else {
      const createBody = body as CreateRangeEventBody;
      await create({ hierarchy_node_id: createBody.hierarchy_node_id, range_type: createBody.range_type, date: createBody.date, location: createBody.location, start_time: createBody.start_time, end_time: createBody.end_time, arrival_instructions: createBody.arrival_instructions, contact_name: createBody.contact_name, contact_phone: createBody.contact_phone, notes: createBody.notes, required_count: Number(createBody.required_count), reserve_count: Number(createBody.reserve_count) });
    }
    await invalidate(formEvent?.id);
  }
  async function attendance() { await invalidate(selected ?? undefined); }

  return <Layout><section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl" data-testid="ranges-page">
    <div className="flex flex-wrap justify-between items-center gap-2"><h1 className="text-xl font-semibold">מטווחים</h1>{manage && <button type="button" data-testid="create-event-button" onClick={() => setFormEvent(null)} className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700">מטווח חדש</button>}</div>
    {selectedIds.size > 0 && <div data-testid="range-bulk-action-bar" className="flex items-center gap-3 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 dark:border-indigo-800 dark:bg-indigo-950" dir="rtl"><span className="text-sm font-medium text-indigo-700 dark:text-indigo-300">{selectedIds.size} נבחרו</span></div>}
    <RangePlanningTable rows={rows} loading={ranges.isLoading} error={ranges.isError ? "טעינת המטווחים נכשלה" : undefined} selectedIds={selectedIds} onToggleSelect={toggleSelected} onRowClick={e => { setSelected(e.id); setEditAssignments(null); }} rowActions={e => <div className="flex gap-1 items-center"><button type="button" data-testid={`view-assignments-${e.id}`} onClick={async () => { const detail = await getRangeEvent(e.id); setEditAssignments(detail); }} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-600">📋 שיבוצים</button>{manage && e.status === "planned" && <><button type="button" data-testid={`edit-range-${e.id}`} onClick={() => setFormEvent(e)} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-300 hover:bg-blue-200 dark:hover:bg-blue-800">✏️ עריכה</button><button type="button" disabled={count(e, false) > 0 || count(e, true) > 0} data-testid={`delete-range-${e.id}`} onClick={async () => { if (!confirm("למחוק?")) return; setSelected(current => current === e.id ? null : current); await deleteRangeEvent(e.id); await invalidate(); }} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-800 disabled:opacity-40 disabled:cursor-not-allowed">🗑️ מחיקה</button><button type="button" data-testid={`cancel-range-${e.id}`} onClick={() => setCancelId(e.id)} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-800">🚫 ביטול</button></>}</div>} filters={<div className="flex flex-wrap gap-x-4 gap-y-2 items-center text-sm"><label className="flex items-center gap-2">מתאריך<input aria-label="מתאריך" type="date" value={from} onChange={e => setFrom(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" /></label><label className="flex items-center gap-2">עד תאריך<input aria-label="עד תאריך" type="date" value={to} onChange={e => setTo(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" /></label><label className="flex items-center gap-2">סוג<select aria-label="סוג" value={type} onChange={e => setType(e.target.value as RangeType | "")} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"><option value="">כל הסוגים</option>{Object.entries(RANGE_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><label className="flex items-center gap-2">סטטוס<select aria-label="סטטוס" value={status} onChange={e => setStatus(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"><option value="">כל הסטטוסים</option><option value="">כל הסטטוסים</option>{Object.entries(RANGE_EVENT_STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><label className="flex items-center gap-2">מילוי<select aria-label="מילוי" value={fill} onChange={e => setFill(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"><option value="">כל המצבים</option><option value="open">חסר</option><option value="full">מלא</option></select></label></div>} sort={<button type="button" onClick={() => setSortAsc(v => !v)} className="text-blue-600 dark:text-blue-400 hover:underline">מיון תאריך {sortAsc ? "↑" : "↓"}</button>} />
    {!editAssignments && formEvent === undefined && !cancelId && event.data && <EventDetailModal open title={event.data.location} subtitle={`${RANGE_TYPE_LABELS[event.data.range_type] ?? event.data.range_type} · ${event.data.date}`} onClose={() => { setSelected(null); setEditAssignments(null); }} metadata={[{ label: "סטטוס", value: RANGE_EVENT_STATUS_LABELS[event.data.status] ?? event.data.status }, { label: "שעות", value: `${event.data.start_time ?? "—"}–${event.data.end_time ?? "—"}` }]}><RangeDetailContent event={event.data} canManage={manage} canEditAttendance={event.data.can_edit_attendance} userId={user?.id} soldierName={names} excusalRequests={excusal.data} onExcuse={async (id, reason) => { await excuseRangeAssignment(event.data!.id, id, reason); await invalidate(event.data!.id); await qc.invalidateQueries({ queryKey: queryKeys.rangeExcusalRequests(event.data!.id) }); }} onDecide={async (id, approve) => { await decideRangeExcusal(event.data!.id, id, approve); await invalidate(event.data!.id); await qc.invalidateQueries({ queryKey: queryKeys.rangeExcusalRequests(event.data!.id) }); }} onAttendance={attendance} /></EventDetailModal>}
    {editAssignments && <RangeEditAssignmentsModal open event={editAssignments} soldiers={soldiers.data ?? []} canManage={manage} onClose={() => setEditAssignments(null)} onChanged={async () => { await invalidate(editAssignments.id); }} />}
    <RangeFormModal open={formEvent !== undefined} event={formEvent} hierarchyNodeId={nodeId ?? ""} onClose={() => setFormEvent(undefined)} onSubmit={save} /><RangeCancelDialog open={!!cancelId} onClose={() => setCancelId(null)} onConfirm={async reason => { if (cancelId) { await cancelRangeEvent(cancelId, reason); await invalidate(cancelId); } }} />
  </section></Layout>;
}
