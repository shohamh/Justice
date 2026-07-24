import { FormEvent, useEffect, useState } from "react";
import {
  createExemptionType, ExemptionType, DutyType, DutyLocation,
  listDutyTypes, listLocations, setExemptionDutyTypes, setExemptionDutyLocations,
} from "../api/dutyConfig";

interface Props {
  onSaved: (et: ExemptionType) => void;
  onClose: () => void;
}

export default function ExemptionTypeFormModal({ onSaved, onClose }: Props) {
  const [name, setName] = useState("");
  const [isGlobal, setIsGlobal] = useState(false);
  const [isMedical, setIsMedical] = useState(false);
  const [isCommanderExemption, setIsCommanderExemption] = useState(false);
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
  const [locations, setLocations] = useState<DutyLocation[]>([]);
  const [selectedDutyTypeIds, setSelectedDutyTypeIds] = useState<string[]>([]);
  const [selectedLocationIds, setSelectedLocationIds] = useState<string[]>([]);
  const [dutyTypesReviewed, setDutyTypesReviewed] = useState(false);
  const [locationsReviewed, setLocationsReviewed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listDutyTypes().then(setDutyTypes);
    void listLocations().then(setLocations);
  }, []);

  const canSubmit = name.trim().length > 0 && dutyTypesReviewed && locationsReviewed && !saving;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    setError(null);
    try {
      const et = await createExemptionType({
        name, is_global: isGlobal, is_medical: isMedical, is_commander_exemption: isCommanderExemption,
      });
      if (selectedDutyTypeIds.length > 0) {
        await setExemptionDutyTypes(et.id, selectedDutyTypeIds);
      }
      if (selectedLocationIds.length > 0) {
        await setExemptionDutyLocations(et.id, selectedLocationIds);
      }
      onSaved(et);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-lg max-h-[90dvh] overflow-y-auto" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-base">הוספת סוג פטור</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="et-modal-name" className="block text-sm font-medium mb-1">שם *</label>
            <input id="et-modal-name" required autoFocus value={name} onChange={e => setName(e.target.value)}
              className="block w-full border border-gray-300 dark:border-gray-600 rounded-lg p-2 text-sm dark:bg-gray-700 dark:text-gray-100" />
          </div>

          <div className="flex gap-4">
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={isGlobal} onChange={e => setIsGlobal(e.target.checked)} /> גורף
            </label>
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={isMedical} onChange={e => setIsMedical(e.target.checked)} /> 🏥 רפואי
            </label>
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={isCommanderExemption} onChange={e => setIsCommanderExemption(e.target.checked)} /> 🎖️ פטור פיקודי
            </label>
          </div>

          <div className="border dark:border-gray-600 rounded p-3">
            <p className="text-sm font-medium mb-1">מאילו סוגי תורנות פוטר סוג פטור זה?</p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">חובה לעבור על הרשימה המלאה לפני יצירת סוג הפטור.</p>
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {dutyTypes.map(dt => (
                <label key={dt.id} className="flex items-center gap-2 text-xs">
                  <input type="checkbox" checked={selectedDutyTypeIds.includes(dt.id)}
                    onChange={() => setSelectedDutyTypeIds(prev =>
                      prev.includes(dt.id) ? prev.filter(x => x !== dt.id) : [...prev, dt.id]
                    )} />
                  {dt.name}
                </label>
              ))}
            </div>
            <label className="flex items-center gap-2 text-xs mt-2 font-medium">
              <input type="checkbox" checked={dutyTypesReviewed} onChange={e => setDutyTypesReviewed(e.target.checked)} />
              עברתי על רשימת סוגי התורנות ומאשר את הבחירה
            </label>
          </div>

          <div className="border dark:border-gray-600 rounded p-3">
            <p className="text-sm font-medium mb-1">מאילו מיקומי תורנות פוטר סוג פטור זה?</p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">חובה לעבור על הרשימה המלאה לפני יצירת סוג הפטור.</p>
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {locations.map(loc => (
                <label key={loc.id} className="flex items-center gap-2 text-xs">
                  <input type="checkbox" checked={selectedLocationIds.includes(loc.id)}
                    onChange={() => setSelectedLocationIds(prev =>
                      prev.includes(loc.id) ? prev.filter(x => x !== loc.id) : [...prev, loc.id]
                    )} />
                  {loc.name}
                </label>
              ))}
            </div>
            <label className="flex items-center gap-2 text-xs mt-2 font-medium">
              <input type="checkbox" checked={locationsReviewed} onChange={e => setLocationsReviewed(e.target.checked)} />
              עברתי על רשימת המיקומים ומאשר את הבחירה
            </label>
          </div>

          {error && <p className="text-red-500 text-xs">{error}</p>}

          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">ביטול</button>
            <button type="submit" disabled={!canSubmit} className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50">
              הוסף
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
