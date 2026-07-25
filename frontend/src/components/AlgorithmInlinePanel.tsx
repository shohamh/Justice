import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { SolverSettings, submitJob, getAlgorithmDefaults } from "../api/algorithm";
import SubHierarchySelector from "./SubHierarchySelector";
import AlgorithmModeHelpModal from "./AlgorithmModeHelpModal";
import { translateApiError } from "../utils/translateApiError";
import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  selectedShiftIds: string[];
  onJobSubmitted: (jobId: string) => void;
  onClose: () => void;
}

const DEFAULT_SETTINGS: SolverSettings = {
  K: 8, T: 8, Wt: 14, R: 15, Wr: 28, alpha: 1.0, beta: 2.0, time_limit_seconds: 30, num_workers: 1,
};

export default function AlgorithmInlinePanel({ selectedShiftIds, onJobSubmitted, onClose }: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const [mode, setMode] = useState<"draft" | "direct_publish">("draft");
  const [showModeHelp, setShowModeHelp] = useState(false);
  const [showDeterministicHelp, setShowDeterministicHelp] = useState(false);
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
      setError(translateApiError(e, t, "שגיאה בשליחת הבקשה"));
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

      {/* Run mode */}
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
        הגדרות מתקדמות
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
        <summary className="cursor-pointer text-xs">הגבלת תת-עץ</summary>
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
