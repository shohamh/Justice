import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PreviewRow, generateShifts, previewGeneration } from "../api/shiftTemplates";

interface Props {
  open: boolean;
  templateId: string;
  onClose: () => void;
  onGenerated: () => void;
}

const DAY_NAMES = ["א", "ב", "ג", "ד", "ה", "ו", "ש"]; // Sun=0 .. Sat=6

function toDateStr(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function startOfWeekSunday(date: Date): Date {
  const d = new Date(date);
  d.setDate(d.getDate() - d.getDay());
  d.setHours(0, 0, 0, 0);
  return d;
}

function addDays(date: Date, n: number): Date {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

export default function GenerateShiftsModal({ open, templateId, onClose, onGenerated }: Props) {
  const { t } = useTranslation();

  const [windowStart, setWindowStart] = useState(() => startOfWeekSunday(new Date()));
  const [fromIdx, setFromIdx] = useState<number | null>(0);
  const [toIdx, setToIdx] = useState<number | null>(13);
  const [preview, setPreview] = useState<PreviewRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const allDates: string[] = Array.from({ length: 14 }, (_, i) => toDateStr(addDays(windowStart, i)));

  const fromDate = fromIdx !== null ? allDates[fromIdx] : null;
  const toDate = toIdx !== null ? allDates[toIdx] : null;

  function handleDateClick(i: number) {
    setPreview(null);
    setResult(null);
    if (fromIdx === null || toIdx === null) {
      setFromIdx(i);
      setToIdx(i);
    } else if (i < fromIdx) {
      setFromIdx(i);
    } else if (i > toIdx) {
      setToIdx(i);
    } else if (i === fromIdx && i === toIdx) {
      return;
    } else {
      const dFrom = Math.abs(i - fromIdx);
      const dTo = Math.abs(i - toIdx);
      if (dFrom <= dTo) setFromIdx(i);
      else setToIdx(i);
    }
  }

  function navigate(delta: number) {
    setWindowStart(d => addDays(d, delta));
    setFromIdx(null);
    setToIdx(null);
    setPreview(null);
    setResult(null);
  }

  async function handlePreview() {
    if (!fromDate || !toDate) return;
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      setPreview(await previewGeneration(templateId, fromDate, toDate));
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerate() {
    if (!fromDate || !toDate) return;
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

  const newCount = preview ? preview.filter(r => !r.exists).length : 0;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-lg w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-5">
          <h3 className="text-lg font-semibold">{t("shift_templates.generate_title")}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none p-1">✕</button>
        </div>

        <div className="mb-5">
          <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-2 block">
            {t("shift_templates.date_range", "טווח תאריכים")}
          </label>

          <div className="flex justify-between items-center mb-3">
            <button
              type="button"
              onClick={() => navigate(-14)}
              className="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              ← {t("shift_templates.two_weeks_prev", "2 שבועות")}
            </button>
            <button
              type="button"
              onClick={() => navigate(14)}
              className="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              {t("shift_templates.two_weeks_next", "2 שבועות")} →
            </button>
          </div>

          <div className="flex flex-wrap gap-1.5 justify-center">
            {allDates.map((d, i) => {
              const dt = new Date(d);
              const dayName = DAY_NAMES[dt.getDay()];
              const dayNum = dt.getDate();
              const isStart = fromIdx === i;
              const isEnd = toIdx === i;
              const isSelected = fromIdx !== null && toIdx !== null && i >= fromIdx && i <= toIdx;
              const isRange = isSelected && !isStart && !isEnd;
              return (
                <button
                  key={d}
                  type="button"
                  onClick={() => handleDateClick(i)}
                  className={`flex flex-col items-center rounded-lg px-2.5 py-1.5 text-xs min-w-[48px] transition-colors
                    ${isStart || isEnd
                      ? "bg-blue-600 text-white shadow-md font-bold"
                      : isRange
                        ? "bg-blue-100 dark:bg-blue-900 text-blue-900 dark:text-blue-100"
                        : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                    }`}
                >
                  <span className="text-[10px] opacity-70">{dayName}</span>
                  <span className="text-sm font-medium">{dayNum}</span>
                </button>
              );
            })}
          </div>

          <div className="flex justify-center gap-6 mt-3 text-sm text-gray-600 dark:text-gray-300">
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-blue-600 inline-block" />
              {t("dismiss_modal.from", "מ")}: <span className="font-medium text-gray-800 dark:text-gray-100" dir="ltr">{fromDate ?? "—"}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-blue-600 inline-block" />
              {t("dismiss_modal.to", "עד")}: <span className="font-medium text-gray-800 dark:text-gray-100" dir="ltr">{toDate ?? "—"}</span>
            </span>
          </div>
        </div>

        {preview && (
          <div className="max-h-40 overflow-y-auto border dark:border-gray-600 rounded-lg p-2 space-y-1 text-sm mb-4">
            {preview.length === 0 && <p className="text-gray-500">אין תאריכים</p>}
            {preview.map(row => (
              <div key={row.date} className="flex items-center justify-between">
                <span dir="ltr">{row.date}</span>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${row.exists ? "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300" : "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300"}`}>
                  {row.exists ? t("shift_templates.exists_badge") : t("shift_templates.new_badge")}
                </span>
              </div>
            ))}
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
            onClick={handlePreview}
            disabled={loading || fromIdx === null}
            className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50"
          >
            {t("shift_templates.preview_btn")}
          </button>
          <button
            type="button"
            onClick={handleGenerate}
            disabled={loading || fromIdx === null || (preview !== null && newCount === 0)}
            className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {t("shift_templates.generate_btn")}
          </button>
        </div>
      </div>
    </div>
  );
}
