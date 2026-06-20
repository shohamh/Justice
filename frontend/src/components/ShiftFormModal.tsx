import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CreateShiftInput, DutyShift, createShift, updateShift } from "../api/shifts";
import { DutyType, DutyLocation, createLocation } from "../api/dutyConfig";
import Combobox from "./Combobox";

interface Props {
  dutyTypes: DutyType[];
  locations: DutyLocation[];
  existing?: DutyShift;
  onSaved: () => void | Promise<void>;
  onClose: () => void;
}

export default function ShiftFormModal({ dutyTypes, locations: initialLocations, existing, onSaved, onClose }: Props) {
  const { t } = useTranslation();
  const [locations, setLocations] = useState<DutyLocation[]>(initialLocations);
  const [dtId, setDtId] = useState(existing?.duty_type_id ?? dutyTypes[0]?.id ?? "");
  const [locId, setLocId] = useState(existing?.duty_location_id ?? initialLocations[0]?.id ?? "");
  const [startDate, setStartDate] = useState(existing?.start_date ?? "");
  const [endDate, setEndDate] = useState(existing?.end_date ?? "");
  const [count, setCount] = useState(existing?.required_count ?? 1);
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [reserveOverride, setReserveOverride] = useState(existing?.reserve_count_override?.toString() ?? "");
  const [error, setError] = useState<string | null>(null);
  const [addingLocation, setAddingLocation] = useState(false);
  const [newLocName, setNewLocName] = useState("");
  const [locSaving, setLocSaving] = useState(false);

  async function handleAddLocation(e: React.FormEvent) {
    e.preventDefault();
    if (!newLocName.trim()) return;
    setLocSaving(true);
    try {
      const created = await createLocation({ name: newLocName.trim() });
      setLocations(prev => [...prev, created]);
      setLocId(created.id);
      setNewLocName("");
      setAddingLocation(false);
    } finally {
      setLocSaving(false);
    }
  }

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
          reserve_count_override: reserveOverride === "" ? null : parseInt(reserveOverride),
        });
      } else {
        const input: CreateShiftInput = {
          duty_type_id: dtId,
          duty_location_id: locId,
          start_date: startDate,
          end_date: endDate,
          required_count: count,
          notes: notes || null,
          reserve_count_override: reserveOverride === "" ? null : parseInt(reserveOverride),
        };
        await createShift(input);
      }
      await onSaved();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">{existing ? t("shifts.edit") : t("shifts.create")}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          {!existing && (
            <>
              <div>
                <span className="text-sm block mb-0.5">{t("shifts.duty_type")}</span>
                <Combobox items={dutyTypes} value={dtId} onChange={setDtId} />
              </div>
              <div className="block text-sm">
                <div className="flex items-center justify-between mb-1">
                  <span>{t("shifts.location")}</span>
                  {!addingLocation && (
                    <button type="button" onClick={() => setAddingLocation(true)} className="text-xs text-blue-600 dark:text-blue-400 hover:underline">
                      + {t("shifts.add_location")}
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
                      placeholder={t("shifts.location_name")}
                      className="flex-1 border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    />
                    <button type="submit" disabled={locSaving || !newLocName.trim()} className="px-2 py-1 text-xs bg-blue-600 text-white rounded disabled:opacity-50">
                      {t("shifts.save")}
                    </button>
                    <button type="button" onClick={() => { setAddingLocation(false); setNewLocName(""); }} className="px-2 py-1 text-xs border dark:border-gray-600 dark:text-gray-300 rounded">
                      {t("shifts.dismiss")}
                    </button>
                  </form>
                ) : (
                  <Combobox items={locations} value={locId} onChange={setLocId} />
                )}
              </div>
            </>
          )}
          <label className="block text-sm">
            {t("shifts.start_date")}
            <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" required />
          </label>
          <label className="block text-sm">
            {t("shifts.end_date")}
            <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" required />
          </label>
          <label className="block text-sm">
            {t("shifts.required_count")}
            <input type="number" min={1} value={count} onChange={e => setCount(parseInt(e.target.value))} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" required />
          </label>
          <label className="block text-sm">
            {t("shifts.notes")}
            <textarea value={notes} onChange={e => setNotes(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" rows={2} />
          </label>
          <label className="block text-sm">
            {t("reserve_count_override")}
            <input type="number" min="0" step="1" value={reserveOverride} onChange={e => setReserveOverride(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" placeholder={existing?.calculated_reserve_count?.toString() ?? ""} />
            {existing?.calculated_reserve_count != null && (
              <span className="text-xs text-gray-500">({t("reserve_calculated_count")}: {existing.calculated_reserve_count})</span>
            )}
          </label>
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">{t("shifts.cancel")}</button>
            <button type="submit" className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">{t("shifts.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
