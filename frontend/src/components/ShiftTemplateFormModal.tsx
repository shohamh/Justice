import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CreateTemplateInput,
  RecurrenceType,
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

// Israeli week order for display: Sun(ISO 7), Mon(1) … Sat(6)
// Picker index 0-6 = Week 1 Sun-Sat, 7-13 = Week 2 Sun-Sat
const DAY_LABELS = ["א׳", "ב׳", "ג׳", "ד׳", "ה׳", "ו׳", "ש׳"]; // Sun…Sat

function indexToIso(i: number): number {
  const dow = i % 7; // 0=Sun, 1=Mon, ..., 6=Sat
  return dow === 0 ? 7 : dow; // ISO: Sun=7, Mon=1, ..., Sat=6
}

function isoToPickerDow(iso: number): number {
  return iso === 7 ? 0 : iso; // Sun(7)→0, Mon(1)→1, ..., Sat(6)→6
}

function weekLabel(i: number) {
  return `${DAY_LABELS[i % 7]} ש${i < 7 ? "1" : "2"}`;
}

export default function ShiftTemplateFormModal({ dutyTypes, locations, initial, onSubmit, onClose }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(initial?.name ?? "");
  const [dtId, setDtId] = useState(initial?.duty_type_id ?? dutyTypes[0]?.id ?? "");
  const [locId, setLocId] = useState(initial?.duty_location_id ?? locations[0]?.id ?? "");
  const [recurrenceType, setRecurrenceType] = useState<RecurrenceType>(initial?.recurrence_type ?? "weekly");

  // Abstract 2-week picker state (only used for "weekly" recurrence)
  const [startIdx, setStartIdx] = useState<number | null>(() => {
    if (initial?.recurrence_type === "weekly" && initial.weekdays.length === 1) {
      return isoToPickerDow(initial.weekdays[0]);
    }
    return null;
  });
  const [endIdx, setEndIdx] = useState<number | null>(() => {
    if (initial?.recurrence_type === "weekly" && initial.weekdays.length === 1) {
      const si = isoToPickerDow(initial.weekdays[0]);
      return si + (initial.duration_days ?? 1) - 1;
    }
    return null;
  });

  const [startTime, setStartTime] = useState(initial?.start_time ?? "00:00");
  const [endTime, setEndTime] = useState(initial?.end_time ?? "23:59");
  const [count, setCount] = useState(initial?.required_count ?? 1);
  const [autoRoll, setAutoRoll] = useState(initial?.auto_roll ?? false);
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [error, setError] = useState<string | null>(null);

  function handlePickerClick(i: number) {
    if (startIdx === null || endIdx === null) {
      setStartIdx(i);
      setEndIdx(i);
    } else if (i < startIdx) {
      setStartIdx(i);
    } else if (i > endIdx) {
      setEndIdx(i);
    } else if (i === startIdx && i === endIdx) {
      return;
    } else {
      const dFrom = Math.abs(i - startIdx);
      const dTo = Math.abs(i - endIdx);
      if (dFrom <= dTo) setStartIdx(i);
      else setEndIdx(i);
    }
  }

  const computedWeekdays = startIdx !== null ? [indexToIso(startIdx)] : [];
  const computedDurationDays =
    startIdx !== null && endIdx !== null ? endIdx - startIdx + 1 : 1;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (recurrenceType === "weekly" && startIdx === null) {
      setError("יש לבחור את תקופת המשמרת");
      return;
    }
    try {
      const weekdays = recurrenceType === "weekly" ? computedWeekdays : [];
      const duration_days = recurrenceType === "weekly" ? computedDurationDays : 1;
      if (initial) {
        const input: UpdateTemplateInput = {
          name, recurrence_type: recurrenceType, weekdays, duration_days,
          start_time: startTime, end_time: endTime,
          required_count: count, auto_roll: autoRoll, notes: notes || null,
        };
        await updateTemplate(initial.id, input);
      } else {
        const input: CreateTemplateInput = {
          name, duty_type_id: dtId, duty_location_id: locId,
          recurrence_type: recurrenceType, weekdays, duration_days,
          start_time: startTime, end_time: endTime,
          required_count: count, auto_roll: autoRoll, notes: notes || null,
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
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
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
              className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              required
            />
          </label>
          {!initial && (
            <>
              <label className="block text-sm">
                {t("shift_templates.duty_type")}
                <select value={dtId} onChange={e => setDtId(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100">
                  {dutyTypes.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </label>
              <label className="block text-sm">
                {t("shift_templates.location")}
                <select value={locId} onChange={e => setLocId(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100">
                  {locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </label>
            </>
          )}

          {/* Recurrence type */}
          <div className="block text-sm">
            <span className="block mb-1">{t("shift_templates.recurrence_type")}</span>
            <div className="flex gap-2 flex-wrap">
              {(["daily", "weekdays", "weekly"] as RecurrenceType[]).map(rt => (
                <button
                  key={rt}
                  type="button"
                  onClick={() => setRecurrenceType(rt)}
                  className={`px-3 py-1 rounded text-xs border ${recurrenceType === rt ? "bg-indigo-600 text-white border-indigo-600" : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-gray-300 dark:border-gray-600"}`}
                >
                  {t(`shift_templates.recurrence_${rt}`)}
                </button>
              ))}
            </div>
          </div>

          {/* 2-week abstract period picker (weekly only) */}
          {recurrenceType === "weekly" && (
            <div className="block text-sm">
              <span className="block mb-1.5">{t("shift_templates.shift_period", "תקופת המשמרת")}</span>
              <div className="space-y-1">
                {[0, 1].map(week => (
                  <div key={week} className="flex items-center gap-1">
                    <span className="text-[10px] text-gray-400 dark:text-gray-500 w-10 text-left shrink-0">
                      {t("shift_templates.week", "שבוע")} {week + 1}
                    </span>
                    <div className="flex gap-1">
                      {DAY_LABELS.map((label, dow) => {
                        const i = week * 7 + dow;
                        const isStart = startIdx === i;
                        const isEnd = endIdx === i;
                        const inRange =
                          startIdx !== null &&
                          endIdx !== null &&
                          i >= startIdx &&
                          i <= endIdx;
                        const isEdge = isStart || isEnd;
                        return (
                          <button
                            key={i}
                            type="button"
                            onClick={() => handlePickerClick(i)}
                            className={`w-8 h-8 rounded text-xs font-medium transition-colors
                              ${isEdge
                                ? "bg-blue-600 text-white shadow"
                                : inRange
                                  ? "bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200"
                                  : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                              }`}
                          >
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
              {startIdx !== null && endIdx !== null && (
                <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
                  {t("shift_templates.shift_period_summary", "מ-{{from}} עד {{to}} — {{n}} ימים", {
                    from: weekLabel(startIdx),
                    to: weekLabel(endIdx),
                    n: computedDurationDays,
                  })}
                </p>
              )}
            </div>
          )}

          <label className="block text-sm">
            {t("shift_templates.start_time")}
            <input type="time" value={startTime} onChange={e => setStartTime(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          </label>
          <label className="block text-sm">
            {t("shift_templates.end_time")}
            <input type="time" value={endTime} onChange={e => setEndTime(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          </label>
          <label className="block text-sm">
            {t("shift_templates.required_count")}
            <input type="number" min={1} value={count} onChange={e => setCount(parseInt(e.target.value))} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" required />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={autoRoll} onChange={e => setAutoRoll(e.target.checked)} />
            {t("shift_templates.auto_roll")}
          </label>
          <label className="block text-sm">
            {t("shift_templates.notes")}
            <textarea value={notes} onChange={e => setNotes(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" rows={2} />
          </label>
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">{t("shift_templates.cancel")}</button>
            <button type="submit" className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">{t("shift_templates.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
