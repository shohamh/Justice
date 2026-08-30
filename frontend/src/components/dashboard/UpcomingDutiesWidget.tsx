import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { EffectiveDuty } from "../../api/assignments";
import { formatDutyRange } from "../../utils/formatDate";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
  locationNames: Record<string, string>;
  onOpenDuty: (duty: EffectiveDuty) => void;
}

function statusLabel(t: TFunction, d: EffectiveDuty): { text: string; calledUp: boolean } {
  if (d.is_reserve && d.called_up_from) {
    const text = d.called_up_from === d.called_up_to
      ? `${t("reserve_called_up")} ${d.called_up_from}`
      : t("called_up_from_to", { from: d.called_up_from, to: d.called_up_to });
    return { text, calledUp: true };
  }
  return { text: d.is_reserve ? t("reserve_standby") : t("home.duty_primary"), calledUp: false };
}

export default function UpcomingDutiesWidget({ duties, typeNames, locationNames, onOpenDuty }: Props) {
  const { t } = useTranslation();
  const today = new Date().toISOString().split("T")[0];
  // Defensive guard: listEffectiveDuties (api/assignments.ts) is currently
  // an unguarded pass-through, so a malformed non-array response would
  // otherwise crash .filter() here. Normalize to [] rather than throwing —
  // this widget is decorative, not a required-data screen.
  const upcoming = (Array.isArray(duties) ? duties : [])
    .filter((d) => d.end_date > today)
    .sort((a, b) => a.start_date.localeCompare(b.start_date));

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">תורנויות קרובות</h2>
      {upcoming.length === 0 ? (
        <p className="text-sm text-gray-500">אין תורנויות קרובות</p>
      ) : (
        <div className="space-y-2">
          {upcoming.map((d) => {
            const status = statusLabel(t, d);
            return (
              <div
                key={d.assignment_id}
                role="button"
                tabIndex={0}
                className={`rounded-lg p-3 cursor-pointer transition ${
                  d.is_reserve
                    ? "border-2 border-dashed border-amber-400 dark:border-amber-500 bg-amber-50/50 dark:bg-amber-900/20 hover:bg-amber-50/80 dark:hover:bg-amber-900/30"
                    : "border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700/60 hover:bg-gray-100 dark:hover:bg-gray-700"
                }`}
                onClick={() => onOpenDuty(d)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onOpenDuty(d);
                  }
                }}
                title="פתח פרטים"
              >
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-medium text-sm">
                      {d.status === "algorithm_draft" && (
                        <span className="mr-1 text-[10px] px-1 rounded bg-blue-100 text-blue-800" data-testid={`draft-badge-${d.assignment_id}`}>
                          {t("duty_history.draft_badge")}
                        </span>
                      )}
                      {typeNames[d.duty_type_id] ?? "—"}
                    </div>
                    <div className={`text-xs mt-0.5 ${status.calledUp ? "text-amber-700 dark:text-amber-400 font-medium" : "text-gray-500 dark:text-gray-400"}`}>
                      {status.text}
                    </div>
                  </div>
                  <span className="text-gray-400 text-xs">›</span>
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {formatDutyRange(d.start_date, d.end_date)} · {locationNames[d.duty_location_id] ?? "—"}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
