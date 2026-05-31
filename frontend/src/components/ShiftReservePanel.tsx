import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  getShiftReserveDetail,
  callUpReserve,
  dismissPrimary,
  deleteDismissal,
} from "../api/reserves";

interface Props {
  shiftId: string;
  onClose: () => void;
}

export default function ShiftReservePanel({ shiftId, onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery(
    ["shiftReserveDetail", shiftId],
    () => getShiftReserveDetail(shiftId),
  );

  const [callUpForm, setCallUpForm] = useState<{ assignmentId: string; from: string; to: string } | null>(null);
  const [dismissForm, setDismissForm] = useState<{ assignmentId: string; from: string; to: string; reason: string } | null>(null);

  const callUpMutation = useMutation(
    ({ id, from, to }: { id: string; from: string; to: string }) =>
      callUpReserve(id, from, to),
    { onSuccess: () => { qc.invalidateQueries(["shiftReserveDetail", shiftId]); setCallUpForm(null); } },
  );

  const dismissMutation = useMutation(
    ({ id, from, to, reason }: { id: string; from: string; to: string; reason: string }) =>
      dismissPrimary(id, from, to, reason || undefined),
    { onSuccess: () => { qc.invalidateQueries(["shiftReserveDetail", shiftId]); setDismissForm(null); } },
  );

  const deleteDismissalMutation = useMutation(
    ({ assignmentId, dismissalId }: { assignmentId: string; dismissalId: string }) =>
      deleteDismissal(assignmentId, dismissalId),
    { onSuccess: () => qc.invalidateQueries(["shiftReserveDetail", shiftId]) },
  );

  if (isLoading || !data) return <div className="p-4">{t("loading", "טוען...")}</div>;

  return (
    <div className="p-4 border rounded bg-white shadow-lg max-w-lg" dir="rtl">
      <div className="flex justify-between items-center mb-3">
        <h3 className="font-bold text-lg">{t("reserve_detail_title")}</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
      </div>

      <section className="mb-4">
        <h4 className="font-semibold text-sm text-gray-600 mb-2">{t("primary_soldiers")}</h4>
        {data.primaries.map(p => (
          <div key={p.assignment_id} className="border-b py-2 flex flex-col gap-1">
            <div className="flex justify-between items-center">
              <span className="font-medium text-sm">{p.soldier_id}</span>
              <button
                className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded"
                onClick={() => setDismissForm({ assignmentId: p.assignment_id, from: p.start_date, to: p.end_date, reason: "" })}
              >
                {t("dismiss_action")}
              </button>
            </div>
            {p.reserve_assignment_id && (
              <span className="text-xs text-gray-500">
                {t("reserve_standby")}: {p.reserve_assignment_id.slice(0, 8)}... (מרחק {p.reserve_hierarchy_distance ?? "?"})
              </span>
            )}
            {p.dismissals.map(d => (
              <div key={d.id} className="flex items-center gap-2 text-xs text-red-600">
                <span>{t("reserve_dismissed")} {d.dismissed_from}–{d.dismissed_to}</span>
                <button
                  className="underline text-gray-400"
                  onClick={() => deleteDismissalMutation.mutate({ assignmentId: p.assignment_id, dismissalId: d.id })}
                >
                  ביטול
                </button>
              </div>
            ))}
          </div>
        ))}
      </section>

      <section>
        <h4 className="font-semibold text-sm text-gray-600 mb-2">{t("reserve_soldiers")}</h4>
        {data.reserves.map(r => (
          <div key={r.assignment_id} className="border-b py-2 flex flex-col gap-1">
            <div className="flex justify-between items-center">
              <span className="font-medium text-sm">{r.soldier_id}</span>
              <button
                className="text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded"
                onClick={() => setCallUpForm({ assignmentId: r.assignment_id, from: r.start_date, to: r.end_date })}
              >
                {t("call_up_action")}
              </button>
            </div>
            {r.called_up_from && (
              <span className="text-xs text-blue-600 font-medium">
                {t("reserve_called_up")} {r.called_up_from}–{r.called_up_to}
              </span>
            )}
            <span className="text-xs text-gray-500">
              {t("reserve_covers")}: {r.primary_assignment_ids.length > 0 ? `${r.primary_assignment_ids.length} חיילים` : "—"}
            </span>
          </div>
        ))}
      </section>

      {callUpForm && (
        <div className="mt-4 p-3 bg-blue-50 rounded">
          <h5 className="font-semibold text-sm mb-2">{t("call_up_action")}</h5>
          <div className="flex gap-2 mb-2">
            <input type="date" className="border rounded px-2 py-1 text-sm flex-1"
              value={callUpForm.from}
              onChange={e => setCallUpForm(f => f && ({ ...f, from: e.target.value }))} />
            <input type="date" className="border rounded px-2 py-1 text-sm flex-1"
              value={callUpForm.to}
              onChange={e => setCallUpForm(f => f && ({ ...f, to: e.target.value }))} />
          </div>
          <div className="flex gap-2">
            <button
              className="bg-blue-600 text-white text-sm px-3 py-1 rounded"
              onClick={() => callUpMutation.mutate({ id: callUpForm.assignmentId, from: callUpForm.from, to: callUpForm.to })}
            >
              אשר הקפצה
            </button>
            <button className="text-sm text-gray-600" onClick={() => setCallUpForm(null)}>ביטול</button>
          </div>
        </div>
      )}

      {dismissForm && (
        <div className="mt-4 p-3 bg-amber-50 rounded">
          <h5 className="font-semibold text-sm mb-2">{t("dismiss_action")}</h5>
          <div className="flex gap-2 mb-2">
            <input type="date" className="border rounded px-2 py-1 text-sm flex-1"
              value={dismissForm.from}
              onChange={e => setDismissForm(f => f && ({ ...f, from: e.target.value }))} />
            <input type="date" className="border rounded px-2 py-1 text-sm flex-1"
              value={dismissForm.to}
              onChange={e => setDismissForm(f => f && ({ ...f, to: e.target.value }))} />
          </div>
          <input type="text" placeholder="סיבה (אופציונלי)" className="border rounded px-2 py-1 text-sm w-full mb-2"
            value={dismissForm.reason}
            onChange={e => setDismissForm(f => f && ({ ...f, reason: e.target.value }))} />
          <div className="flex gap-2">
            <button
              className="bg-amber-600 text-white text-sm px-3 py-1 rounded"
              onClick={() => dismissMutation.mutate({ id: dismissForm.assignmentId, from: dismissForm.from, to: dismissForm.to, reason: dismissForm.reason })}
            >
              אשר שחרור
            </button>
            <button className="text-sm text-gray-600" onClick={() => setDismissForm(null)}>ביטול</button>
          </div>
        </div>
      )}
    </div>
  );
}
