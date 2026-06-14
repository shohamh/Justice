import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  previewGimelim,
  commitGimelim,
  uploadGimelimAttachment,
  GimelimPreview,
} from "../api/gimelim";
import { CalendarShiftAssignee } from "../api/calendar";
import SoldierLink from "./SoldierLink";

interface Props {
  shiftId: string;
  primary: CalendarShiftAssignee;
  defaultRestDays: number;
  onClose: () => void;
  onDone: () => void;
}

type Step = "form" | "preview";

const ALLOWED_TYPES = new Set(["application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"]);
const MAX_BYTES = 20 * 1024 * 1024;

export default function GimelimModal({
  shiftId,
  primary,
  defaultRestDays,
  onClose,
  onDone,
}: Props) {
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<Step>("form");
  const [restDays, setRestDays] = useState(defaultRestDays);
  const [reason, setReason] = useState("");
  const [reasonTouched, setReasonTouched] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [preview, setPreview] = useState<GimelimPreview | null>(null);

  const reasonEmpty = reason.trim() === "";
  const showReasonError = reasonTouched && reasonEmpty;

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

  const previewMutation = useMutation({
    mutationFn: () =>
      previewGimelim(shiftId, {
        primary_assignment_id: primary.assignment_id ?? "",
        rest_days: restDays,
        reason: reason.trim(),
      }),
    onSuccess: (data) => {
      setPreview(data);
      setStep("preview");
    },
  });

  const commitMutation = useMutation({
    mutationFn: () => commitGimelim(shiftId, preview!.preview_token),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["calendarShifts"] });
      onDone();
      // Upload attachment silently after closing (fire-and-forget)
      if (selectedFile && result.dismissal_id) {
        uploadGimelimAttachment(result.dismissal_id, selectedFile).catch(() => {
          // Silent — attachment upload failure doesn't block the gimelim action
        });
      }
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      const detail = err?.response?.data?.detail ?? "";
      if (detail.includes("stale") || detail.includes("expired")) {
        setStep("form");
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
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-lg w-full mx-4"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex justify-between items-center mb-5">
          <div>
            <h3 className="font-bold text-lg text-red-700 dark:text-red-400">
              🏥 שחרור גימלים
            </h3>
            <p className="text-sm text-gray-500 mt-0.5">{primary.soldier_name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none p-1">
            ✕
          </button>
        </div>

        {step === "form" && (
          <>
            {/* Rest days */}
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

            {/* Reason — mandatory */}
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

            {/* File upload — optional */}
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

        {step === "preview" && preview && (
          <>
            {/* Current shift summary */}
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

            {/* Future slot summary */}
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

            {/* Warnings */}
            {preview.warnings.filter(w => w !== "no_future_slot_found").map((w) => (
              <div key={w} className="text-xs text-amber-600 mb-2">⚠️ {w}</div>
            ))}

            {/* Attachment summary */}
            {selectedFile && (
              <p className="text-xs text-gray-500 mb-2">📎 {selectedFile.name} יצורף לאחר האישור</p>
            )}

            {/* Token expiry hint */}
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
                onClick={() => { setStep("form"); setPreview(null); }}
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
