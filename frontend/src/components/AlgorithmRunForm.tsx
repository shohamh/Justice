import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { SolverSettings, submitJob, getAlgorithmDefaults } from "../api/algorithm";
import { DutyShift, listShifts } from "../api/shifts";
import { DutyType } from "../api/dutyConfig";
import SubHierarchySelector from "./SubHierarchySelector";
import AlgorithmModeHelpModal from "./AlgorithmModeHelpModal";

interface Props {
  dutyTypes: DutyType[];
  onJobSubmitted: (jobId: string) => void;
  initialOverrides?: Record<string, number>;
}

const DEFAULT_SETTINGS: SolverSettings = {
  K: 8, T: 8, Wt: 14, R: 15, Wr: 28, alpha: 1.0, beta: 2.0, time_limit_seconds: 30,
};

function todayStr() {
  return new Date().toISOString().split("T")[0];
}

function thirtyDaysStr() {
  const d = new Date();
  d.setDate(d.getDate() + 30);
  return d.toISOString().split("T")[0];
}

const FILL_COLORS: Record<string, string> = {
  empty: "text-red-600 dark:text-red-400",
  partial: "text-amber-600 dark:text-amber-400",
  full: "text-green-600 dark:text-green-400",
};

export default function AlgorithmRunForm({ dutyTypes, onJobSubmitted, initialOverrides }: Props) {
  const { t } = useTranslation();
  const [dateFrom, setDateFrom] = useState(todayStr);
  const [dateTo, setDateTo] = useState(thirtyDaysStr);
  const [availableShifts, setAvailableShifts] = useState<DutyShift[]>([]);
  const [selectedShiftIds, setSelectedShiftIds] = useState<string[]>([]);
  const [mode, setMode] = useState<"draft" | "direct_publish">("draft");
  const [showModeHelp, setShowModeHelp] = useState(false);
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const [eligibleNodeIds, setEligibleNodeIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [search, setSearch] = useState("");
  const [filterDutyTypeId, setFilterDutyTypeId] = useState("");

  const typeName = (id: string) => dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8);
  const shiftLabel = (shift: DutyShift) =>
    `${typeName(shift.duty_type_id)} — ${shift.start_date} עד ${shift.end_date} (ראשי: ${shift.assigned_count}/${shift.required_count}, רזרבה: ${shift.reserve_assigned_count ?? 0})`;

  const loadShifts = useCallback(async () => {
    const ss = await listShifts({
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    });
    setAvailableShifts(ss.filter(s => s.fill_status !== "full"));
  }, [dateFrom, dateTo]);

  useEffect(() => {
    void loadShifts();
  }, [loadShifts]);

  useEffect(() => {
    void getAlgorithmDefaults()
      .then(d => setSettings(s => ({ ...s, T: d.T, Wt: d.Wt, R: d.R, Wr: d.Wr })))
      .catch(() => { /* keep hardcoded defaults if unavailable */ });
  }, []);

  useEffect(() => {
    if (initialOverrides && Object.keys(initialOverrides).length > 0) {
      setSettings(s => ({ ...s, ...initialOverrides }));
      setShowSettings(true);
    }
  }, [initialOverrides]);

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
      const apiMode = mode === "draft" ? "shadow" : "dm_reviewed";
      const resp = await submitJob({ shift_ids: selectedShiftIds, mode: apiMode, settings });
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
          <div className="flex items-center gap-3 mb-2 flex-wrap">
            <p className="font-medium">בחר משמרות להרצה</p>
            <button type="button" onClick={() => setSelectedShiftIds(availableShifts.map(s => s.id))} className="text-xs text-blue-600 dark:text-blue-400 hover:underline">בחר הכל</button>
            <button type="button" onClick={() => setSelectedShiftIds([])} className="text-xs text-blue-600 dark:text-blue-400 hover:underline">בטל בחירה</button>
          </div>
          <div className="flex gap-2 mb-2">
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={t("shifts.search_shifts")}
              className="flex-1 border rounded p-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            />
            <select
              value={filterDutyTypeId}
              onChange={e => setFilterDutyTypeId(e.target.value)}
              className="border rounded p-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            >
              <option value="">כל הסוגים</option>
              {dutyTypes.map(dt => <option key={dt.id} value={dt.id}>{dt.name}</option>)}
            </select>
          </div>
          <div className="space-y-1 max-h-48 overflow-y-auto border dark:border-gray-600 rounded p-2">
            {availableShifts
              .filter(s => !filterDutyTypeId || s.duty_type_id === filterDutyTypeId)
              .filter(s => !search || shiftLabel(s).includes(search))
              .map(shift => (
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
        <p className="text-sm text-gray-500 text-right" dir="rtl">
          לא נמצאו משמרות ללא שיבוץ בטווח התאריכים שנבחר.
        </p>
      )}

      <div className="flex items-center gap-2" dir="rtl">
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">מצב הרצה:</span>
        <div className="flex rounded border border-gray-300 dark:border-gray-600 overflow-hidden text-sm">
          <button
            type="button"
            className={`px-3 py-1 ${mode === "draft" ? "bg-indigo-600 text-white" : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300"}`}
            onClick={() => setMode("draft")}
          >
            מצב טיוטה
          </button>
          <button
            type="button"
            className={`px-3 py-1 ${mode === "direct_publish" ? "bg-indigo-600 text-white" : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300"}`}
            onClick={() => setMode("direct_publish")}
          >
            מצב פרסום ישיר
          </button>
        </div>
        <button
          type="button"
          className="text-gray-400 hover:text-indigo-600 text-xs font-bold border rounded-full w-5 h-5 flex items-center justify-center flex-shrink-0"
          onClick={() => setShowModeHelp(true)}
          title="מה ההבדל?"
        >
          ?
        </button>
        {showModeHelp && <AlgorithmModeHelpModal onClose={() => setShowModeHelp(false)} />}
      </div>

      <button type="button" className="text-xs text-blue-600 dark:text-blue-400 underline" onClick={() => setShowSettings(s => !s)}>
        {t("algorithm.settings")}
      </button>
      {showSettings && (
        <div className="grid grid-cols-3 gap-3 text-xs bg-gray-50 dark:bg-gray-700 p-3 rounded">
          {(["K", "T", "Wt", "R", "Wr", "alpha", "beta", "time_limit_seconds"] as const).map(key => (
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
