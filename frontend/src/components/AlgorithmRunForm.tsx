import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { SolverSettings, submitJob } from "../api/algorithm";
import { DutyShift, listShifts } from "../api/shifts";
import { DutyType } from "../api/dutyConfig";
import SubHierarchySelector from "./SubHierarchySelector";

interface Props {
  dutyTypes: DutyType[];
  onJobSubmitted: (jobId: string) => void;
}

const DEFAULT_SETTINGS: SolverSettings = {
  K: 8, T: 7, W: 14, alpha: 1.0, beta: 2.0, time_limit_seconds: 30,
};

const FILL_COLORS: Record<string, string> = {
  empty: "text-red-600",
  partial: "text-amber-600",
  full: "text-green-600",
};

export default function AlgorithmRunForm({ dutyTypes, onJobSubmitted }: Props) {
  const { t } = useTranslation();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [availableShifts, setAvailableShifts] = useState<DutyShift[]>([]);
  const [selectedShiftIds, setSelectedShiftIds] = useState<string[]>([]);
  const [mode, setMode] = useState<"shadow" | "dm_reviewed">("shadow");
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const [eligibleNodeIds, setEligibleNodeIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const typeName = (id: string) => dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8);
  const shiftLabel = (shift: DutyShift) =>
    `${typeName(shift.duty_type_id)} — ${shift.start_date} עד ${shift.end_date} (${shift.assigned_count}/${shift.required_count})`;

  const loadShifts = useCallback(async () => {
    const ss = await listShifts({
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    });
    setAvailableShifts(ss.filter(s => s.fill_status !== "full"));
  }, [dateFrom, dateTo]);

  useEffect(() => {
    if (dateFrom || dateTo) void loadShifts();
    else setAvailableShifts([]);
  }, [loadShifts, dateFrom, dateTo]);

  function toggleShift(id: string) {
    setSelectedShiftIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  }

  async function handleSubmit() {
    setError(null);
    if (selectedShiftIds.length === 0) {
      setError("נא לבחור לפחות משמרת אחת");
      return;
    }
    setSubmitting(true);
    try {
      const resp = await submitJob({ shift_ids: selectedShiftIds, mode, settings });
      onJobSubmitted(resp.id);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה בשליחת הבקשה");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4 text-sm" dir="rtl">
      <div className="grid grid-cols-2 gap-4">
        <label className="block">
          {t("shifts.filter_from")}
          <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
        </label>
        <label className="block">
          {t("shifts.filter_to")}
          <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
        </label>
      </div>

      {availableShifts.length > 0 && (
        <div>
          <div className="flex items-center gap-3 mb-1">
            <p className="font-medium">בחר משמרות להרצה</p>
            <button type="button" onClick={() => setSelectedShiftIds(availableShifts.map(s => s.id))} className="text-xs text-blue-600 hover:underline">בחר הכל</button>
            <button type="button" onClick={() => setSelectedShiftIds([])} className="text-xs text-blue-600 hover:underline">בטל בחירה</button>
          </div>
          <div className="space-y-1 max-h-48 overflow-y-auto border dark:border-gray-600 rounded p-2">
            {availableShifts.map(shift => (
              <label key={shift.id} className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={selectedShiftIds.includes(shift.id)}
                  onChange={() => toggleShift(shift.id)}
                />
                <span className={FILL_COLORS[shift.fill_status]}>{shiftLabel(shift)}</span>
              </label>
            ))}
          </div>
        </div>
      )}
      {availableShifts.length === 0 && (
        <p className="text-gray-400">
          {dateFrom || dateTo ? "אין משמרות פתוחות בטווח הנבחר" : "הזן טווח תאריכים לצפייה במשמרות"}
        </p>
      )}

      <label className="block">
        {t("algorithm.mode_label")}
        <select value={mode} onChange={e => setMode(e.target.value as "shadow" | "dm_reviewed")} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100">
          <option value="shadow">{t("algorithm.shadow_mode")}</option>
          <option value="dm_reviewed">{t("algorithm.dm_reviewed_mode")}</option>
        </select>
      </label>

      <button type="button" className="text-xs text-blue-600 underline" onClick={() => setShowSettings(s => !s)}>
        {t("algorithm.settings")}
      </button>
      {showSettings && (
        <div className="grid grid-cols-3 gap-3 text-xs bg-gray-50 dark:bg-gray-700 p-3 rounded">
          {(["K", "T", "W", "alpha", "beta", "time_limit_seconds"] as const).map(key => (
            <label key={key} className="block">
              {key}
              <input
                type="number"
                value={settings[key]}
                onChange={e => setSettings(s => ({ ...s, [key]: parseFloat(e.target.value) }))}
                className="mt-1 block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                step={key === "alpha" || key === "beta" ? 0.1 : 1}
              />
            </label>
          ))}
        </div>
      )}

      <details className="border dark:border-gray-600 rounded p-2">
        <summary className="cursor-pointer">{t("algorithm.restrict_to_subtree")}</summary>
        <SubHierarchySelector value={eligibleNodeIds} onChange={setEligibleNodeIds} />
      </details>

      {error && <p className="text-red-500">{error}</p>}

      <button
        onClick={handleSubmit}
        disabled={submitting || selectedShiftIds.length === 0}
        type="button"
        className="w-full bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
      >
        {t("algorithm.run_button")} {selectedShiftIds.length > 0 && `(${selectedShiftIds.length} משמרות)`}
      </button>
    </div>
  );
}
