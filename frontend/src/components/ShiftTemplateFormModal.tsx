import Fuse from "fuse.js";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
import DutyTypeFormModal from "./DutyTypeFormModal";
import LocationFormModal from "./LocationFormModal";

interface Props {
  dutyTypes: DutyType[];
  locations: DutyLocation[];
  initial?: ShiftTemplate;
  onSubmit: () => void | Promise<void>;
  onClose: () => void;
}

// Israeli week order: 0=Sun, 1=Mon, …, 6=Sat
const DAY_LABELS = ["א׳", "ב׳", "ג׳", "ד׳", "ה׳", "ו׳", "ש׳"];
const DOW_BG = [
  "bg-rose-400", "bg-orange-400", "bg-amber-400",
  "bg-emerald-400", "bg-teal-400", "bg-sky-400", "bg-violet-400",
];
const TIME_PRESETS = ["06:00", "08:00", "10:00", "12:00", "14:00", "16:00", "17:00", "18:00", "20:00"];

// dow 0=Sun→ISO 7, dow 1-6→ISO 1-6
function dowToIso(dow: number): number { return dow === 0 ? 7 : dow; }
function isoToDow(iso: number): number { return iso === 7 ? 0 : iso; }

function parseTimeFraction(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return (h * 60 + (m || 0)) / (24 * 60);
}

// ── sub-components ────────────────────────────────────────────────────────────

interface CellProps {
  label: string;
  colorBg: string;
  topPct: number;
  heightPct: number;
  inactive?: boolean;
  isStart?: boolean;
}

function VisualizationCell({ label, colorBg, topPct, heightPct, inactive, isStart }: CellProps) {
  if (inactive) {
    return (
      <div className="w-8 h-8 rounded bg-gray-100 dark:bg-gray-700 flex items-center justify-center text-[10px] text-gray-400 dark:text-gray-500">
        {label}
      </div>
    );
  }
  return (
    <div className={`relative w-8 h-8 rounded overflow-hidden bg-gray-100 dark:bg-gray-700 ${isStart ? "ring-2 ring-blue-500 ring-offset-1" : ""}`}>
      <div
        className={`absolute left-0 right-0 ${colorBg}`}
        style={{ top: `${topPct}%`, height: `${heightPct}%` }}
      />
      <span className="absolute inset-0 flex items-center justify-center z-10 text-[10px] font-semibold text-white drop-shadow-[0_0_2px_rgba(0,0,0,0.6)]">
        {label}
      </span>
    </div>
  );
}

function TimePicker({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex-1">
      <span className="text-xs text-gray-500 dark:text-gray-400 block mb-0.5">{label}</span>
      <input
        type="text"
        inputMode="numeric"
        placeholder="HH:MM"
        pattern="[0-2][0-9]:[0-5][0-9]"
        value={value}
        onChange={e => onChange(e.target.value)}
        className="block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
      />
      <div className="flex gap-1 mt-1 flex-wrap">
        {TIME_PRESETS.map(t => (
          <button
            key={t}
            type="button"
            onClick={() => onChange(t)}
            className={`text-[10px] px-1 py-0.5 rounded border transition-colors ${
              value === t
                ? "bg-indigo-600 text-white border-indigo-600"
                : "bg-gray-50 dark:bg-gray-700 text-gray-500 dark:text-gray-400 border-gray-200 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-600"
            }`}
          >
            {t}
          </button>
        ))}
      </div>
    </div>
  );
}

// Combobox with Fuse.js fuzzy search — dropdown rendered via portal so it
// escapes the modal's overflow-y-auto container.
function Combobox({ label, items, value, onChange }: {
  label: string;
  items: { id: string; name: string }[];
  value: string;
  onChange: (id: string) => void;
}) {
  const [query, setQuery] = useState(() => items.find(i => i.id === value)?.name ?? "");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);

  const fuse = new Fuse(items, { keys: ["name"], threshold: 0.4 });
  const results = query.trim() === "" ? items : fuse.search(query).map(r => r.item);

  useLayoutEffect(() => {
    if (open && inputRef.current) setRect(inputRef.current.getBoundingClientRect());
  }, [open]);

  // Sync label when external value changes (e.g. after quick-add selects new item)
  useEffect(() => {
    const match = items.find(i => i.id === value);
    if (match) setQuery(match.name);
  }, [value, items]);

  return (
    <div>
      <span className="text-xs text-gray-500 dark:text-gray-400 block mb-0.5">{label}</span>
      <input
        ref={inputRef}
        type="text"
        value={query}
        autoComplete="off"
        onChange={e => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => { setOpen(true); if (inputRef.current) setRect(inputRef.current.getBoundingClientRect()); }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className="block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
      />
      {open && results.length > 0 && rect && createPortal(
        <ul
          style={{ position: "fixed", top: rect.bottom + 2, left: rect.left, width: rect.width, zIndex: 9999 }}
          className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded shadow-lg max-h-48 overflow-y-auto"
        >
          {results.map(item => (
            <li key={item.id}>
              <button
                type="button"
                onPointerDown={e => {
                  e.preventDefault(); // keep input focused so blur doesn't fire
                  onChange(item.id);
                  setQuery(item.name);
                  setOpen(false);
                }}
                className={`w-full text-right px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-700 ${
                  value === item.id ? "font-semibold text-indigo-600 dark:text-indigo-400" : "text-gray-700 dark:text-gray-200"
                }`}
              >
                {item.name}
              </button>
            </li>
          ))}
        </ul>,
        document.body
      )}
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────────

export default function ShiftTemplateFormModal({
  dutyTypes: propDutyTypes,
  locations: propLocations,
  initial,
  onSubmit,
  onClose,
}: Props) {
  const { t } = useTranslation();

  const [localDutyTypes, setLocalDutyTypes] = useState(propDutyTypes);
  const [localLocations, setLocalLocations] = useState(propLocations);

  const [name, setName] = useState(initial?.name ?? "");
  const [dtId, setDtId] = useState(initial?.duty_type_id ?? propDutyTypes[0]?.id ?? "");
  const [locId, setLocId] = useState(initial?.duty_location_id ?? propLocations[0]?.id ?? "");
  const [recurrenceType, setRecurrenceType] = useState<RecurrenceType>(
    initial?.recurrence_type ?? "weekdays"
  );
  const [startDow, setStartDow] = useState<number | null>(() => {
    if (initial?.recurrence_type === "weekly" && initial.weekdays.length === 1) {
      return isoToDow(initial.weekdays[0]);
    }
    return null;
  });
  const [durationDays, setDurationDays] = useState<number>(initial?.duration_days ?? 1);
  const [startTime, setStartTime] = useState(initial?.start_time ?? "08:00");
  const [endTime, setEndTime] = useState(initial?.end_time ?? "17:00");
  const [count, setCount] = useState(initial?.required_count ?? 1);
  const [autoRoll, setAutoRoll] = useState(initial?.auto_roll ?? false);
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const [showAddDt, setShowAddDt] = useState(false);
  const [showAddLoc, setShowAddLoc] = useState(false);

  function changeDuration(delta: number) {
    setDurationDays(d => Math.max(1, Math.min(11, d + delta)));
  }

  // Visualization: 14 cells (week1 Sun-Sat, week2 Sun-Sat)
  function getCellProps(cellIdx: number): CellProps {
    const dow = cellIdx % 7;
    const label = DAY_LABELS[dow];
    const sf = parseTimeFraction(startTime);
    const ef = parseTimeFraction(endTime);
    const topPct = sf * 100;
    const heightPct = (ef - sf) * 100;

    if (recurrenceType === "daily") {
      return { label, colorBg: DOW_BG[dow], topPct, heightPct };
    }
    if (recurrenceType === "weekdays") {
      // Sun(0)–Thu(4) are work days; Fri(5), Sat(6) inactive
      if (dow > 4) return { label, colorBg: "", topPct: 0, heightPct: 0, inactive: true };
      return { label, colorBg: DOW_BG[dow], topPct, heightPct };
    }
    // weekly
    if (startDow === null) return { label, colorBg: "", topPct: 0, heightPct: 0, inactive: true };
    const endCell = Math.min(startDow + durationDays - 1, 13);
    if (cellIdx < startDow || cellIdx > endCell) {
      return { label, colorBg: "", topPct: 0, heightPct: 0, inactive: true };
    }
    const single = durationDays === 1;
    const isStart = cellIdx === startDow;
    const isEnd = cellIdx === endCell;
    let top = 0, h = 100;
    if (single)       { top = sf * 100; h = (ef - sf) * 100; }
    else if (isStart) { top = sf * 100; h = (1 - sf) * 100; }
    else if (isEnd)   { top = 0;        h = ef * 100; }
    return { label, colorBg: "bg-blue-500", topPct: top, heightPct: h, isStart: isStart && !single };
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (recurrenceType === "weekly" && startDow === null) {
      setError("יש לבחור יום התחלה");
      return;
    }
    try {
      const weekdays = recurrenceType === "weekly" ? [dowToIso(startDow!)] : [];
      const duration_days = recurrenceType === "weekly" ? durationDays : 1;
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

  const showViz = recurrenceType !== "weekly" || startDow !== null;

  return (
    <>
    {showAddDt && (
      <DutyTypeFormModal
        onSaved={dt => { setLocalDutyTypes(prev => [...prev, dt]); setDtId(dt.id); setShowAddDt(false); }}
        onClose={() => setShowAddDt(false)}
      />
    )}

    {showAddLoc && (
      <LocationFormModal
        onCreated={loc => { setLocalLocations(prev => [...prev, loc]); setLocId(loc.id); setShowAddLoc(false); }}
        onClose={() => setShowAddLoc(false)}
      />
    )}

    <div
      className="fixed inset-0 bg-black bg-opacity-40 flex items-end sm:items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-t-2xl sm:rounded-lg shadow-xl w-full sm:max-w-md sm:mx-4 max-h-[95dvh] overflow-y-auto"
        dir="rtl"
        onClick={e => e.stopPropagation()}
      >
        {/* drag handle — mobile only */}
        <div className="flex justify-center pt-3 pb-1 sm:hidden">
          <div className="w-10 h-1 rounded-full bg-gray-300 dark:bg-gray-600" />
        </div>

        <div className="px-6 pb-6 pt-3 sm:p-6">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-lg font-semibold">
              {initial ? t("shift_templates.edit") : t("shift_templates.create")}
            </h3>
            <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-3">
            {/* Name */}
            <label className="block text-sm">
              {t("shift_templates.name")}
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                required
                className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              />
            </label>

            {/* Duty type + location — create only */}
            {!initial && (
              <>
                <div>
                  <div className="flex justify-between items-center mb-0.5">
                    <span className="text-sm">{t("shift_templates.duty_type")}</span>
                    <button type="button" onClick={() => setShowAddDt(true)}
                      className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">
                      + {t("shift_templates.add_duty_type", "הוסף סוג תורנות")}
                    </button>
                  </div>
                  <Combobox label="" items={localDutyTypes} value={dtId} onChange={setDtId} />
                </div>

                <div>
                  <div className="flex justify-between items-center mb-0.5">
                    <span className="text-sm">{t("shift_templates.location")}</span>
                    <button type="button" onClick={() => setShowAddLoc(true)}
                      className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">
                      + {t("shift_templates.add_location", "הוסף מיקום")}
                    </button>
                  </div>
                  <Combobox label="" items={localLocations} value={locId} onChange={setLocId} />
                </div>
              </>
            )}

            {/* Recurrence — weekdays first = rightmost in RTL */}
            <div className="block text-sm">
              <span className="block mb-1">{t("shift_templates.recurrence_type")}</span>
              <div className="flex gap-2 flex-wrap">
                {(["weekdays", "daily", "weekly"] as RecurrenceType[]).map(rt => (
                  <button
                    key={rt}
                    type="button"
                    onClick={() => setRecurrenceType(rt)}
                    className={`px-3 py-1 rounded text-xs border ${
                      recurrenceType === rt
                        ? "bg-indigo-600 text-white border-indigo-600"
                        : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-gray-300 dark:border-gray-600"
                    }`}
                  >
                    {t(`shift_templates.recurrence_${rt}`)}
                  </button>
                ))}
              </div>
            </div>

            {/* Weekly: start-day buttons + duration stepper */}
            {recurrenceType === "weekly" && (
              <div className="space-y-3 p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg border border-gray-200 dark:border-gray-600">
                <div>
                  <span className="text-xs font-medium text-gray-600 dark:text-gray-300 block mb-1.5">
                    {t("shift_templates.start_day", "יום התחלה")}
                  </span>
                  <div className="flex gap-1">
                    {DAY_LABELS.map((label, dow) => (
                      <button
                        key={dow}
                        type="button"
                        onClick={() => setStartDow(dow)}
                        className={`w-9 h-9 rounded text-xs font-medium transition-colors ${
                          startDow === dow
                            ? "bg-blue-600 text-white shadow"
                            : "bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-600"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs font-medium text-gray-600 dark:text-gray-300">
                    {t("shift_templates.duration_days", "משך (ימים)")}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => changeDuration(-1)}
                      disabled={durationDays <= 1}
                      className="w-7 h-7 rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600 disabled:opacity-30 text-base leading-none"
                    >
                      −
                    </button>
                    <span className="w-6 text-center text-sm font-semibold text-gray-800 dark:text-gray-100">
                      {durationDays}
                    </span>
                    <button
                      type="button"
                      onClick={() => changeDuration(1)}
                      disabled={durationDays >= 11}
                      className="w-7 h-7 rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600 disabled:opacity-30 text-base leading-none"
                    >
                      +
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Times */}
            <div className="flex gap-3">
              <TimePicker label={t("shift_templates.start_time")} value={startTime} onChange={setStartTime} />
              <TimePicker label={t("shift_templates.end_time")} value={endTime} onChange={setEndTime} />
            </div>

            {/* 2-week visualization */}
            {showViz && (
              <div>
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400 block mb-1.5">
                  {t("shift_templates.visualization", "תצוגה")}
                </span>
                <div className="space-y-1">
                  {[0, 1].map(week => (
                    <div key={week} className="flex items-center gap-1">
                      <span className="text-[10px] text-gray-400 dark:text-gray-500 w-8 shrink-0 text-left">
                        ש{week + 1}
                      </span>
                      <div className="flex gap-1">
                        {Array.from({ length: 7 }, (_, dow) => {
                          const cellIdx = week * 7 + dow;
                          const props = getCellProps(cellIdx);
                          return <VisualizationCell key={cellIdx} {...props} />;
                        })}
                      </div>
                    </div>
                  ))}
                </div>
                {recurrenceType === "weekly" && startDow !== null && (
                  <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
                    מ-{DAY_LABELS[startDow]} למשך {durationDays} {durationDays === 1 ? "יום" : "ימים"} | {startTime}–{endTime}
                  </p>
                )}
              </div>
            )}

            {/* Count */}
            <label className="block text-sm">
              {t("shift_templates.required_count")}
              <input
                type="number"
                min={1}
                value={count}
                onChange={e => setCount(parseInt(e.target.value))}
                required
                className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              />
            </label>

            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={autoRoll} onChange={e => setAutoRoll(e.target.checked)} />
              {t("shift_templates.auto_roll")}
            </label>

            <label className="block text-sm">
              {t("shift_templates.notes")}
              <textarea
                value={notes}
                onChange={e => setNotes(e.target.value)}
                rows={2}
                className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              />
            </label>

            {error && <p className="text-red-500 text-xs">{error}</p>}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded"
              >
                {t("shift_templates.cancel")}
              </button>
              <button
                type="submit"
                className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
              >
                {t("shift_templates.save")}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
    </>
  );
}
