import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CreateTemplateInput,
  ShiftTemplate,
  UpdateTemplateInput,
  createTemplate,
  updateTemplate,
} from "../api/shiftTemplates";
import { DutyType, DutyLocation } from "../api/dutyConfig";

interface Props {
  dutyTypes: DutyType[];
  locations: DutyLocation[];
  initial?: ShiftTemplate;
  onSubmit: () => void | Promise<void>;
  onClose: () => void;
}

const ALL_WEEKDAYS = [1, 2, 3, 4, 5, 6, 7];

export default function ShiftTemplateFormModal({ dutyTypes, locations, initial, onSubmit, onClose }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(initial?.name ?? "");
  const [dtId, setDtId] = useState(initial?.duty_type_id ?? dutyTypes[0]?.id ?? "");
  const [locId, setLocId] = useState(initial?.duty_location_id ?? locations[0]?.id ?? "");
  const [weekdays, setWeekdays] = useState<number[]>(initial?.weekdays ?? []);
  const [startTime, setStartTime] = useState(initial?.start_time ?? "00:00");
  const [endTime, setEndTime] = useState(initial?.end_time ?? "23:59");
  const [count, setCount] = useState(initial?.required_count ?? 1);
  const [autoRoll, setAutoRoll] = useState(initial?.auto_roll ?? false);
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [error, setError] = useState<string | null>(null);

  function toggleWeekday(day: number) {
    setWeekdays(prev =>
      prev.includes(day) ? prev.filter(d => d !== day) : [...prev, day].sort((a, b) => a - b)
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      if (initial) {
        const input: UpdateTemplateInput = {
          name,
          weekdays,
          start_time: startTime,
          end_time: endTime,
          required_count: count,
          auto_roll: autoRoll,
          notes: notes || null,
        };
        await updateTemplate(initial.id, input);
      } else {
        const input: CreateTemplateInput = {
          name,
          duty_type_id: dtId,
          duty_location_id: locId,
          weekdays,
          start_time: startTime,
          end_time: endTime,
          required_count: count,
          auto_roll: autoRoll,
          notes: notes || null,
        };
        await createTemplate(input);
      }
      await onSubmit();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">{initial ? t("shift_templates.edit") : t("shift_templates.create")}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <label className="block text-sm">
            {t("shift_templates.name")}
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              className="mt-1 block w-full border rounded p-1 text-sm"
              required
            />
          </label>
          {!initial && (
            <>
              <label className="block text-sm">
                {t("shift_templates.duty_type")}
                <select value={dtId} onChange={e => setDtId(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm">
                  {dutyTypes.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </label>
              <label className="block text-sm">
                {t("shift_templates.location")}
                <select value={locId} onChange={e => setLocId(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm">
                  {locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </label>
            </>
          )}
          <div className="block text-sm">
            <span className="block mb-1">{t("shift_templates.weekdays")}</span>
            <div className="flex gap-1 flex-wrap">
              {ALL_WEEKDAYS.map(day => (
                <button
                  key={day}
                  type="button"
                  onClick={() => toggleWeekday(day)}
                  className={`px-2 py-1 rounded text-xs border ${weekdays.includes(day) ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-gray-700 border-gray-300"}`}
                >
                  {t(`weekday_${day}`)}
                </button>
              ))}
            </div>
          </div>
          <label className="block text-sm">
            {t("shift_templates.start_time")}
            <input type="time" value={startTime} onChange={e => setStartTime(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" />
          </label>
          <label className="block text-sm">
            {t("shift_templates.end_time")}
            <input type="time" value={endTime} onChange={e => setEndTime(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" />
          </label>
          <label className="block text-sm">
            {t("shift_templates.required_count")}
            <input type="number" min={1} value={count} onChange={e => setCount(parseInt(e.target.value))} className="mt-1 block w-full border rounded p-1 text-sm" required />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={autoRoll} onChange={e => setAutoRoll(e.target.checked)} />
            {t("shift_templates.auto_roll")}
          </label>
          <label className="block text-sm">
            {t("shift_templates.notes")}
            <textarea value={notes} onChange={e => setNotes(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" rows={2} />
          </label>
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded">{t("shift_templates.cancel")}</button>
            <button type="submit" className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">{t("shift_templates.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
