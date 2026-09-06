import { useTranslation } from "react-i18next";
import { formatDate } from "../utils/formatDate";
import Tooltip from "./Tooltip";

export interface HolidayHit {
  date: string;
  name: string;
}

export default function HolidayBadge({ holidays }: { holidays: HolidayHit[] }) {
  const { t } = useTranslation();

  if (holidays.length === 0) return null;

  const label = t("holidays.badge_label", { count: holidays.length });

  return (
    <Tooltip
      testId="holiday-badge"
      ariaLabel={label}
      title={label}
      label={t("holidays.calendar_legend")}
      className="inline-flex items-center gap-0.5 rounded bg-amber-100 px-1.5 py-0.5 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
      content={
        <ul className="space-y-0.5">
          {holidays.map((h) => (
            <li key={h.date}>{formatDate(h.date)} — {h.name}</li>
          ))}
        </ul>
      }
    >
      📅 <span className="text-[10px] leading-4">{holidays.length}</span>
    </Tooltip>
  );
}
