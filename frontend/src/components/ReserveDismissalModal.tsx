import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarShift, CalendarShiftAssignee, dismissReserve } from "../api/calendar";
import { ReserveCandidate, getReserveCandidates } from "../api/reserves";
import Combobox from "./Combobox";
import { translateApiError } from "../utils/translateApiError";
import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  shift: CalendarShift;
  reserve: CalendarShiftAssignee;
  onClose: () => void;
  onDone: () => void;
}

const DAY_NAMES = ["א", "ב", "ג", "ד", "ה", "ו", "ש"];

export default function ReserveDismissalModal({ shift, reserve, onClose, onDone }: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const qc = useQueryClient();

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

  const [fromIdx, setFromIdx] = useState<number | null>(0);
  const [toIdx, setToIdx] = useState<number | null>(allDates.length - 1);
  const [reason, setReason] = useState("");
  const [candidates, setCandidates] = useState<ReserveCandidate[]>([]);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>("");

  const coversAnyone = reserve.primary_assignment_ids.length > 0;

  useEffect(() => {
    if (!coversAnyone) return;
    getReserveCandidates(shift.id, reserve.assignment_id)
      .then((cs) => {
        setCandidates(cs);
        if (cs.length > 0) setSelectedCandidateId(cs[0].assignment_id);
      })
      .catch(() => {});
  }, [shift.id, reserve.assignment_id, coversAnyone]);

  const assigneeById = useMemo(
    () => Object.fromEntries(shift.assignees.map((a) => [a.assignment_id, a])),
    [shift.assignees],
  );

  const fromDate = fromIdx !== null ? allDates[fromIdx] : null;
  const toDate = toIdx !== null ? allDates[toIdx] : null;

  function handleDateClick(i: number) {
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

  const mutation = useMutation({
    mutationFn: () =>
      dismissReserve(reserve.assignment_id, {
        from_date: fromDate ?? shift.start_date,
        to_date: toDate ?? shift.end_date,
        reason: reason || undefined,
        covering_reserve_assignment_id: coversAnyone && selectedCandidateId ? selectedCandidateId : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendarShifts"] });
      onDone();
    },
  });

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-lg w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-5">
          <div>
            <h3 className="font-bold text-lg">{t("dismiss_modal.title_reserve", "שחרור כוננות")}</h3>
            <p className="text-sm text-gray-500 mt-0.5">{reserve.soldier_name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none p-1">✕</button>
        </div>

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
              return (
                <button
                  key={d}
                  type="button"
                  onClick={() => handleDateClick(i)}
                  className={`flex flex-col items-center rounded-lg px-2.5 py-1.5 text-xs min-w-[48px] transition-colors
                    ${isStart || isEnd
                      ? "bg-amber-500 text-white shadow-md font-bold"
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
              <span className="w-2.5 h-2.5 rounded-sm bg-amber-500 inline-block" />
              {t("dismiss_modal.from")}: <span className="font-medium text-gray-800" dir="ltr">{fromDate}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-amber-500 inline-block" />
              {t("dismiss_modal.to")}: <span className="font-medium text-gray-800" dir="ltr">{toDate}</span>
            </span>
          </div>
        </div>

        {coversAnyone && (
          <div className="mb-4">
            <label className="text-sm font-medium text-gray-600 dark:text-gray-300 mb-1.5 block">
              {t("dismiss_modal.covering_reserve", "מי יכסה במקום")}
            </label>
            <div className="text-xs text-gray-500 dark:text-gray-400 mb-2">
              {t("dismiss_modal.covers_primaries", "כונן זה מחליף את")}:{" "}
              {reserve.primary_assignment_ids.map((id, i) => {
                const a = assigneeById[id];
                return <span key={id}>{i > 0 && ", "}<span className="font-medium">{a?.soldier_name ?? id}</span></span>;
              })}
            </div>
            {candidates.length === 0 ? (
              <p className="text-xs text-gray-400 italic">{t("dismiss_modal.no_reserves", "אין כוננים פנויים — המערכת תחלץ אוטומטית")}</p>
            ) : (
              <Combobox
                items={(() => {
                  const minDist = Math.min(...candidates.map(c => c.distance));
                  return candidates.map((c) => {
                    const a = assigneeById[c.assignment_id];
                    const name = a?.soldier_name ?? c.soldier_id;
                    const calledUp = c.called_up_from != null;
                    const recommended = c.distance === minDist;
                    return {
                      id: c.assignment_id,
                      name: `${recommended ? "★ " : ""}${name} — ${t("distance_label", "מרחק")}: ${c.distance}${calledUp ? ` (${t("reserve_called_up", "בהקפצה")})` : ""}`,
                      disabled: calledUp,
                    };
                  });
                })()}
                value={selectedCandidateId}
                onChange={setSelectedCandidateId}
              />
            )}
          </div>
        )}

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
              {translateApiError(mutation.error, t, t("dismiss_modal.error"))}
            </p>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
            {t("dismiss_modal.cancel")}
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
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
            ) : t("dismiss_action")}
          </button>
        </div>
      </div>
    </div>
  );
}
