import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { DutyLocation, createLocation } from "../api/dutyConfig";
import { translateApiError } from "../utils/translateApiError";

interface Props {
  onCreated: (loc: DutyLocation) => void;
  onClose: () => void;
}

export default function LocationFormModal({ onCreated, onClose }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const loc = await createLocation({ name: name.trim() });
      onCreated(loc);
    } catch (err: unknown) {
      setError(translateApiError(err, t, "שגיאה"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-80" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-base">{t("duty_config.add")} {t("duty_config.locations")}</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <label className="block text-sm">
            {t("duty_config.name")}
            <input
              required
              autoFocus
              value={name}
              onChange={e => setName(e.target.value)}
              className="mt-1 block w-full border rounded p-1.5 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            />
          </label>
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">
              {t("duty_config.cancel", "ביטול")}
            </button>
            <button type="submit" disabled={saving || !name.trim()}
              className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50">
              {t("duty_config.add")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
