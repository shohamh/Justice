import { FormEvent, useState } from "react";
import { RangeLocation } from "../../api/rangeLocations";

interface Props { locations: RangeLocation[]; loading: boolean; error: boolean; canManage: boolean; onCreate: (name: string) => Promise<void>; }

export default function RangeLocationsContent({ locations, loading, error, canManage, onCreate }: Props) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) { setFormError("יש להזין שם מיקום"); return; }
    setSaving(true); setFormError("");
    try { await onCreate(trimmedName); setName(""); } catch { setFormError("יצירת המיקום נכשלה"); } finally { setSaving(false); }
  }
  return <div data-testid="range-locations-content" className="space-y-4" dir="rtl">
    <div><h2 className="text-lg font-semibold">מיקומי מטווחים</h2><p className="text-sm text-gray-500 dark:text-gray-400">ניהול המיקומים הזמינים בטפסי מטווחים</p></div>
    {canManage && <form onSubmit={submit} className="flex flex-wrap items-end gap-2"><label className="block text-sm">שם המיקום<input value={name} onChange={event => setName(event.target.value)} required maxLength={200} className="mt-1 block rounded border p-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100" /></label><button type="submit" disabled={saving} className="rounded bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50">הוסף מיקום</button></form>}
    {formError && <p role="alert" className="text-sm text-red-600">{formError}</p>}
    {loading ? <p role="status" className="text-sm text-gray-500">טוען מיקומים...</p> : error ? <p role="alert" className="text-sm text-red-600">טעינת המיקומים נכשלה</p> : locations.length === 0 ? <p className="rounded-lg border border-dashed p-6 text-center text-sm text-gray-500">אין מיקומי מטווחים</p> : <ul className="divide-y rounded border dark:border-gray-700">{locations.map(location => <li key={location.id} className="flex items-center justify-between px-3 py-2 text-sm"><span>{location.name}</span>{!location.active && <span className="text-xs text-gray-500">לא פעיל</span>}</li>)}</ul>}
  </div>;
}
