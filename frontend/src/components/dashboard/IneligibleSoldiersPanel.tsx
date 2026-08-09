import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { getIneligibleSoldiers, type IneligibleSoldier } from "../../api/ineligibleSoldiers";
import { queryKeys } from "../../queryKeys";
import SoldierLink from "../SoldierLink";
import { RANGE_TYPE_LABELS } from "../../utils/rangeLabels";

function qualificationSummary(soldier: IneligibleSoldier, t: (key: string, options?: { date?: string }) => string) {
  if (soldier.valid_qualifications.length === 0) return t("range_qualification.warning.normal");
  return soldier.valid_qualifications
    .map((qualification) => `${RANGE_TYPE_LABELS[qualification.range_type] ?? qualification.range_type} ${t("range_qualification.qualificationExpiry", { date: qualification.valid_until })}`)
    .join(", ");
}

function dutySummary(soldier: IneligibleSoldier) {
  return soldier.upcoming_weapon_duties
    .map((duty) => `${duty.duty_type_name} ${duty.start_date}`)
    .join(", ");
}

function rangeSummary(soldier: IneligibleSoldier) {
  return soldier.upcoming_matching_ranges
    .map((range) => `${RANGE_TYPE_LABELS[range.range_type] ?? range.range_type} ${range.date}`)
    .join(", ");
}

export function IneligibleSoldiersPanel() {
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: queryKeys.ineligibleSoldiers("commander"),
    queryFn: () => getIneligibleSoldiers("commander"),
    retry: false,
  });

  const soldiers = useMemo(() => {
    const rows = query.data?.soldiers ?? [];
    return rows.filter((soldier) => soldier.valid_qualifications.length === 0 || soldier.has_upcoming_weapon_duty);
  }, [query.data]);

  if (query.isLoading) {
    return <section id="panel-ineligible-soldiers" className="space-y-2" dir="rtl">
      <p className="text-sm text-gray-500" role="status">{t("range_qualification.loading")}</p>
    </section>;
  }

  if (query.isError) {
    return <section id="panel-ineligible-soldiers" className="space-y-2" dir="rtl">
      <p className="text-sm text-red-700 dark:text-red-300" role="alert">{t("range_qualification.error")}</p>
    </section>;
  }

  if (soldiers.length === 0) {
    return <section id="panel-ineligible-soldiers" className="space-y-2" dir="rtl">
      <p className="text-sm text-gray-500" role="status">{t("range_qualification.dashboard.empty")}</p>
    </section>;
  }

  return (
    <section id="panel-ineligible-soldiers" className="space-y-3" dir="rtl">
      <div className="space-y-1">
        <h3 className="text-base font-semibold">{t("range_qualification.dashboard.title")}</h3>
        <p className="text-sm text-gray-600 dark:text-gray-300">{t("range_qualification.dashboard.description")}</p>
      </div>
      <ul className="space-y-3">
        {soldiers.map((soldier) => {
          const urgent = soldier.has_upcoming_weapon_duty && !soldier.has_upcoming_matching_range;
          const dutyText = dutySummary(soldier);
          const rangeText = rangeSummary(soldier);
          return (
            <li key={soldier.soldier_id} className="rounded-lg border border-gray-200 p-3 dark:border-gray-700">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <SoldierLink id={soldier.soldier_id} name={soldier.soldier_name} className="font-medium" />
                  <p className="text-sm text-gray-600 dark:text-gray-300">{soldier.hierarchy_node_name}</p>
                  <p className="text-sm text-gray-700 dark:text-gray-200">{qualificationSummary(soldier, t)}</p>
                  {(dutyText || rangeText) && (
                    <p className="text-sm text-gray-600 dark:text-gray-300">
                      {[dutyText, rangeText].filter(Boolean).join(" · ")}
                    </p>
                  )}
                </div>
                <span
                  data-testid={`ineligible-warning-${soldier.soldier_id}`}
                  className={`shrink-0 rounded px-2 py-1 text-xs ${urgent
                    ? "bg-red-100 font-semibold text-red-800 dark:bg-red-900/40 dark:text-red-300"
                    : "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"}`}
                >
                  {t(urgent ? "range_qualification.warning.urgent" : "range_qualification.warning.normal")}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default IneligibleSoldiersPanel;
