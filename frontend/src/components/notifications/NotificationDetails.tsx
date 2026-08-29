import type { TFunction } from "i18next";
import type { NotificationDTO } from "../../api/notifications";

const RANGE_TYPES = new Set([
  "range_assignment_confirmed", "range_roster_changed", "range_cancelled", "range_no_show",
  "range_excusal_pending", "range_excusal_approved", "range_excusal_rejected",
  "range_reserve_promoted", "range_reserve_excused", "range_excusal_no_backfill",
  "range_reminder", "range_reminder_shortfall",
]);

function formatDate(value: unknown): string {
  if (typeof value !== "string") return String(value ?? "");
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? `${match[3]}.${match[2]}.${match[1]}` : value;
}

function assignmentReason(assignment: Record<string, unknown>, t: TFunction): string {
  if (typeof assignment.assignment_reason_text === "string" && assignment.assignment_reason_text) {
    return assignment.assignment_reason_text;
  }
  const code = String(assignment.assignment_reason_code ?? "legacy");
  return t(`ranges.assignment_reasons.${code}`, { defaultValue: code });
}

function rangeDetails(notification: NotificationDTO, t: TFunction): Array<[string, string]> {
  if (!RANGE_TYPES.has(notification.type)) return [];
  const metadata = notification.metadata ?? {};
  const details: Array<[string, string]> = [];
  const add = (label: string, value: unknown, formatter: (value: unknown) => string = (item) => String(item)) => {
    if (value !== undefined && value !== null && value !== "") details.push([label, formatter(value)]);
  };

  add(t("notifications.detail_date"), metadata.range_date, formatDate);
  add(t("notifications.detail_range_type"), metadata.range_type,
    (value) => t(`notifications.range_type_${String(value)}`, { defaultValue: String(value) }));
  add(t("notifications.detail_location"), metadata.range_location);
  add(t("notifications.detail_primary"), metadata.primary_filled !== undefined
    ? `${metadata.primary_filled}/${metadata.primary_capacity}` : undefined);
  add(t("notifications.detail_reserve"), metadata.reserve_filled !== undefined
    ? `${metadata.reserve_filled}/${metadata.reserve_capacity}` : undefined);
  if (details.length > 0) return details;
  if (!notification.body) return [];

  return notification.body.split(" | ").flatMap((part): Array<[string, string]> => {
    const separator = part.indexOf("=");
    if (separator < 0) return [["", part]];
    const key = part.slice(0, separator);
    const value = part.slice(separator + 1);
    const labels: Record<string, string> = {
      date: t("notifications.detail_date"),
      type: t("notifications.detail_range_type"),
      location: t("notifications.detail_location"),
      primary: t("notifications.detail_primary"),
      reserve: t("notifications.detail_reserve"),
      reason: t("notifications.detail_reason"),
    };
    const translated = key === "date" ? formatDate(value)
      : key === "type" ? t(`notifications.range_type_${value}`, { defaultValue: value }) : value;
    return [[labels[key] ?? key, translated]];
  });
}

export function getNotificationTitle(notification: NotificationDTO, t: TFunction): string {
  if (notification.type === "announcement") return notification.title;
  const separator = notification.title.indexOf(": ");
  const prefix = separator >= 0 ? notification.title.slice(0, separator) : "";
  const translated = t(`notifications.type_${notification.type}`, { defaultValue: notification.title });
  return prefix ? `${prefix}: ${translated}` : translated;
}

export function NotificationDetails({ notification, expanded, t }: {
  notification: NotificationDTO;
  expanded: boolean;
  t: TFunction;
}) {
  if (!notification.body) return null;
  const assignments = notification.metadata?.assignments;
  const assignmentRows = Array.isArray(assignments)
    ? assignments.filter((assignment): assignment is Record<string, unknown> => Boolean(assignment && typeof assignment === "object"))
    : [];
  const details = rangeDetails(notification, t);
  if (!expanded) {
    return <p className="text-sm text-gray-500 dark:text-gray-400 line-clamp-2 break-words">{details.length > 0 ? details.map(([label, value]) => `${label}: ${value}`).join(" | ") : notification.body}</p>;
  }
  if (details.length > 0) {
    return <div className="mt-1 space-y-2 text-sm text-gray-600 dark:text-gray-300 break-words">
      <div className="space-y-0.5">
        {details.map(([label, value], index) => <p key={`${label}-${index}`}>{label ? `${label}: ${value}` : value}</p>)}
      </div>
      {assignmentRows.length > 0 && (
        <div className="overflow-x-auto rounded border dark:border-gray-600">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 dark:bg-gray-700">
              <tr>
                <th className="p-2 text-right font-medium">{t("notifications.detail_assignment_soldier")}</th>
                <th className="p-2 text-right font-medium">{t("notifications.detail_assignment_type")}</th>
                <th className="p-2 text-right font-medium">{t("notifications.detail_assignment_system_reason")}</th>
              </tr>
            </thead>
            <tbody>
              {assignmentRows.map((assignment, index) => (
                <tr key={`${String(assignment.soldier_id ?? assignment.soldier_name ?? "assignment")}-${index}`} className="border-t dark:border-gray-600">
                  <td className="p-2">{String(assignment.soldier_name ?? assignment.soldier_id ?? "")}</td>
                  <td className="p-2">{assignment.is_reserve ? t("notifications.assignment_type_reserve") : t("notifications.assignment_type_primary")}</td>
                  <td className="p-2">{assignmentReason(assignment, t)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>;
  }
  return <p className="mt-1 whitespace-pre-wrap break-words text-sm text-gray-600 dark:text-gray-300">{notification.body}</p>;
}
