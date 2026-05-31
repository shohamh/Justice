import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarShift, CalendarShiftAssignee } from "../api/calendar";
import { dismissAndReallocate } from "../api/reserves";

interface Props {
  shift: CalendarShift;
  primary: CalendarShiftAssignee;
  onClose: () => void;
  onDone: () => void;
}

export default function DismissalModal({ shift, primary, onClose, onDone }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const allDates = useMemo(() => {
    const dates: string[] = [];
    const d = new Date(shift.start_date);
    const stop = new Date(shift.end_date);
    while (d <= stop) {
      dates.push(d.toISOString().slice(0, 10));
      d.setDate(d.getDate() + 1);
    }
    return dates;
  }, [shift.start_date, shift.end_date]);

  const [fromIdx, setFromIdx] = useState(0);
  const [toIdx, setToIdx] = useState(allDates.length - 1);
  const [selectedReserveId, setSelectedReserveId] = useState(primary.reserve_assignment_id ?? "");
  const [reason, setReason] = useState("");

  const reserveOptions = useMemo(
    () => shift.assignees.filter(a => a.is_reserve && a.assignment_id),
    [shift.assignees]
  );

  useMemo(() => {
    if (!selectedReserveId && primary.reserve_assignment_id) {
      setSelectedReserveId(primary.reserve_assignment_id);
    } else if (!selectedReserveId && reserveOptions.length > 0) {
      setSelectedReserveId(reserveOptions[0].assignment_id ?? "");
    }
  }, [primary.reserve_assignment_id, reserveOptions, selectedReserveId]);

  const fromDate = allDates[fromIdx];
  const toDate = allDates[toIdx];

  const mutation = useMutation({
    mutationFn: () =>
      dismissAndReallocate(shift.id, {
        primary_assignment_id: primary.assignment_id,
        covering_reserve_assignment_id: selectedReserveId,
        from_date: fromDate,
        to_date: toDate,
        reason: reason || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendarShifts"] });
      onDone();
    },
  });

  const dayWidth = 36;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-5 max-w-xl w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-bold text-lg">{t("dismiss_modal.title")} — {primary.soldier_name}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>

        <div className="mb-4">
          <label className="text-sm text-gray-500 mb-1 block">{t("dismiss_modal.date_range")}</label>
          <div className="relative overflow-x-auto" style={{ direction: "ltr" }}>
            <div className="flex" style={{ minWidth: allDates.length * dayWidth }}>
              {allDates.map((d, i) => {
                const isSelected = i >= fromIdx && i <= toIdx;
                return (
                  <div
                    key={d}
                    onClick={() => {
                      if (i < fromIdx) setFromIdx(i);
                      else if (i > toIdx) setToIdx(i);
                      else {
                        const mid = Math.floor((fromIdx + toIdx) / 2);
                        if (i <= mid) setFromIdx(i);
                        else setToIdx(i);
                      }
                    }}
                    className="h-10 flex items-center justify-center text-[10px] cursor-pointer border-l border-gray-200"
                    style={{
                      width: dayWidth,
                      backgroundColor: isSelected ? "#fbbf24" : "#f3f4f6",
                      fontWeight: isSelected ? 600 : 400,
                    }}
                    title={d}
                  >
                    {new Date(d).getDate()}
                  </div>
                );
              })}
            </div>
          </div>
          <div className="flex gap-4 mt-2 text-xs text-gray-600">
            <input
              type="range" min={0} max={allDates.length - 1} value={fromIdx}
              onChange={e => setFromIdx(Math.min(parseInt(e.target.value), toIdx))}
              className="flex-1"
            />
            <input
              type="range" min={0} max={allDates.length - 1} value={toIdx}
              onChange={e => setToIdx(Math.max(parseInt(e.target.value), fromIdx))}
              className="flex-1"
            />
          </div>
          <div className="flex gap-4 mt-1 text-xs text-gray-600">
            <span>{t("dismiss_modal.from")}: {fromDate}</span>
            <span>{t("dismiss_modal.to")}: {toDate}</span>
          </div>
        </div>

        <div className="mb-3">
          <label className="text-sm text-gray-500 mb-1 block">{t("dismiss_modal.covering_reserve")}</label>
          <select
            value={selectedReserveId}
            onChange={e => setSelectedReserveId(e.target.value)}
            className="border rounded p-1 w-full text-sm"
          >
            {reserveOptions.length === 0 && <option value="">{t("dismiss_modal.no_reserves")}</option>}
            {reserveOptions.map(a => (
              <option key={a.assignment_id} value={a.assignment_id}>
                {a.soldier_name}
                {a.assignment_id === primary.reserve_assignment_id ? ` (${t("reserve_standby")})` : ""}
              </option>
            ))}
          </select>
        </div>

        <div className="mb-4">
          <label className="text-sm text-gray-500 mb-1 block">{t("dismiss_modal.reason")}</label>
          <input
            className="border rounded p-1 w-full text-sm"
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder={t("dismiss_modal.reason_placeholder")}
          />
        </div>

        {mutation.isError && (
          <p className="text-red-500 text-sm mb-2">
            {(mutation.error as any)?.response?.data?.detail ?? t("dismiss_modal.error")}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1 text-sm border rounded">{t("dismiss_modal.cancel")}</button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="px-3 py-1 text-sm bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50"
          >
            {mutation.isPending ? t("dismiss_modal.submitting") : t("dismiss_modal.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
