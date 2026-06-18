import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { PreviewRow, generateShifts, previewGeneration } from "../api/shiftTemplates";

interface Props {
  open: boolean;
  templateId: string;
  onClose: () => void;
  onGenerated: () => void;
}

function toDateStr(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export default function GenerateShiftsModal({ open, templateId, onClose, onGenerated }: Props) {
  const { t } = useTranslation();

  const [fromDate, setFromDate] = useState(() => toDateStr(new Date()));
  const [toDate, setToDate] = useState("");
  const [preview, setPreview] = useState<PreviewRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Reset state when modal opens so stale preview/result don't carry over
  useEffect(() => {
    if (open) {
      setFromDate(toDateStr(new Date()));
      setToDate("");
      setPreview(null);
      setResult(null);
      setError(null);
    }
  }, [open]);

  // Auto-preview when both dates are set and valid; cancel stale requests
  useEffect(() => {
    if (!fromDate || !toDate || toDate < fromDate) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setPreview(null);
    setError(null);
    setResult(null);
    setLoading(true);
    previewGeneration(templateId, fromDate, toDate)
      .then((rows) => { if (!cancelled) setPreview(rows); })
      .catch((err: unknown) => {
        if (!cancelled) {
          const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
          setError(detail ?? "שגיאה");
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [templateId, fromDate, toDate]);

  if (!open) return null;

  const newCount = preview ? preview.filter((r) => !r.exists).length : 0;

  async function handleGenerate() {
    if (!fromDate || !toDate || toDate < fromDate) return;
    setError(null);
    setLoading(true);
    try {
      const res = await generateShifts(templateId, fromDate, toDate);
      setResult(res.created_count);
      setPreview(null);
      onGenerated();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-sm w-full mx-4" dir="rtl" onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-5">
          <h3 className="text-lg font-semibold">{t("shift_templates.generate_title")}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none p-1">✕</button>
        </div>

        <div className="space-y-3 mb-5">
          <label className="block text-sm">
            <span className="block text-xs text-gray-500 dark:text-gray-400 mb-0.5">{t("shift_templates.from_date", "מתאריך")}</span>
            <input
              type="date"
              value={fromDate}
              onChange={(e) => { setFromDate(e.target.value); setPreview(null); setResult(null); }}
              className="block w-full border rounded p-1.5 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              dir="ltr"
            />
          </label>
          <label className="block text-sm">
            <span className="block text-xs text-gray-500 dark:text-gray-400 mb-0.5">{t("shift_templates.to_date", "עד תאריך")}</span>
            <input
              type="date"
              value={toDate}
              min={fromDate}
              onChange={(e) => { setToDate(e.target.value); setPreview(null); setResult(null); }}
              className="block w-full border rounded p-1.5 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              dir="ltr"
            />
          </label>
        </div>

        {loading && (
          <p className="text-xs text-gray-400 text-center mb-3">טוען תצוגה מקדימה...</p>
        )}

        {preview && !loading && (
          <div className="mb-4 space-y-1">
            <p className="text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
              {t("shift_templates.preview_title", "תצוגה מקדימה")} — {newCount} {t("shift_templates.new_badge", "חדש")} / {preview.length} {t("shift_templates.total", "סה״כ")}
            </p>
            <div className="max-h-36 overflow-y-auto border dark:border-gray-600 rounded-lg p-2 space-y-1 text-sm">
              {preview.length === 0 && <p className="text-gray-500 text-xs">אין תאריכים להצגה</p>}
              {preview.map((row) => (
                <div key={row.date} className="flex items-center justify-between">
                  <span dir="ltr" className="text-xs">{row.date}</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${row.exists ? "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300" : "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300"}`}>
                    {row.exists ? t("shift_templates.exists_badge") : t("shift_templates.new_badge")}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {result !== null && (
          <p className="text-green-700 dark:text-green-400 text-sm font-medium mb-4">
            {t("shift_templates.created_count", { count: result })}
          </p>
        )}

        {error && <p className="text-red-500 text-xs mb-3">{error}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 dark:text-gray-300 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700">
            {t("shift_templates.cancel")}
          </button>
          <button
            type="button"
            onClick={handleGenerate}
            disabled={loading || !fromDate || !toDate || toDate < fromDate || (preview !== null && newCount === 0)}
            className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {t("shift_templates.generate_btn")}
          </button>
        </div>
      </div>
    </div>
  );
}
