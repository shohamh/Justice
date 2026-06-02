import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarShift, CalendarShiftAssignee } from "../api/calendar";
import DismissalModal from "./DismissalModal";
import SoldierLink from "./SoldierLink";

interface Props {
  shift: CalendarShift;
  onClose: () => void;
  onRefreshNeeded: () => void;
}

export default function ShiftDetailPanel({ shift, onClose, onRefreshNeeded }: Props) {
  const { t } = useTranslation();
  const [dismissTarget, setDismissTarget] = useState<CalendarShiftAssignee | null>(null);

  const dismissed = shift.assignees.filter(a => (!a.is_reserve || a.called_up_from) && a.dismissals.length > 0);
  const primaries = shift.assignees.filter(a => (!a.is_reserve || a.called_up_from) && a.dismissals.length === 0);
  const reserves = shift.assignees.filter(a => a.is_reserve && !a.called_up_from);

  function soldierName(id: string | null): string {
    if (!id) return "—";
    const a = shift.assignees.find(a => a.assignment_id === id);
    return a?.soldier_name ?? id.slice(0, 8);
  }

  const assigneeById = Object.fromEntries(
    shift.assignees.map((a) => [a.assignment_id, { soldierId: a.soldier_id, name: a.soldier_name }])
  );

  function soldierNode(id: string | null): React.ReactNode {
    if (!id) return "—";
    const a = assigneeById[id];
    if (!a) return id.slice(0, 8);
    return <SoldierLink id={a.soldierId} name={a.name} />;
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-5 max-w-lg w-full max-h-[80vh] overflow-y-auto mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <div>
            <h3 className="font-bold text-lg">{shift.duty_type_name} — {shift.duty_location_name}</h3>
            <p className="text-sm text-gray-500">{shift.start_date} — {shift.end_date}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl">✕</button>
        </div>

        <section className="mb-5">
          <h4 className="font-semibold text-sm text-gray-600 mb-2">
            {t("primary_soldiers")} ({primaries.length}/{shift.required_count})
            {shift.fill_status === "full" ? " ✅" : ""}
          </h4>
          <div className="space-y-2">
            {primaries.length === 0 && <p className="text-xs text-gray-400">{t("unit_calendar.none")}</p>}
            {primaries.map(a => {
              const isCalledUp = a.is_reserve && a.called_up_from;
              return (
              <div key={a.assignment_id} className={`border rounded p-2 text-sm flex flex-col gap-1 ${isCalledUp ? "border-blue-200 bg-blue-50" : ""}`}>
                <div className="flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <SoldierLink id={a.soldier_id} name={a.soldier_name} className="font-medium" />
                    {a.hierarchy_label && <span className="text-xs text-gray-400">({a.hierarchy_label})</span>}
                    {isCalledUp && (
                      <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">
                        {a.called_up_from === a.called_up_to
                          ? `${t("reserve_called_up")} ${a.called_up_from}`
                          : `${t("reserve_called_up")} ${a.called_up_from}–${a.called_up_to}`}
                      </span>
                    )}
                  </div>
                  {!isCalledUp && (
                    <button
                      className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded hover:bg-amber-200"
                      onClick={() => setDismissTarget(a)}
                    >
                      {t("dismiss_action")}
                    </button>
                  )}
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  {!isCalledUp && a.reserve_assignment_id && (
                    <span className="text-purple-600">
                      {t("reserve_standby")}: {soldierNode(a.reserve_assignment_id)}
                      {a.reserve_hierarchy_distance != null && ` (${t("distance_label", "מרחק")}: ${a.reserve_hierarchy_distance})`}
                    </span>
                  )}
                  {isCalledUp && a.primary_assignment_ids.length > 0 && (
                    <span className="text-blue-600">
                      {t("reserve_covers")}: {a.primary_assignment_ids.map((id, i) => (
                        <span key={id}>{i > 0 && ", "}{soldierNode(id)}</span>
                      ))}
                    </span>
                  )}
                </div>
              </div>
              );
            })}
          </div>
        </section>

        {dismissed.length > 0 && (
        <section className="mb-5">
          <h4 className="font-semibold text-sm text-gray-600 mb-2">
            {t("dismissed_soldiers")} ({dismissed.length})
          </h4>
          <div className="space-y-2">
            {dismissed.map(a => (
              <div key={a.assignment_id} className="border border-amber-200 bg-amber-50 rounded p-2 text-sm flex flex-col gap-1">
                <div className="flex justify-between items-center">
                  <div>
                    <SoldierLink id={a.soldier_id} name={a.soldier_name} className="font-medium" />
                    {a.hierarchy_label && <span className="text-xs text-gray-400 mr-2">({a.hierarchy_label})</span>}
                  </div>
                </div>
                {a.dismissals.map(d => (
                  <div key={d.id} className="text-xs text-amber-700">
                    {t("dismissed_from_to", { from: d.dismissed_from, to: d.dismissed_to })}
                    {d.reason && <span> ({d.reason})</span>}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </section>
        )}

        <section>
          <h4 className="font-semibold text-sm text-gray-600 mb-2">
            {t("reserve_soldiers")} ({reserves.length})
          </h4>
          <div className="space-y-2">
            {reserves.length === 0 && <p className="text-xs text-gray-400">{t("unit_calendar.none")}</p>}
            {reserves.map(a => (
              <div key={a.assignment_id} className="border rounded p-2 text-sm border-purple-200 bg-purple-50 flex flex-col gap-1">
                <div className="flex justify-between items-center">
                  <div>
                    <SoldierLink id={a.soldier_id} name={a.soldier_name} className="font-medium" />
                    <span className="text-xs text-purple-500 mr-2">({t("reserve_label")})</span>
                    {a.hierarchy_label && <span className="text-xs text-gray-400 mr-2">({a.hierarchy_label})</span>}
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded ${a.called_up_from ? "bg-blue-100 text-blue-800" : "bg-gray-100 text-gray-600"}`}>
                    {a.called_up_from
                      ? `${t("reserve_called_up")} ${a.called_up_from}–${a.called_up_to}`
                      : t("reserve_standby")}
                  </span>
                </div>
                {a.primary_assignment_ids.length > 0 && (
                  <div className="text-xs text-gray-600">
                    {t("reserve_covers")}: {a.primary_assignment_ids.map((id, i) => (
                      <span key={id}>{i > 0 && ", "}{soldierNode(id)}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>

        {dismissTarget && (
          <DismissalModal
            shift={shift}
            primary={dismissTarget}
            onClose={() => setDismissTarget(null)}
            onDone={() => { setDismissTarget(null); onRefreshNeeded(); }}
          />
        )}
      </div>
    </div>
  );
}
