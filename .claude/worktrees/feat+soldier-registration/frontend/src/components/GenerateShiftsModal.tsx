import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PreviewRow, generateShifts, previewGeneration } from "../api/shiftTemplates";

interface Props {
  open: boolean;
  templateId: string;
  onClose: () => void;
  onGenerated: () => void;
}

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}
function thirtyDaysLater() {
  const d = new Date();
  d.setDate(d.getDate() + 30);
  return d.toISOString().slice(0, 10);
}

export default function GenerateShiftsModal({ open, templateId, onClose, onGenerated }: Props) {
  const { t } = useTranslation();
  const [rangeStart, setRangeStart] = useState(todayStr());
  const [rangeEnd, setRangeEnd] = useState(thirtyDaysLater());
  const [preview, setPreview] = useState<PreviewRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  async function handlePreview() {
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const rows = await previewGeneration(templateId, rangeStart, rangeEnd);
      setPreview(rows);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerate() {
    setError(null);
    setLoading(true);
    try {
      const res = await generateShifts(templateId, rangeStart, rangeEnd);
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
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">{t("shift_templates.generate_title")}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>

        <div className="space-y-3">
          <label className="block text-sm">
            {t("shift_templates.range_start")}
            <input type="date" value={rangeStart} onChange={e => setRangeStart(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" />
          </label>
          <label className="block text-sm">
            {t("shift_templates.range_end")}
            <input type="date" value={rangeEnd} onChange={e => setRangeEnd(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" />
          </label>

          <button
            type="button"
            onClick={handlePreview}
            disabled={loading}
            className="bg-gray-100 border px-3 py-1 rounded text-sm hover:bg-gray-200 disabled:opacity-50"
          >
            {t("shift_templates.preview_btn")}
          </button>

          {preview && (
            <div className="max-h-48 overflow-y-auto border rounded p-2 space-y-1 text-sm">
              {preview.length === 0 && <p className="text-gray-500">אין תאריכים</p>}
              {preview.map(row => (
                <div key={row.date} className="flex items-center justify-between">
                  <span dir="ltr">{row.date}</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${row.exists ? "bg-gray-100 text-gray-600" : "bg-green-100 text-green-700"}`}>
                    {row.exists ? t("shift_templates.exists_badge") : t("shift_templates.new_badge")}
                  </span>
                </div>
              ))}
            </div>
          )}

          {result !== null && (
            <p className="text-green-700 text-sm font-medium">
              {t("shift_templates.created_count", { count: result })}
            </p>
          )}

          {error && <p className="text-red-500 text-xs">{error}</p>}

          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded">{t("shift_templates.cancel")}</button>
            <button
              type="button"
              onClick={handleGenerate}
              disabled={loading || (preview !== null && newCount === 0)}
              className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {t("shift_templates.generate_btn")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
