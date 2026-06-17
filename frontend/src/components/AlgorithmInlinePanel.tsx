import { useEffect, useState } from "react";
import { SolverSettings, submitJob, getAlgorithmDefaults } from "../api/algorithm";
import { DutyType } from "../api/dutyConfig";
import SubHierarchySelector from "./SubHierarchySelector";
import AlgorithmModeHelpModal from "./AlgorithmModeHelpModal";

interface Props {
  selectedShiftIds: string[];
  dutyTypes: DutyType[];
  onJobSubmitted: (jobId: string) => void;
  onClose: () => void;
}

const DEFAULT_SETTINGS: SolverSettings = {
  K: 8, T: 8, Wt: 14, R: 15, Wr: 28, alpha: 1.0, beta: 2.0, time_limit_seconds: 30,
};

export default function AlgorithmInlinePanel({ selectedShiftIds, onJobSubmitted, onClose }: Props) {
  const [mode, setMode] = useState<"draft" | "direct_publish">("draft");
  const [showModeHelp, setShowModeHelp] = useState(false);
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const [eligibleNodeIds, setEligibleNodeIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    void getAlgorithmDefaults()
      .then(d => setSettings(s => ({ ...s, T: d.T, Wt: d.Wt, R: d.R, Wr: d.Wr })))
      .catch(() => {});
  }, []);

  async function handleSubmit() {
    setError(null);
    setSubmitting(true);
    try {
      const apiMode = mode === "draft" ? "shadow" : "dm_reviewed";
      const resp = await submitJob({ shift_ids: selectedShiftIds, mode: apiMode, settings });
      onJobSubmitted(resp.id);
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה בשליחת הבקשה");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="border dark:border-gray-600 rounded-lg bg-indigo-50 dark:bg-indigo-950 p-4 space-y-3 text-sm" dir="rtl">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-indigo-800 dark:text-indigo-200">
          {selectedShiftIds.length} משמרות נבחרות
        </span>
        <button
          type="button"
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
          aria-label="סגור"
        >
          ✕
        </button>
      </div>

      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">מצב הרצה:</span>
        <div className="flex rounded border border-gray-300 dark:border-gray-600 overflow-hidden text-sm">
          <button
            type="button"
            className={`px-3 py-1 ${mode === "draft" ? "bg-indigo-600 text-white" : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300"}`}
            onClick={() => setMode("draft")}
          >
            טיוטה
          </button>
          <button
            type="button"
            className={`px-3 py-1 ${mode === "direct_publish" ? "bg-indigo-600 text-white" : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300"}`}
            onClick={() => setMode("direct_publish")}
          >
            פרסום ישיר
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

      <button
        type="button"
        className="text-xs text-blue-600 dark:text-blue-400 underline"
        onClick={() => setShowSettings(s => !s)}
      >
        הגדרות מתקדמות
      </button>
      {showSettings && (
        <div className="grid grid-cols-3 gap-3 text-xs bg-gray-50 dark:bg-gray-700 p-3 rounded">
          {(["K", "T", "Wt", "R", "Wr", "alpha", "beta", "time_limit_seconds"] as const).map(key => (
            <label key={key} className="block">
              {key}
              <input
                type="number"
                value={settings[key]}
                onChange={e => setSettings(s => ({
                  ...s,
                  [key]: (key === "alpha" || key === "beta") ? parseFloat(e.target.value) : parseInt(e.target.value, 10),
                }))}
                className="mt-1 block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                step={key === "alpha" || key === "beta" ? 0.1 : 1}
              />
            </label>
          ))}
        </div>
      )}

      <details className="border dark:border-gray-600 rounded p-2">
        <summary className="cursor-pointer">הגבלת תת-עץ</summary>
        <SubHierarchySelector value={eligibleNodeIds} onChange={setEligibleNodeIds} />
      </details>

      {error && <p className="text-red-500 text-xs">{error}</p>}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={submitting || selectedShiftIds.length === 0}
        className="w-full bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 font-medium"
      >
        הרץ שיבוץ אוטומטי {selectedShiftIds.length > 0 && `(${selectedShiftIds.length})`}
      </button>
    </div>
  );
}
