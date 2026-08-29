import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { Edit2, Power, Trash2 } from "lucide-react";
import { RangeLocation } from "../../api/rangeLocations";
import ConfirmDialog from "../ConfirmDialog";

interface Props {
  locations: RangeLocation[];
  loading: boolean;
  error: boolean;
  canManage: boolean;
  onCreate: (name: string) => Promise<void>;
  onUpdate: (id: string, input: { name?: string; active?: boolean }) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

const deleteDisabledReason = "לא ניתן למחוק — המיקום כבר בשימוש במטווחים";

export default function RangeLocationsContent({ locations, loading, error, canManage, onCreate, onUpdate, onDelete }: Props) {
  const { t } = useTranslation();
  const text = (key: string, fallback: string, values?: Record<string, unknown>) => {
    const translated = t(key, { ...values, defaultValue: fallback });
    return translated === key ? fallback : translated;
  };
  const [name, setName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [tooltipId, setTooltipId] = useState<string | null>(null);
  const [formError, setFormError] = useState("");
  const [locationToDelete, setLocationToDelete] = useState<RangeLocation | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) { setFormError("יש להזין שם מיקום"); return; }
    setBusyId("new"); setFormError("");
    try { await onCreate(trimmedName); setName(""); } catch { setFormError("יצירת המיקום נכשלה"); } finally { setBusyId(null); }
  }

  async function saveName(location: RangeLocation) {
    const trimmedName = editingName.trim();
    if (!trimmedName) { setFormError("יש להזין שם מיקום"); return; }
    setBusyId(location.id); setFormError("");
    try { await onUpdate(location.id, { name: trimmedName }); setEditingId(null); } catch { setFormError("עדכון המיקום נכשל"); } finally { setBusyId(null); }
  }

  async function toggleActive(location: RangeLocation) {
    setBusyId(location.id); setFormError("");
    try { await onUpdate(location.id, { active: !location.active }); } catch { setFormError("עדכון מצב המיקום נכשל"); } finally { setBusyId(null); }
  }

  function remove(location: RangeLocation) {
    if (location.can_delete === false) { setTooltipId(location.id); return; }
    setLocationToDelete(location);
  }

  async function confirmRemove() {
    const location = locationToDelete;
    if (!location) return;
    setBusyId(location.id); setFormError("");
    try { await onDelete(location.id); } catch { setFormError("מחיקת המיקום נכשלה"); } finally { setBusyId(null); setLocationToDelete(null); }
  }

  return <>
  <div data-testid="range-locations-content" className="space-y-4" dir="rtl">
    <div><h2 className="text-lg font-semibold">מיקומי מטווחים</h2><p className="text-sm text-gray-500 dark:text-gray-400">ניהול המיקומים הזמינים בטפסי מטווחים</p></div>
    {canManage && <form onSubmit={submit} className="flex flex-wrap items-end gap-2"><label className="block text-sm">שם המיקום<input value={name} onChange={event => setName(event.target.value)} required maxLength={200} className="mt-1 block rounded border p-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100" /></label><button type="submit" disabled={busyId === "new"} className="rounded bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50">הוסף מיקום</button></form>}
    {formError && <p role="alert" className="text-sm text-red-600">{formError}</p>}
    {loading ? <p role="status" className="text-sm text-gray-500">טוען מיקומים...</p> : error ? <p role="alert" className="text-sm text-red-600">טעינת המיקומים נכשלה</p> : locations.length === 0 ? <p className="rounded-lg border border-dashed p-6 text-center text-sm text-gray-500">אין מיקומי מטווחים</p> : <ul className="divide-y rounded border dark:border-gray-700">{locations.map(location => {
      const deleteDisabled = location.can_delete === false;
      const isEditing = editingId === location.id;
      return <li key={location.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
        {isEditing ? <div className="flex min-w-0 flex-1 gap-2"><input aria-label="שם המיקום" value={editingName} onChange={event => setEditingName(event.target.value)} className="min-w-0 flex-1 rounded border p-1 text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100" /><button type="button" onClick={() => void saveName(location)} disabled={busyId === location.id} className="text-blue-600 hover:underline">שמור</button><button type="button" onClick={() => setEditingId(null)} className="text-gray-600 hover:underline">ביטול</button></div> : <span className="min-w-0 flex-1">{location.name}</span>}
        {canManage && !isEditing && <div className="flex shrink-0 items-center gap-1">
          <button type="button" aria-label="ערוך מיקום" title="ערוך מיקום" onClick={() => { setEditingId(location.id); setEditingName(location.name); setTooltipId(null); }} className="rounded p-1 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/30"><Edit2 size={16} /></button>
          <button type="button" aria-label={location.active ? "השבת מיקום" : "הפעל מיקום"} title={location.active ? "השבת מיקום" : "הפעל מיקום"} onClick={() => void toggleActive(location)} disabled={busyId === location.id} className="rounded p-1 text-amber-600 hover:bg-amber-50 disabled:opacity-40 dark:hover:bg-amber-900/30"><Power size={16} /></button>
          <span className="relative" title={deleteDisabled ? deleteDisabledReason : undefined} onClick={() => { if (deleteDisabled) setTooltipId(location.id); }}>
            <button type="button" aria-label="מחק מיקום" title={deleteDisabled ? deleteDisabledReason : "מחק מיקום"} onClick={() => void remove(location)} disabled={deleteDisabled || busyId === location.id} className="rounded p-1 text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40 dark:hover:bg-red-900/30"><Trash2 size={16} /></button>
            {tooltipId === location.id && deleteDisabled && <span role="tooltip" className="absolute bottom-full right-0 z-10 mb-1 w-56 rounded bg-gray-900 px-2 py-1 text-xs text-white shadow-lg">{deleteDisabledReason}</span>}
          </span>
        </div>}
        {!location.active && <span className="text-xs text-gray-500">לא פעיל</span>}
      </li>;
    })}</ul>}
  </div>
  <ConfirmDialog
    open={locationToDelete !== null}
    title={text("ranges.locations.confirm_delete_title", "מחיקת מיקום")}
    message={text("ranges.locations.confirm_delete_message", `למחוק את המיקום "${locationToDelete?.name ?? ""}"?`, { name: locationToDelete?.name ?? "" })}
    confirmLabel={text("ranges.confirm_delete_label", "מחק")}
    danger
    confirmDisabled={busyId === locationToDelete?.id}
    onConfirm={() => void confirmRemove()}
    onClose={() => setLocationToDelete(null)}
  />
  </>;
}
