import { FormEvent, useEffect, useState } from "react";
import { EventDetailModal } from "../planning";
import { CreateRangeEventBody, RangeEvent, RangeType, UpdateRangeEventBody } from "../../api/ranges";
import { RANGE_TYPE_LABELS } from "../../utils/rangeLabels";

interface Props { open: boolean; event?: RangeEvent | null; hierarchyNodeId: string; onClose: () => void; onSubmit: (body: CreateRangeEventBody | UpdateRangeEventBody) => Promise<void>; }
export default function RangeFormModal({ open, event, hierarchyNodeId, onClose, onSubmit }: Props) {
  const [form, setForm] = useState({ range_type: "laser" as RangeType, date: "", start_time: "", end_time: "", location: "", arrival_instructions: "", contact_name: "", contact_phone: "", required_count: 0, reserve_count: 0, notes: "" });
  const [force, setForce] = useState(false); const [error, setError] = useState(""); const [pending, setPending] = useState(false);
  useEffect(() => { if (open) { setForce(false); setForm({ range_type: event?.range_type ?? "laser", date: event?.date ?? "", start_time: event?.start_time ?? "", end_time: event?.end_time ?? "", location: event?.location ?? "", arrival_instructions: event?.arrival_instructions ?? "", contact_name: event?.contact_name ?? "", contact_phone: event?.contact_phone ?? "", required_count: event?.required_count ?? 0, reserve_count: event?.reserve_count ?? 0, notes: event?.notes ?? "" }); } }, [open, event]);
  const set = (key: string, value: string | number) => setForm(prev => ({ ...prev, [key]: value }));
  async function submit(e: FormEvent) { e.preventDefault(); setError(""); if (form.start_time && form.end_time && form.start_time > form.end_time) { setError("שעת התחלה חייבת להיות לפני שעת הסיום"); return; } if (event && event.assignments.length > 0 && (form.date !== event.date || form.range_type !== event.range_type) && !force) { setError("שינוי תאריך או סוג דורש אישור מפורש"); return; } setPending(true); try { await onSubmit(event ? { ...form, start_time: form.start_time || null, end_time: form.end_time || null, arrival_instructions: form.arrival_instructions || null, contact_name: form.contact_name || null, contact_phone: form.contact_phone || null, notes: form.notes || null, required_count: Number(form.required_count), reserve_count: Number(form.reserve_count), force_schedule_change: force } : { hierarchy_node_id: hierarchyNodeId, ...form, start_time: form.start_time || null, end_time: form.end_time || null, arrival_instructions: form.arrival_instructions || null, contact_name: form.contact_name || null, contact_phone: form.contact_phone || null, notes: form.notes || null }); onClose(); } finally { setPending(false); } }
  const fields: Array<[string,string,"text"|"date"|"time"|"number"]> = [["date","תאריך","date"],["start_time","התחלה","time"],["end_time","סיום","time"],["location","מיקום","text"],["required_count","ראשיים","number"],["reserve_count","רזרבה","number"],["contact_name","איש קשר","text"],["contact_phone","טלפון","text"]];
  const inputClass = "mt-1 block w-full rounded border p-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100";
  return <EventDetailModal open={open} title={event ? "עריכת מטווח" : "מטווח חדש"} onClose={onClose}>
    <form onSubmit={submit} className="space-y-4" data-testid={event ? "range-form" : "create-event-form"}>
      <div data-testid="range-form-header" className="border-b pb-3">
        <p className="text-sm text-gray-500 dark:text-gray-400">פרטי המטווח והשיבוץ הנדרש</p>
      </div>
      <section data-testid="range-form-section-schedule" className="space-y-3">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-200">פרטי זמן ומיקום</h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block text-sm sm:col-span-2">סוג<select data-testid={event ? "edit-range-type" : "new-range-type"} value={form.range_type} onChange={e=>set("range_type",e.target.value)} className={inputClass}><option value="laser">{RANGE_TYPE_LABELS.laser}</option><option value="live">{RANGE_TYPE_LABELS.live}</option><option value="alal">{RANGE_TYPE_LABELS.alal}</option></select></label>
          {fields.slice(0, 6).map(([key,label,type])=><label key={key} className="block text-sm">{label}<input id={`${event ? "edit" : "new"}-${key.replace("_", "-")}`} data-testid={`${event ? "edit" : "new"}-${key.replace("_", "-")}`} type={type} value={form[key as keyof typeof form] as string|number} min={type === "number" ? 0 : undefined} onChange={e=>set(key,type === "number" ? Number(e.target.value) : e.target.value)} className={inputClass} /></label>)}
        </div>
      </section>
      <section data-testid="range-form-section-contact" className="space-y-3 border-t pt-4">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-200">פרטי קשר</h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{fields.slice(6).map(([key,label,type])=><label key={key} className="block text-sm">{label}<input id={`${event ? "edit" : "new"}-${key.replace("_", "-")}`} data-testid={`${event ? "edit" : "new"}-${key.replace("_", "-")}`} type={type} value={form[key as keyof typeof form] as string|number} min={type === "number" ? 0 : undefined} onChange={e=>set(key,type === "number" ? Number(e.target.value) : e.target.value)} className={inputClass} /></label>)}</div>
        <label className="block text-sm">הוראות הגעה<textarea value={form.arrival_instructions} onChange={e=>set("arrival_instructions",e.target.value)} className={inputClass} rows={3} /></label>
      </section>
      <section data-testid="range-form-section-notes" className="space-y-3 border-t pt-4">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-200">הערות</h4>
        <label className="block text-sm"><span className="sr-only">הערות</span><textarea aria-label="הערות" value={form.notes} onChange={e=>set("notes",e.target.value)} className={inputClass} rows={3} /></label>
      </section>
      {event && event.assignments.length > 0 && (form.date !== event.date || form.range_type !== event.range_type) && <label className="flex items-center gap-2 rounded border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-900/20"><input type="checkbox" checked={force} onChange={e=>setForce(e.target.checked)} />אני מאשר שינוי מועד/סוג עם שיבוצים</label>}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <div data-testid="range-form-footer" className="flex justify-end gap-2 border-t pt-4">
        <button type="button" onClick={onClose} className="rounded border px-4 py-2 text-sm dark:border-gray-600 dark:text-gray-100">ביטול</button>
        <button type="submit" disabled={pending} className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50">שמור</button>
      </div>
    </form>
  </EventDetailModal>;
}


