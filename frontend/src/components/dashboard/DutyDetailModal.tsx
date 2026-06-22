import { useEffect, useState } from "react";
import { EffectiveDuty } from "../../api/assignments";
import { CalendarShift, CalendarShiftAssignee, getCalendarShift } from "../../api/calendar";
import { DutyType, listDutyTypes } from "../../api/dutyConfig";
import { formatDutyRange } from "../../utils/formatDate";
import { useAuth } from "../../auth/AuthContext";
import { useSoldierModal } from "../../contexts/SoldierModalContext";
import ShiftDetailPanel from "../ShiftDetailPanel";

interface Props {
  duty: EffectiveDuty | null;
  typeNames: Record<string, string>;
  locationNames: Record<string, string>;
  onClose: () => void;
  onRequestSwap: (duty: EffectiveDuty) => void;
}

export default function DutyDetailModal({ duty, typeNames, locationNames, onClose, onRequestSwap }: Props) {
  const { user } = useAuth();
  const { openSoldierModal } = useSoldierModal();
  const [shift, setShift] = useState<CalendarShift | null>(null);
  const [dutyType, setDutyType] = useState<DutyType | null>(null);
  const [loading, setLoading] = useState(false);
  const [showShiftPanel, setShowShiftPanel] = useState(false);

  useEffect(() => {
    if (!duty) { setShift(null); setDutyType(null); setShowShiftPanel(false); return; }
    function handleKeyDown(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [duty, onClose]);

  useEffect(() => {
    if (!duty) return;
    setLoading(true);
    setShift(null);
    setDutyType(null);
    const dtFetch = listDutyTypes().then((dts) => dts.find((d) => d.id === duty.duty_type_id) ?? null);
    const shiftFetch = duty.shift_id ? getCalendarShift(duty.shift_id) : Promise.resolve(null);
    Promise.all([dtFetch, shiftFetch])
      .then(([dt, sh]) => { setDutyType(dt); setShift(sh); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [duty]);

  if (!duty) return null;

  const primaries = shift?.assignees.filter((a) => !a.is_reserve || a.called_up_from) ?? [];
  const reserves = shift?.assignees.filter((a) => a.is_reserve && !a.called_up_from) ?? [];

  function timeLabel() {
    if (!dutyType?.start_time && !dutyType?.end_time) return null;
    const fmt = (t: string) => t.slice(0, 5);
    if (dutyType.start_time && dutyType.end_time) return `${fmt(dutyType.start_time)}–${fmt(dutyType.end_time)}`;
    if (dutyType.start_time) return `מ-${fmt(dutyType.start_time)}`;
    return `עד ${fmt(dutyType.end_time!)}`;
  }

  const time = timeLabel();

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="duty-detail-title"
        className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-sm mx-auto space-y-0 overflow-hidden"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="px-5 pt-5 pb-4"
          style={undefined}
        >
          <div className="flex justify-between items-start">
            <div>
              <h3 id="duty-detail-title" className="text-base font-semibold text-gray-900 dark:text-gray-100">
                {typeNames[duty.duty_type_id] ?? "—"}
              </h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                {formatDutyRange(duty.start_date, duty.end_date)}
                {time && <span className="mr-2 text-xs">· {time}</span>}
              </p>
            </div>
            <button onClick={onClose} aria-label="סגור" className="text-gray-400 hover:text-gray-600 text-xl leading-none mt-0.5">×</button>
          </div>

          <div className="mt-3 space-y-1 text-sm">
            <div className="flex gap-2">
              <span className="text-gray-400 w-14 shrink-0">מיקום</span>
              <span className="text-gray-700 dark:text-gray-300">{locationNames[duty.duty_location_id] ?? "—"}</span>
            </div>
            {(dutyType?.contact_name || dutyType?.contact_phone) && (
              <div className="flex gap-2">
                <span className="text-gray-400 w-14 shrink-0">איש קשר</span>
                <span className="text-gray-700 dark:text-gray-300 flex items-center gap-2 flex-wrap">
                  {dutyType.contact_name && <span>{dutyType.contact_name}</span>}
                  {dutyType.contact_phone && (
                    <a href={`tel:${dutyType.contact_phone}`} className="text-indigo-600 dark:text-indigo-300 hover:underline" dir="ltr">
                      {dutyType.contact_phone}
                    </a>
                  )}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Instructions */}
        {dutyType?.instructions && (
          <div className="px-5 py-3 bg-amber-50 dark:bg-amber-950/40 border-t border-amber-100 dark:border-amber-900">
            <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 mb-1">הוראות</p>
            <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-line leading-relaxed">
              {dutyType.instructions}
            </p>
          </div>
        )}

        {/* Other soldiers on the shift */}
        <div className="px-5 py-3 border-t dark:border-gray-700">
          {loading && <p className="text-xs text-gray-400">טוען...</p>}
          {!loading && !duty.shift_id && (
            <p className="text-xs text-gray-400">אין מידע על חיילים אחרים במשמרת זו</p>
          )}
          {!loading && duty.shift_id && (
            <>
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-2">
                חיילים במשמרת
                {shift && <span className="font-normal mr-1">({primaries.length}/{shift.required_count})</span>}
              </p>
              {primaries.length === 0 ? (
                <p className="text-xs text-gray-400">אין נתונים</p>
              ) : (
                <ul className="space-y-1">
                  {primaries.map((a) => (
                    <AssigneeRow key={a.assignment_id} assignee={a} isMe={a.soldier_id === user?.id} onClickSoldier={openSoldierModal} />
                  ))}
                </ul>
              )}
              {reserves.length > 0 && (
                <>
                  <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 mt-3 mb-1">רזרבות</p>
                  <ul className="space-y-1">
                    {reserves.map((a) => (
                      <AssigneeRow key={a.assignment_id} assignee={a} isMe={a.soldier_id === user?.id} reserve onClickSoldier={openSoldierModal} />
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </div>

        {/* Actions */}
        <div className="px-5 pb-5 pt-2 border-t dark:border-gray-700 flex gap-2">
          <button
            className="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white py-2 rounded-lg text-sm font-medium"
            onClick={() => onRequestSwap(duty)}
          >
            בקש החלפה
          </button>
          {shift && (
            <button
              className="flex-1 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 py-2 rounded-lg text-sm font-medium"
              onClick={() => setShowShiftPanel(true)}
            >
              פרטי משמרת
            </button>
          )}
        </div>
      </div>

      {showShiftPanel && shift && (
        <ShiftDetailPanel
          shift={shift}
          onClose={() => setShowShiftPanel(false)}
          onRefreshNeeded={() => {}}
        />
      )}
    </div>
  );
}

function AssigneeRow({ assignee, isMe, reserve, onClickSoldier }: {
  assignee: CalendarShiftAssignee;
  isMe: boolean;
  reserve?: boolean;
  onClickSoldier?: (id: string) => void;
}) {
  return (
    <li className={`flex items-center gap-2 text-sm ${isMe ? "font-semibold text-indigo-600 dark:text-indigo-300" : "text-gray-700 dark:text-gray-300"}`}>
      <span className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${reserve ? "bg-gray-300 dark:bg-gray-600" : isMe ? "bg-indigo-500" : "bg-gray-400"}`} />
      <button
        type="button"
        className={`truncate text-right hover:underline ${isMe ? "text-indigo-600 dark:text-indigo-300" : "text-gray-700 dark:text-gray-300"}`}
        onClick={() => onClickSoldier?.(assignee.soldier_id)}
      >
        {assignee.soldier_name}
      </button>
      {assignee.hierarchy_label && (
        <span className="text-xs text-gray-400 shrink-0">{assignee.hierarchy_label}</span>
      )}
      {assignee.called_up_from && (
        <span className="text-xs text-amber-600 dark:text-amber-400 shrink-0">הוקפץ</span>
      )}
      {isMe && <span className="text-xs text-indigo-400 shrink-0">(את/ה)</span>}
    </li>
  );
}
