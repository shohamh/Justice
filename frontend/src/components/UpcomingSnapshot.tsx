import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { UpcomingDay, UpcomingAssignment } from "../api/commanderDashboard";
import type { EffectiveDuty } from "../api/assignments";
import { usePublicSettings } from "../hooks/usePublicSettings";
import SoldierLink from "./SoldierLink";
import DutyDetailModal from "./dashboard/DutyDetailModal";
import ConfirmDialog from "./ConfirmDialog";

interface Props {
  data: UpcomingDay[] | null;
}

function formatDate(dateStr: string) {
  const d = new Date(dateStr);
  const day = d.getDate().toString().padStart(2, "0");
  const month = (d.getMonth() + 1).toString().padStart(2, "0");
  const weekday = d.toLocaleDateString("he-IL", { weekday: "short" });
  return { weekday, dayMonth: `${day}.${month}` };
}

function Badge({ a, onSelect, t }: { a: UpcomingAssignment; onSelect: (a: UpcomingAssignment) => void; t: (key: string) => string }) {
  return (
    <button
      onClick={() => onSelect(a)}
      className={`text-xs rounded px-2 py-0.5 cursor-pointer border ${
        a.is_reserve ? "bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800" : "bg-gray-100 dark:bg-gray-700 border-gray-200 dark:border-gray-600"
      }`}
    >
      {a.status === "algorithm_draft" && (
        <span className="mr-1 px-1 rounded bg-blue-100 text-blue-800" data-testid={`draft-badge-${a.assignment_id}`}>
          {t("duty_history.draft_badge")}
        </span>
      )}
      {a.soldier_name || a.duty_type_id?.slice(0, 6) || "?"}
    </button>
  );
}

export default function UpcomingSnapshot({ data }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const publicSettings = usePublicSettings();
  const [selected, setSelected] = useState<UpcomingAssignment | null>(null);
  const [detailDuty, setDetailDuty] = useState<EffectiveDuty | null>(null);
  const [detailLocationNames, setDetailLocationNames] = useState<Record<string, string>>({});
  const [forcedReleaseTarget, setForcedReleaseTarget] = useState<UpcomingAssignment | null>(null);
  const forcedCallupEnabled = publicSettings?.["forced_callup.enabled"] === true;

  function handleForcedRelease(a: UpcomingAssignment) {
    navigate(`/commander/hakpaza?soldierId=${a.soldier_id}&assignmentId=${a.assignment_id}`);
  }

  function openDutyDetails(a: UpcomingAssignment) {
    setSelected(null);
    setDetailLocationNames({ [a.duty_location_id]: a.duty_location_name });
    setDetailDuty({
      assignment_id: a.assignment_id,
      soldier_id: a.soldier_id,
      duty_type_id: a.duty_type_id,
      duty_type_name: a.duty_type_name,
      duty_location_id: a.duty_location_id,
      start_date: a.start_date,
      end_date: a.end_date,
      start_time: a.start_time,
      end_time: a.end_time,
      start_at: `${a.start_date}T${a.start_time}`,
      end_at: `${a.end_date}T${a.end_time}`,
      shift_id: a.shift_id,
      is_reserve: a.is_reserve,
      called_up_from: null,
      called_up_to: null,
      weapon_ineligible: false,
      weapon_ineligible_reason: null,
      status: a.status,
    });
  }
  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_upcoming")}</p>;
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div className="space-y-2" data-testid="upcoming-snapshot">
      {data.map((day) => {
        const isToday = day.date === today;
        const { weekday, dayMonth } = formatDate(day.date);
        return (
          <div key={day.date} className={`flex items-center gap-3 p-2 rounded ${isToday ? "bg-indigo-50 dark:bg-indigo-950" : ""}`}>
            <span className="text-sm font-medium w-20 text-left" dir="ltr">{weekday} {dayMonth}</span>
            <div className="flex-1 flex flex-wrap gap-1">
              {day.assignments.length === 0 ? (
                <span className="text-xs text-gray-400">{t("command_dashboard.none")}</span>
              ) : (
                day.assignments.map((a) => <Badge key={a.assignment_id} a={a} onSelect={setSelected} t={t} />)
              )}
            </div>
            <span className="text-xs text-gray-500 dark:text-gray-400">{day.assignments.length}</span>
          </div>
        );
      })}

      {selected && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setSelected(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-5 w-72" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-3">
              <div className="font-bold text-lg">
                {selected.soldier_id ? (
                  <SoldierLink id={selected.soldier_id} name={selected.soldier_name || "?"} />
                ) : (
                  selected.soldier_name || "?"
                )}
              </div>
              <button onClick={() => setSelected(null)} aria-label="סגור" className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
            </div>
            <div className="space-y-1 text-sm">
              <div><span className="text-gray-500 dark:text-gray-400">תורנות:</span> {selected.duty_type_name || selected.duty_type_id?.slice(0, 6) || "?"}</div>
              <div><span className="text-gray-500 dark:text-gray-400">יחידה:</span> {selected.node_name || "?"}</div>
              {selected.is_reserve && <div className="text-amber-700 dark:text-amber-400 font-medium">רזרבה</div>}
            </div>
            <button
              type="button"
              onClick={() => openDutyDetails(selected)}
              className="mt-4 w-full px-3 py-1.5 rounded text-sm font-medium border border-indigo-200 dark:border-indigo-800 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-50 dark:hover:bg-indigo-950"
            >
              {t("command_dashboard.view_duty_details")}
            </button>
            {selected.soldier_id && forcedCallupEnabled && (
              <button
                onClick={() => setForcedReleaseTarget(selected)}
                className="mt-4 w-full px-3 py-1.5 rounded text-sm font-medium bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-800"
              >
                שחרור פיקודי
              </button>
            )}
          </div>
        </div>
      )}

      <DutyDetailModal
        duty={detailDuty}
        typeNames={detailDuty ? { [detailDuty.duty_type_id]: detailDuty.duty_type_name } : {}}
        locationNames={detailLocationNames}
        onClose={() => {
          setDetailDuty(null);
          setDetailLocationNames({});
        }}
      />
      <ConfirmDialog
        open={forcedReleaseTarget !== null}
        title={t("command_dashboard.forced_callup_title", "שחרור פיקודי")}
        message={t("command_dashboard.forced_callup_confirm", { soldier: forcedReleaseTarget?.soldier_name || t("command_dashboard.soldier", "החייל"), defaultValue: "פעולה זו תפעיל מנגנון הקפצה פיקודית עבור {{soldier}} — מיועד למקרים קיצוניים בלבד (מחלה, צורך מבצעי דחוף). להמשיך?" })}
        confirmLabel={t("command_dashboard.forced_callup_confirm_button", "המשך")}
        danger
        onClose={() => setForcedReleaseTarget(null)}
        onConfirm={() => {
          const target = forcedReleaseTarget;
          setForcedReleaseTarget(null);
          if (target) handleForcedRelease(target);
        }}
      />
    </div>
  );
}
