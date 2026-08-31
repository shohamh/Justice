import { useMemo, useState } from "react";
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

interface DutyGroup {
  key: string;
  representative: UpcomingAssignment;
  primaries: UpcomingAssignment[];
  reserves: UpcomingAssignment[];
}

function formatDate(dateStr: string) {
  const d = new Date(dateStr);
  const day = d.getDate().toString().padStart(2, "0");
  const month = (d.getMonth() + 1).toString().padStart(2, "0");
  const weekday = d.toLocaleDateString("he-IL", { weekday: "short" });
  return { weekday, dayMonth: `${day}.${month}` };
}

function groupByDuty(assignments: UpcomingAssignment[]): DutyGroup[] {
  const groups = new Map<string, DutyGroup>();
  for (const a of assignments) {
    const key = a.shift_id ?? `${a.duty_type_id}|${a.duty_location_id}|${a.start_time}|${a.end_time}`;
    let group = groups.get(key);
    if (!group) {
      group = { key, representative: a, primaries: [], reserves: [] };
      groups.set(key, group);
    }
    (a.is_reserve ? group.reserves : group.primaries).push(a);
  }
  return Array.from(groups.values());
}

function toEffectiveDuty(a: UpcomingAssignment): EffectiveDuty {
  return {
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
  };
}

function SoldierRow({
  a,
  forcedCallupEnabled,
  onForcedRelease,
  reserve,
}: {
  a: UpcomingAssignment;
  forcedCallupEnabled: boolean;
  onForcedRelease: (a: UpcomingAssignment) => void;
  reserve?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <li className="flex items-center gap-1.5 text-sm">
      {reserve && <span className="text-xs text-amber-700 dark:text-amber-400">({t("command_dashboard.reserve", "רזרבה")})</span>}
      {a.status === "algorithm_draft" && (
        <span className="px-1 rounded bg-blue-100 text-blue-800 text-xs" data-testid={`draft-badge-${a.assignment_id}`}>
          {t("duty_history.draft_badge")}
        </span>
      )}
      {a.soldier_id ? (
        <SoldierLink id={a.soldier_id} name={a.soldier_name || a.duty_type_id?.slice(0, 6) || "?"} />
      ) : (
        <span>{a.soldier_name || "?"}</span>
      )}
      {forcedCallupEnabled && a.soldier_id && (
        <button
          type="button"
          onClick={() => onForcedRelease(a)}
          aria-label={t("command_dashboard.forced_callup_title", "שחרור פיקודי")}
          title={t("command_dashboard.forced_callup_title", "שחרור פיקודי")}
          className="text-amber-600 dark:text-amber-400 hover:text-amber-800 dark:hover:text-amber-200 text-xs leading-none"
        >
          ⚑
        </button>
      )}
    </li>
  );
}

export default function UpcomingSnapshot({ data }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const publicSettings = usePublicSettings();
  const [detailDuty, setDetailDuty] = useState<EffectiveDuty | null>(null);
  const [detailLocationNames, setDetailLocationNames] = useState<Record<string, string>>({});
  const [forcedReleaseTarget, setForcedReleaseTarget] = useState<UpcomingAssignment | null>(null);
  const forcedCallupEnabled = publicSettings?.["forced_callup.enabled"] === true;

  function handleForcedRelease(a: UpcomingAssignment) {
    navigate(`/commander/hakpaza?soldierId=${a.soldier_id}&assignmentId=${a.assignment_id}`);
  }

  function openDutyDetails(a: UpcomingAssignment) {
    setDetailLocationNames({ [a.duty_location_id]: a.duty_location_name });
    setDetailDuty(toEffectiveDuty(a));
  }

  const days = useMemo(
    () => (data ?? []).map((day) => ({ ...day, groups: groupByDuty(day.assignments) })),
    [data],
  );

  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_upcoming")}</p>;
  const today = new Date().toISOString().slice(0, 10);

  return (
    <div className="max-h-[28rem] overflow-y-auto space-y-2" data-testid="upcoming-snapshot">
      {days.map((day) => {
        const isToday = day.date === today;
        const { weekday, dayMonth } = formatDate(day.date);
        return (
          <div key={day.date} className={`p-2 rounded ${isToday ? "bg-indigo-50 dark:bg-indigo-950" : ""}`}>
            <div className="text-sm font-medium mb-1" dir="ltr">{weekday} {dayMonth}</div>
            {day.groups.length === 0 ? (
              <span className="text-xs text-gray-400">{t("command_dashboard.none")}</span>
            ) : (
              <div className="space-y-2">
                {day.groups.map((group) => (
                  <div key={group.key} className="border border-gray-100 dark:border-gray-700 rounded p-2">
                    <button
                      type="button"
                      onClick={() => openDutyDetails(group.representative)}
                      className="text-sm font-medium text-indigo-700 dark:text-indigo-300 hover:underline"
                    >
                      {group.representative.duty_type_name || group.representative.duty_type_id?.slice(0, 6) || "?"}
                      {" · "}
                      {group.representative.duty_location_name || "?"}
                    </button>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
                      {group.primaries.length > 0 && (
                        <ul className="space-y-0.5">
                          {group.primaries.map((a) => (
                            <SoldierRow key={a.assignment_id} a={a} forcedCallupEnabled={forcedCallupEnabled} onForcedRelease={setForcedReleaseTarget} />
                          ))}
                        </ul>
                      )}
                      {group.reserves.length > 0 && (
                        <ul className="space-y-0.5">
                          {group.reserves.map((a) => (
                            <SoldierRow key={a.assignment_id} a={a} reserve forcedCallupEnabled={forcedCallupEnabled} onForcedRelease={setForcedReleaseTarget} />
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

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
