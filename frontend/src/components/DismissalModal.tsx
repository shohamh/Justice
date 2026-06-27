import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarShift, CalendarShiftAssignee } from "../api/calendar";
import { dismissAndReallocate } from "../api/reserves";
import {
  previewGimelim,
  commitGimelim,
  uploadGimelimAttachment,
  GimelimPreview,
} from "../api/gimelim";
import Combobox from "./Combobox";
import SoldierLink from "./SoldierLink";

interface Props {
  shift: CalendarShift;
  primary: CalendarShiftAssignee;
  canGimelim: boolean;
  defaultRestDays: number;
  onClose: () => void;
  onDone: () => void;
}

const DAY_NAMES = ["א", "ב", "ג", "ד", "ה", "ו", "ש"];
const ALLOWED_TYPES = new Set(["application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"]);
const MAX_BYTES = 20 * 1024 * 1024;

type Mode = "regular" | "gimelim";
type GimelimStep = "form" | "preview";

export default function DismissalModal({
  shift,
  primary,
  canGimelim,
  defaultRestDays,
  onClose,
  onDone,
}: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const allDates = useMemo(() => {
    const dates: string[] = [];
    const d = new Date(shift.start_date);
    const stop = new Date(shift.end_date); // exclusive end_date -- the first day NOT touched
    while (d < stop) {
      dates.push(d.toISOString().slice(0, 10));
      d.setDate(d.getDate() + 1);
    }
    return dates;
  }, [shift.start_date, shift.end_date]);

  // Index of the last day a gimelim "from" can be (shift.end_date - 1 day).
  const lastGimelimFromIdx = Math.max(allDates.length - 2, 0);

  const [mode, setMode] = useState<Mode>("regular");

  // ── Regular mode state ──────────────────────────────────────────────────
  const [fromIdx, setFromIdx] = useState<number | null>(0);
  const [toIdx, setToIdx] = useState<number | null>(allDates.length - 1);
  // "to" = next click narrows/sets the end; "from" = next click starts a new anchor
  const [selectionPhase, setSelectionPhase] = useState<"from" | "to">("to");
  const [selectedReserveId, setSelectedReserveId] = useState(primary.reserve_assignment_id ?? "");

  // ── Shared ───────────────────────────────────────────────────────────────
  const [reason, setReason] = useState("");
  const [reasonTouched, setReasonTouched] = useState(false);

  // ── Gimelim mode state ──────────────────────────────────────────────────
  const initialGimelimFromIdx = useMemo(() => {
    const todayStr = new Date().toISOString().slice(0, 10);
    const idx = allDates.indexOf(todayStr);
    if (idx === -1) return 0;
    return Math.min(idx, lastGimelimFromIdx);
  }, [allDates, lastGimelimFromIdx]);
  const [gimelimFromIdx, setGimelimFromIdx] = useState(initialGimelimFromIdx);
  const [restDays, setRestDays] = useState(defaultRestDays);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [gimelimStep, setGimelimStep] = useState<GimelimStep>("form");
  const [preview, setPreview] = useState<GimelimPreview | null>(null);

  const reserveOptions = useMemo(
    () => shift.assignees.filter(a => a.is_reserve && a.assignment_id && !a.called_up_from),
    [shift.assignees]
  );

  useMemo(() => {
    if (!selectedReserveId && primary.reserve_assignment_id) {
      setSelectedReserveId(primary.reserve_assignment_id);
    } else if (!selectedReserveId && reserveOptions.length > 0) {
      setSelectedReserveId(reserveOptions[0].assignment_id ?? "");
    }
  }, [primary.reserve_assignment_id, reserveOptions, selectedReserveId]);

  const fromDate = fromIdx !== null ? allDates[fromIdx] : null;
  const toDate = toIdx !== null ? allDates[toIdx] : null;

  function handleDateClick(i: number) {
    if (selectionPhase === "from") {
      // First click of a new selection: anchor FROM here, collapse to single day
      setFromIdx(i);
      setToIdx(i);
      setSelectionPhase("to");
    } else {
      // Second click: set TO (or swap if clicked before FROM)
      if (fromIdx === null || i >= fromIdx) {
        setToIdx(i);
      } else {
        setToIdx(fromIdx);
        setFromIdx(i);
      }
      setSelectionPhase("from");
    }
  }

  const reasonEmpty = reason.trim() === "";
  const showReasonError = mode === "gimelim" && reasonTouched && reasonEmpty;

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setFileError(null);
    if (!f) { setSelectedFile(null); return; }
    if (!ALLOWED_TYPES.has(f.type)) {
      setFileError("סוג קובץ לא נתמך — יש להעלות PDF, JPG, PNG, GIF או WEBP");
      setSelectedFile(null);
      e.target.value = "";
      return;
    }
    if (f.size > MAX_BYTES) {
      setFileError("הקובץ גדול מדי — מקסימום 20 MB");
      setSelectedFile(null);
      e.target.value = "";
      return;
    }
    setSelectedFile(f);
  }

  const mutation = useMutation({
    mutationFn: () =>
      dismissAndReallocate(shift.id, {
        primary_assignment_id: primary.assignment_id,
        covering_reserve_assignment_id: selectedReserveId,
        from_date: fromDate ?? shift.start_date,
        to_date: toDate ?? shift.end_date,
        reason: reason || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendarShifts"] });
      onDone();
    },
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      previewGimelim(shift.id, {
        primary_assignment_id: primary.assignment_id,
        rest_days: restDays,
        reason: reason.trim(),
        from_date: allDates[gimelimFromIdx],
      }),
    onSuccess: (data) => {
      setPreview(data);
      setGimelimStep("preview");
    },
  });

  const commitMutation = useMutation({
    mutationFn: () => commitGimelim(shift.id, preview!.preview_token),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["calendarShifts"] });
      onDone();
      if (selectedFile && result.dismissal_id) {
        uploadGimelimAttachment(result.dismissal_id, selectedFile).catch(() => {
          // Silent — attachment upload failure doesn't block the gimelim action
        });
      }
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      const detail = err?.response?.data?.detail ?? "";
      if (detail.includes("stale") || detail.includes("expired")) {
        setGimelimStep("form");
        setPreview(null);
      }
    },
  });

  const tokenExpiresAt = preview ? new Date(preview.preview_token_expires_at) : null;

  function handlePreviewClick() {
    setReasonTouched(true);
    if (reasonEmpty) return;
    previewMutation.mutate();
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-lg w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-5">
          <div>
            <h3 className="font-bold text-lg">
              {mode === "gimelim" ? "🏥 שחרור גימלים" : t("dismiss_modal.title")}
            </h3>
            <p className="text-sm text-gray-500 mt-0.5">{primary.soldier_name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none p-1">✕</button>
        </div>

        {canGimelim && (
          <div className="flex gap-1 mb-5 bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
            <button
              type="button"
              onClick={() => setMode("regular")}
              className={`flex-1 text-sm py-1.5 rounded-md transition-colors ${mode === "regular" ? "bg-white dark:bg-gray-800 shadow font-medium" : "text-gray-500"}`}
            >
              {t("dismiss_modal.mode_regular")}
            </button>
            <button
              type="button"
              onClick={() => setMode("gimelim")}
              className={`flex-1 text-sm py-1.5 rounded-md transition-colors ${mode === "gimelim" ? "bg-white dark:bg-gray-800 shadow font-medium text-red-700" : "text-gray-500"}`}
            >
              {t("dismiss_modal.mode_gimelim")}
            </button>
          </div>
        )}

        {mode === "regular" && (
          <>
            <div className="mb-5">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-2 block">{t("dismiss_modal.date_range")}</label>
              <div className="flex flex-wrap gap-1.5 justify-center">
                {allDates.map((d, i) => {
                  const dt = new Date(d);
                  const dayName = DAY_NAMES[dt.getDay()];
                  const dayNum = dt.getDate();
                  const isStart = fromIdx === i;
                  const isEnd = toIdx === i;
                  const isSelected = fromIdx !== null && toIdx !== null && i >= fromIdx && i <= toIdx;
                  const isRange = isSelected && !isStart && !isEnd;
                  const isActiveEndpoint = (selectionPhase === "from" && isStart) || (selectionPhase === "to" && isEnd);
                  return (
                    <button
                      key={d}
                      type="button"
                      onClick={() => handleDateClick(i)}
                      className={`flex flex-col items-center rounded-lg px-2.5 py-1.5 text-xs min-w-[48px] transition-colors
                        ${isStart || isEnd
                          ? isActiveEndpoint
                            ? "bg-amber-400 text-white shadow-md font-bold ring-2 ring-amber-600"
                            : "bg-amber-500 text-white shadow-md font-bold"
                          : isRange
                            ? "bg-amber-100 text-amber-900"
                            : "bg-gray-100 text-gray-600 hover:bg-gray-200"
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
                  <span className={`w-2.5 h-2.5 rounded-sm inline-block ${selectionPhase === "from" ? "bg-amber-300 ring-2 ring-amber-500" : "bg-amber-500"}`} />
                  {t("dismiss_modal.from")}: <span className="font-medium text-gray-800 dark:text-gray-100" dir="ltr">{fromDate}</span>
                </span>
                <span className="flex items-center gap-1.5">
                  <span className={`w-2.5 h-2.5 rounded-sm inline-block ${selectionPhase === "to" ? "bg-amber-300 ring-2 ring-amber-500" : "bg-amber-500"}`} />
                  {t("dismiss_modal.to")}: <span className="font-medium text-gray-800 dark:text-gray-100" dir="ltr">{toDate}</span>
                </span>
              </div>
              <p className="text-center text-xs text-amber-600 dark:text-amber-400 mt-1">
                {selectionPhase === "from" ? "בחר תאריך התחלה" : "בחר תאריך סיום"}
              </p>
            </div>

            <div className="mb-4">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-1.5 block">{t("dismiss_modal.covering_reserve")}</label>
              {reserveOptions.length === 0 ? (
                <p className="text-sm text-gray-400 italic">{t("dismiss_modal.no_reserves")}</p>
              ) : (
                <Combobox
                  items={reserveOptions.map(a => ({
                    id: a.assignment_id,
                    name: a.soldier_name + (a.assignment_id === primary.reserve_assignment_id ? ` (${t("reserve_standby")})` : ""),
                  }))}
                  value={selectedReserveId}
                  onChange={setSelectedReserveId}
                />
              )}
            </div>

            <div className="mb-4">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-1.5 block">{t("dismiss_modal.reason")}</label>
              <input
                className="border border-gray-300 dark:border-gray-600 rounded-lg p-2 w-full text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-amber-300 focus:border-amber-400 outline-none"
                value={reason}
                onChange={e => setReason(e.target.value)}
                placeholder={t("dismiss_modal.reason_placeholder")}
              />
            </div>

            {mutation.isError && (
              <div className="bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg p-3 mb-4">
                <p className="text-red-600 text-sm">
                  {(mutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? t("dismiss_modal.error")}
                </p>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
                {t("dismiss_modal.cancel")}
              </button>
              <button
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending || selectedReserveId === ""}
                className="px-4 py-2 text-sm bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {mutation.isPending ? (
                  <span className="flex items-center gap-1.5">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    {t("dismiss_modal.submitting")}
                  </span>
                ) : t("dismiss_modal.confirm")}
              </button>
            </div>
          </>
        )}

        {mode === "gimelim" && gimelimStep === "form" && (
          <>
            <div className="mb-5">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-2 block">{t("dismiss_modal.date_range")}</label>
              <div className="flex flex-wrap gap-1.5 justify-center">
                {allDates.slice(0, -1).map((d, i) => {
                  const dt = new Date(d);
                  const dayName = DAY_NAMES[dt.getDay()];
                  const dayNum = dt.getDate();
                  const isSelected = gimelimFromIdx === i;
                  return (
                    <button
                      key={d}
                      type="button"
                      onClick={() => setGimelimFromIdx(i)}
                      className={`flex flex-col items-center rounded-lg px-2.5 py-1.5 text-xs min-w-[48px] transition-colors
                        ${isSelected ? "bg-red-500 text-white shadow-md font-bold" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
                    >
                      <span className="text-[10px] opacity-70">{dayName}</span>
                      <span className="text-sm font-medium">{dayNum}</span>
                    </button>
                  );
                })}
              </div>
              <div className="flex justify-center gap-6 mt-3 text-sm text-gray-600 dark:text-gray-300">
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-sm bg-red-500 inline-block" />
                  {t("dismiss_modal.from")}: <span className="font-medium text-gray-800" dir="ltr">{allDates[gimelimFromIdx]}</span>
                </span>
                <span className="flex items-center gap-1.5 text-gray-400">
                  {t("dismiss_modal.to")}: <span className="font-medium" dir="ltr">{allDates[allDates.length - 1]}</span>
                </span>
              </div>
            </div>

            <div className="mb-4">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-1.5 block">
                ימי מנוחה לפני שיבוץ מחדש
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  max={365}
                  value={restDays}
                  onChange={(e) => setRestDays(Number(e.target.value))}
                  className="w-24 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-1.5 text-sm bg-white dark:bg-gray-700 dark:text-gray-100 text-center focus:ring-2 focus:ring-red-300 outline-none"
                  dir="ltr"
                />
                <span className="text-sm text-gray-500">ימים</span>
              </div>
              <p className="text-xs text-gray-400 mt-1">
                המינימום ממועד סיום התורנות הנוכחית עד לתורנות שיושב בה החייל
              </p>
            </div>

            <div className="mb-4">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-1.5 block">
                סיבה <span className="text-red-500">*</span>
                <span className="font-normal text-gray-400 mr-1">(גלויה למנהלים בלבד)</span>
              </label>
              <textarea
                className={`border rounded-lg p-2 w-full text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 outline-none resize-none transition-colors ${
                  showReasonError
                    ? "border-red-400 focus:ring-red-300"
                    : "border-gray-300 dark:border-gray-600 focus:ring-red-300"
                }`}
                rows={2}
                value={reason}
                onChange={(e) => { setReason(e.target.value); setReasonTouched(true); }}
                onBlur={() => setReasonTouched(true)}
                placeholder="פרטים רפואיים (לא מועברים לחיילים אחרים)"
              />
              {showReasonError && (
                <p className="text-xs text-red-500 mt-1">חובה למלא סיבה לפני הגשת הבקשה</p>
              )}
            </div>

            <div className="mb-5">
              <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-1.5 block">
                צירוף מסמך <span className="text-gray-400 font-normal">(אופציונלי — לזיכרון ארגוני)</span>
              </label>
              <div
                className="flex items-center gap-2 border border-dashed border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 cursor-pointer hover:border-red-300 transition-colors"
                onClick={() => fileInputRef.current?.click()}
              >
                <span className="text-gray-400 text-sm">{selectedFile ? `📎 ${selectedFile.name}` : "לחץ לבחירת קובץ..."}</span>
                {selectedFile && (
                  <button
                    type="button"
                    className="mr-auto text-gray-400 hover:text-red-500 text-xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedFile(null);
                      if (fileInputRef.current) fileInputRef.current.value = "";
                    }}
                  >
                    ✕
                  </button>
                )}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.gif,.webp"
                className="hidden"
                onChange={handleFileChange}
              />
              {fileError && <p className="text-xs text-red-500 mt-1">{fileError}</p>}
              <p className="text-xs text-gray-400 mt-1">PDF, JPG, PNG, GIF, WEBP — עד 20 MB</p>
            </div>

            {previewMutation.isError && (
              <div className="bg-red-50 dark:bg-red-950 border border-red-200 rounded-lg p-3 mb-4 text-sm text-red-700">
                {(previewMutation.error as { response?: { data?: { detail?: string } } })
                  ?.response?.data?.detail ?? "שגיאה בחישוב ההצעה"}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-600 dark:text-gray-300 hover:bg-gray-50 transition-colors"
              >
                ביטול
              </button>
              <button
                onClick={handlePreviewClick}
                disabled={previewMutation.isPending}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-40 transition-colors shadow-sm"
              >
                {previewMutation.isPending ? "מחשב..." : "חשב הצעה ⟶"}
              </button>
            </div>
          </>
        )}

        {mode === "gimelim" && gimelimStep === "preview" && preview && (
          <>
            <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 mb-3 text-sm space-y-1">
              <div className="font-semibold text-gray-700 dark:text-gray-200 mb-1">
                ⬛ תורנות נוכחית — {preview.current_shift.duty_type_name}
              </div>
              <div>
                <span className="text-gray-500">משוחרר:</span>{" "}
                <SoldierLink id={preview.soldier_a.id} name={preview.soldier_a.name} />
                {" "}({preview.current_shift.start_date} — {preview.current_shift.end_date})
              </div>
              <div>
                <span className="text-gray-500">מוקפץ לכיסוי:</span>{" "}
                <SoldierLink id={preview.reserve_soldier.id} name={preview.reserve_soldier.name} />
              </div>
            </div>

            {preview.future_assignment ? (
              <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 mb-3 text-sm space-y-1">
                <div className="font-semibold text-gray-700 dark:text-gray-200 mb-1">
                  ⬛ תורנות עתידית —{" "}
                  {preview.future_assignment.shift.duty_type_name}{" "}
                  ({preview.future_assignment.shift.start_date})
                </div>
                <div>
                  <span className="text-gray-500">ממומר לרזרבה:</span>{" "}
                  <SoldierLink
                    id={preview.future_assignment.soldier_demoted.id}
                    name={preview.future_assignment.soldier_demoted.name}
                  />
                </div>
                <div>
                  <span className="text-gray-500">נכנס כראשוני:</span>{" "}
                  <SoldierLink id={preview.soldier_a.id} name={preview.soldier_a.name} />
                </div>
                {preview.future_assignment.c_existing_reserve_soldier && (
                  <div>
                    <span className="text-gray-500">רזרבה כללית נשארת:</span>{" "}
                    <SoldierLink
                      id={preview.future_assignment.c_existing_reserve_soldier.id}
                      name={preview.future_assignment.c_existing_reserve_soldier.name}
                    />
                  </div>
                )}
              </div>
            ) : (
              <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg p-3 mb-3 text-sm text-amber-800 dark:text-amber-200">
                ⚠️ לא נמצאה תורנות עתידית מתאימה. הגימלים יבוצע ללא שיבוץ מחדש אוטומטי — ניתן לשבץ ידנית לאחר מכן.
              </div>
            )}

            {preview.warnings.filter(w => w !== "no_future_slot_found").map((w) => (
              <div key={w} className="text-xs text-amber-600 mb-2">⚠️ {w}</div>
            ))}

            {selectedFile && (
              <p className="text-xs text-gray-500 mb-2">📎 {selectedFile.name} יצורף לאחר האישור</p>
            )}

            {tokenExpiresAt && (
              <p className="text-xs text-gray-400 mb-3 text-left" dir="ltr">
                ההצעה תקפה עד {tokenExpiresAt.toLocaleTimeString("he-IL")}
              </p>
            )}

            {commitMutation.isError && (
              <div className="bg-red-50 dark:bg-red-950 border border-red-200 rounded-lg p-3 mb-3 text-sm text-red-700">
                {(commitMutation.error as { response?: { data?: { detail?: string } } })
                  ?.response?.data?.detail ?? "שגיאה בביצוע"}
                {String(
                  (commitMutation.error as { response?: { data?: { detail?: string } } })
                    ?.response?.data?.detail ?? ""
                ).includes("stale") && " — הנתונים השתנו, יש לחשב מחדש"}
              </div>
            )}

            <div className="flex flex-wrap justify-between gap-2 pt-1">
              <button
                onClick={() => { setGimelimStep("form"); setPreview(null); }}
                className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-600 dark:text-gray-300 hover:bg-gray-50 transition-colors"
              >
                ⟵ חזור לעריכה
              </button>
              <button
                onClick={() => commitMutation.mutate()}
                disabled={commitMutation.isPending}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-40 transition-colors shadow-sm"
              >
                {commitMutation.isPending ? (
                  <span className="flex items-center gap-1.5">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    מבצע...
                  </span>
                ) : "אשר ובצע ✓"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
