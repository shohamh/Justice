import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CreateShiftInput, DutyShift, createShift, updateShift } from "../api/shifts";
import { DutyType, DutyLocation } from "../api/dutyConfig";

interface Props {
  dutyTypes: DutyType[];
  locations: DutyLocation[];
  existing?: DutyShift;
  onSaved: () => void;
  onClose: () => void;
}

export default function ShiftFormModal({ dutyTypes, locations, existing, onSaved, onClose }: Props) {
  const { t } = useTranslation();
  const [dtId, setDtId] = useState(existing?.duty_type_id ?? dutyTypes[0]?.id ?? "");
  const [locId, setLocId] = useState(existing?.duty_location_id ?? locations[0]?.id ?? "");
  const [startDate, setStartDate] = useState(existing?.start_date ?? "");
  const [endDate, setEndDate] = useState(existing?.end_date ?? "");
  const [count, setCount] = useState(existing?.required_count ?? 1);
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      if (existing) {
        await updateShift(existing.id, {
          start_date: startDate,
          end_date: endDate,
          required_count: count,
          notes: notes || null,
        });
      } else {
        const input: CreateShiftInput = {
          duty_type_id: dtId,
          duty_location_id: locId,
          start_date: startDate,
          end_date: endDate,
          required_count: count,
          notes: notes || null,
        };
        await createShift(input);
      }
      onSaved();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">{existing ? t("shifts.edit") : t("shifts.create")}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          {!existing && (
            <>
              <label className="block text-sm">
                {t("shifts.duty_type")}
                <select value={dtId} onChange={e => setDtId(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm">
                  {dutyTypes.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </label>
              <label className="block text-sm">
                {t("shifts.location")}
                <select value={locId} onChange={e => setLocId(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm">
                  {locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </label>
            </>
          )}
          <label className="block text-sm">
            {t("shifts.start_date")}
            <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" required />
          </label>
          <label className="block text-sm">
            {t("shifts.end_date")}
            <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" required />
          </label>
          <label className="block text-sm">
            {t("shifts.required_count")}
            <input type="number" min={1} value={count} onChange={e => setCount(parseInt(e.target.value))} className="mt-1 block w-full border rounded p-1 text-sm" required />
          </label>
          <label className="block text-sm">
            {t("shifts.notes")}
            <textarea value={notes} onChange={e => setNotes(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" rows={2} />
          </label>
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded">ביטול</button>
            <button type="submit" className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">שמור</button>
          </div>
        </form>
      </div>
    </div>
  );
}
