import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { SolverSettings, submitJob, getAlgorithmDefaults } from "../api/algorithm";
import { DutyShift, listShifts } from "../api/shifts";
import { DutyType } from "../api/dutyConfig";
import SubHierarchySelector from "./SubHierarchySelector";
import AlgorithmModeHelpModal from "./AlgorithmModeHelpModal";
import Combobox from "./Combobox";

interface Props {
  dutyTypes: DutyType[];
  onJobSubmitted: (jobId: string) => void;
  initialOverrides?: Record<string, number>;
}

const DEFAULT_SETTINGS: SolverSettings = {
  K: 8, T: 8, Wt: 14, R: 15, Wr: 28, alpha: 1.0, beta: 2.0, time_limit_seconds: 30, num_workers: 1,
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
  const [showDeterministicHelp, setShowDeterministicHelp] = useState(false);
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
            <div className="w-40">
              <Combobox
                items={dutyTypes}
                value={filterDutyTypeId}
                onChange={setFilterDutyTypeId}
                placeholder="כל הסוגים"
              />
            </div>
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

      {/* Determinism toggle */}
      <div className="flex items-center gap-2 flex-wrap" dir="rtl">
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">תוצאות:</span>
        <div className="flex rounded border border-gray-300 dark:border-gray-600 overflow-hidden text-sm">
          <button
            type="button"
            className={`px-3 py-1 ${settings.num_workers === 1 ? "bg-indigo-600 text-white" : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300"}`}
            onClick={() => setSettings(s => ({ ...s, num_workers: 1 }))}
          >
            דטרמיניסטי
          </button>
          <button
            type="button"
            className={`px-3 py-1 ${settings.num_workers !== 1 ? "bg-indigo-600 text-white" : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300"}`}
            onClick={() => setSettings(s => ({ ...s, num_workers: 8 }))}
          >
            מהיר
          </button>
        </div>
        <button
          type="button"
          className="text-gray-400 hover:text-indigo-600 text-xs font-bold border rounded-full w-5 h-5 flex items-center justify-center flex-shrink-0"
          onClick={() => setShowDeterministicHelp(h => !h)}
          title="מה ההבדל?"
        >
          ?
        </button>
        {showDeterministicHelp && (
          <p className="w-full text-xs text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-700 rounded p-2 mt-1" dir="rtl">
            <strong>דטרמיניסטי:</strong> האלגוריתם רץ עם חוט עיבוד אחד ולכן מייצר תמיד את אותן הצעות בדיוק לאותו קלט — שימושי כשרוצים לוודא שהרצה חוזרת לא תשנה שיבוצים שכבר אושרו.{" "}
            <strong>מהיר:</strong> האלגוריתם רץ עם 8 חוטי עיבוד במקביל — מהיר יותר אבל עשוי לתת תוצאות שונות בין הרצה להרצה אפילו על אותו קלט, כי חוטי העיבוד מתחרים זה בזה וסדר הסיום שלהם תלוי בתזמוני המעבד.
          </p>
        )}
      </div>

      <button type="button" className="text-xs text-blue-600 dark:text-blue-400 underline" onClick={() => setShowSettings(s => !s)}>
        {t("algorithm.settings")}
      </button>
      {showSettings && (
        <div className="bg-gray-50 dark:bg-gray-700 rounded p-3 space-y-3 text-sm">
          {([
            { key: "T" as const, label: "מכסת תורנויות ללא רזרבה בחלון (T)", description: "מספר תורנויות אמת מרבי לחייל בחלון נע — חייב להיות ≤ R", step: 1 },
            { key: "Wt" as const, label: "אורך חלון תורנויות ללא רזרבה (Wt)", description: "גודל החלון הנע בימים לספירת T — בדרך כלל קצר יותר מ-Wr", step: 1 },
            { key: "R" as const, label: "מכסת תורנויות כוללת בחלון (R)", description: "מספר התורנויות הכולל המרבי לחייל בחלון נע, כולל רזרבה — חייב להיות ≥ T", step: 1 },
            { key: "Wr" as const, label: "אורך חלון תורנויות כולל (Wr)", description: "גודל החלון הנע בימים לספירת R — בדרך כלל ארוך יותר מ-Wt", step: 1 },
            { key: "alpha" as const, label: "משקל העדפת ניקוד (α)", description: "ככל שגבוה יותר, האלגוריתם יעדיף חיילים עם עומס נמוך — ערכים גבוהים מייצרים שיבוץ הוגן יותר", step: 0.1 },
            { key: "beta" as const, label: "משקל הוגנות (β)", description: "מחושב אוטומטית — ניתן לשינוי ידני במקרים מיוחדים בלבד", step: 0.1 },
            { key: "time_limit_seconds" as const, label: "מגבלת זמן ריצת האלגוריתם (שניות)", description: "מספר שניות מרבי להרצת האלגוריתם — יחזיר את הפתרון הטוב ביותר שנמצא עד אז", step: 1 },
          ]).map(({ key, label, description, step }) => (
            <div key={key} className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="text-xs font-medium text-gray-800 dark:text-gray-100">{label}</div>
                <div className="text-xs text-gray-400 dark:text-gray-300 mt-0.5">{description}</div>
              </div>
              <input
                type="number"
                value={settings[key]}
                onChange={e => setSettings(s => ({ ...s, [key]: parseFloat(e.target.value) }))}
                className="w-20 border rounded px-2 py-1 text-xs text-left dark:bg-gray-600 dark:border-gray-500 dark:text-gray-100 flex-shrink-0"
                step={step}
                dir="ltr"
              />
            </div>
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
