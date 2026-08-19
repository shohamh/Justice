import { MouseEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { AuditLogEntityType, AuditLogEntry, listAuditLogs } from "../api/auditLogs";

interface Props {
  entityType: AuditLogEntityType;
  entityId: string;
}

export default function AuditHistoryBlock({ entityType, entityId }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [error, setError] = useState(false);

  async function toggle(e: MouseEvent) {
    e.stopPropagation();
    const next = !expanded;
    setExpanded(next);
    if (next && !loaded) {
      try {
        const data = await listAuditLogs(entityType, entityId);
        setEntries(data);
        setLoaded(true);
      } catch {
        setError(true);
        setLoaded(true);
      }
    }
  }

  return (
    <div className="mt-2 text-xs" data-testid={`audit-history-${entityId}`}>
      <button
        type="button"
        onClick={(e) => void toggle(e)}
        className="text-indigo-600 dark:text-indigo-300 underline"
        data-testid={`audit-history-toggle-${entityId}`}
      >
        {expanded ? t("audit_history.hide") : t("audit_history.show")}
      </button>
      {expanded && (
        <div
          className="mt-1 space-y-1 border-t dark:border-gray-600 pt-1"
          data-testid={`audit-history-list-${entityId}`}
        >
          {error && <p className="text-red-500">{t("audit_history.none")}</p>}
          {!error && loaded && entries.length === 0 && (
            <p className="text-gray-500">{t("audit_history.none")}</p>
          )}
          {!error &&
            entries.map((entry) => (
              <p
                key={entry.id}
                className="text-gray-600 dark:text-gray-300"
                data-testid={`audit-history-entry-${entry.id}`}
              >
                {t(`audit_history.action_${entry.action}`, { defaultValue: entry.action })}
                {" — "}
                {entry.actor_name ?? t("audit_history.system")}
                {" · "}
                <span dir="ltr">{new Date(entry.created_at).toLocaleString("he-IL")}</span>
              </p>
            ))}
        </div>
      )}
    </div>
  );
}
