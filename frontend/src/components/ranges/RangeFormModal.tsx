import { FormEvent, useEffect, useState } from "react";
import { EventDetailModal } from "../planning";
import { CreateRangeEventBody, RangeEvent, RangeType, UpdateRangeEventBody } from "../../api/ranges";
import { RangeLocation, createRangeLocation } from "../../api/rangeLocations";
import { RANGE_TYPE_LABELS } from "../../utils/rangeLabels";
import Combobox from "../Combobox";

interface Props { open: boolean; event?: RangeEvent | null; hierarchyNodeId: string; locations: RangeLocation[]; onClose: () => void; onSubmit: (body: CreateRangeEventBody | UpdateRangeEventBody) => Promise<void>; }
export default function RangeFormModal({ open, event, hierarchyNodeId, locations: initialLocations, onClose, onSubmit }: Props) {
  const [locations, setLocations] = useState<RangeLocation[]>(initialLocations);
  // RangeFormModal is mounted once (unconditionally) by RangesPage, before the
  // range-locations query resolves. Re-sync whenever the fetched list changes
  // so the Combobox isn't stuck showing the empty initial snapshot.
  useEffect(() => { setLocations(initialLocations); }, [initialLocations]);
  const [addingLocation, setAddingLocation] = useState(false);
  const [newLocName, setNewLocName] = useState("");
  const [locSaving, setLocSaving] = useState(false);
  const [form, setForm] = useState({ range_type: "laser" as RangeType, date: "", start_time: "", end_time: "", range_location_id: "", arrival_instructions: "", contact_name: "", contact_phone: "", required_count: 0, reserve_count: 0, notes: "" });
  const [force, setForce] = useState(false); const [error, setError] = useState(""); const [pending, setPending] = useState(false);
  useEffect(() => { if (open) { setForce(false); setError(""); setAddingLocation(false); setNewLocName(""); setForm({ range_type: event?.range_type ?? "laser", date: event?.date ?? "", start_time: event?.start_time ?? "", end_time: event?.end_time ?? "", range_location_id: event?.range_location_id ?? "", arrival_instructions: event?.arrival_instructions ?? "", contact_name: event?.contact_name ?? "", contact_phone: event?.contact_phone ?? "", required_count: event?.required_count ?? 0, reserve_count: event?.reserve_count ?? 0, notes: event?.notes ?? "" }); } }, [open, event]);
  const set = (key: string, value: string | number) => setForm(prev => ({ ...prev, [key]: value }));
  async function handleAddLocation(e: FormEvent) {
    e.preventDefault();
    if (!newLocName.trim()) return;
    setLocSaving(true);
    try {
      const created = await createRangeLocation({ name: newLocName.trim() });
      setLocations(prev => [...prev, created]);
      set("range_location_id", created.id);
      setNewLocName("");
      setAddingLocation(false);
    } finally {
      setLocSaving(false);
    }
  }
  async function submit(e: FormEvent) { e.preventDefault(); setError(""); if (form.start_time && form.end_time && form.start_time > form.end_time) { setError("שעת התחלה חייבת להיות לפני שעת הסיום"); return; } if (event && event.assignments.length > 0 && (form.date !== event.date || form.range_type !== event.range_type) && !force) { setError("שינוי תאריך או סוג דורש אישור מפורש"); return; } setPending(true); try { await onSubmit(event ? { ...form, start_time: form.start_time || null, end_time: form.end_time || null, arrival_instructions: form.arrival_instructions || null, contact_name: form.contact_name || null, contact_phone: form.contact_phone || null, notes: form.notes || null, required_count: Number(form.required_count), reserve_count: Number(form.reserve_count), force_schedule_change: force } : { hierarchy_node_id: hierarchyNodeId, ...form, start_time: form.start_time || null, end_time: form.end_time || null, arrival_instructions: form.arrival_instructions || null, contact_name: form.contact_name || null, contact_phone: form.contact_phone || null, notes: form.notes || null }); onClose(); } catch { setError("שמירת המטווח נכשלה"); } finally { setPending(false); } }
  const fields: Array<[string,string,"text"|"date"|"time"|"number"]> = [["date","תאריך","date"],["start_time","התחלה","time"],["end_time","סיום","time"],["required_count","ראשיים","number"],["reserve_count","רזרבה","number"],["contact_name","איש קשר","text"],["contact_phone","טלפון","text"]];
  const inputClass = "mt-1 block w-full rounded border p-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100";
  return <EventDetailModal open={open} title={event ? "עריכת מטווח" : "מטווח חדש"} onClose={onClose}>
    <form onSubmit={submit} className="space-y-4" data-testid={event ? "range-form" : "create-event-form"}>
      <div data-testid="range-form-header" className="border-b pb-3">
        <p className="text-sm text-gray-500 dark:text-gray-400">פרטי המטווח והשיבוץ הנדרש</p>
      </div>
      <section data-testid="range-form-section-schedule" className="space-y-3">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-200">פרטי זמן ומיקום</h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block text-sm sm:col-span-2">סוג<select data-testid={event ? "edit-range-type" : "new-range-type"} value={form.range_type} onChange={e=>set("range_type",e.target.value)} className={inputClass}><option value="laser">{RANGE_TYPE_LABELS.laser}</option><option value="live">{RANGE_TYPE_LABELS.live}</option><option value="alal">{RANGE_TYPE_LABELS.alal}</option></select></label>
          <div className="block text-sm sm:col-span-2">
            <div className="flex items-center justify-between mb-1">
              <span>מיקום</span>
              {!addingLocation && (
                <button type="button" onClick={() => setAddingLocation(true)} className="text-xs text-blue-600 dark:text-blue-400 hover:underline">
                  + הוסף מיקום
                </button>
              )}
            </div>
            {addingLocation ? (
              <form onSubmit={handleAddLocation} className="flex gap-1">
                <input
                  autoFocus
                  type="text"
                  value={newLocName}
                  onChange={e => setNewLocName(e.target.value)}
                  placeholder="שם המיקום"
                  className={inputClass}
                />
                <button type="submit" disabled={locSaving || !newLocName.trim()} className="px-2 py-1 text-xs bg-blue-600 text-white rounded disabled:opacity-50">
                  שמור
                </button>
                <button type="button" onClick={() => { setAddingLocation(false); setNewLocName(""); }} className="px-2 py-1 text-xs border dark:border-gray-600 dark:text-gray-300 rounded">
                  בטל
                </button>
              </form>
            ) : (
              <Combobox
                testId={event ? "edit-range-location" : "new-range-location"}
                items={locations.map(l => ({ id: l.id, name: l.name }))}
                value={form.range_location_id}
                onChange={v => set("range_location_id", v)}
                placeholder="בחר מיקום"
              />
            )}
          </div>
          {fields.slice(0, 5).map(([key,label,type])=><label key={key} className="block text-sm">{label}<input id={`${event ? "edit" : "new"}-${key.replace("_", "-")}`} data-testid={`${event ? "edit" : "new"}-${key.replace("_", "-")}`} type={type} value={form[key as keyof typeof form] as string|number} min={type === "number" ? 0 : undefined} onChange={e=>set(key,type === "number" ? Number(e.target.value) : e.target.value)} className={inputClass} /></label>)}
        </div>
      </section>
      <section data-testid="range-form-section-contact" className="space-y-3 border-t pt-4">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-200">פרטי קשר</h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{fields.slice(5).map(([key,label,type])=><label key={key} className="block text-sm">{label}<input id={`${event ? "edit" : "new"}-${key.replace("_", "-")}`} data-testid={`${event ? "edit" : "new"}-${key.replace("_", "-")}`} type={type} value={form[key as keyof typeof form] as string|number} min={type === "number" ? 0 : undefined} onChange={e=>set(key,type === "number" ? Number(e.target.value) : e.target.value)} className={inputClass} /></label>)}</div>
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


