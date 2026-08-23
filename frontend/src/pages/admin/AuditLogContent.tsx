import { useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { listAdminAuditLogs, type AdminAuditLogEntryDTO } from "../../api/adminAuditLogs";
import { DataTable, ColDef } from "../../components/DataTable";

const PAGE_SIZE = 50;

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function AuditLogContent() {
  const { t } = useTranslation();
  const [actionFilter, setActionFilter] = useState("");
  const [entityTypeFilter, setEntityTypeFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [fromFilter, setFromFilter] = useState("");
  const [toFilter, setToFilter] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<AdminAuditLogEntryDTO | null>(null);

  const filters = useMemo(
    () => ({
      action: actionFilter || undefined,
      entity_type: entityTypeFilter || undefined,
      actor_id: actorFilter || undefined,
      created_from: fromFilter || undefined,
      created_to: toFilter || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [actionFilter, entityTypeFilter, actorFilter, fromFilter, toFilter, page]
  );

  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin-audit-logs", filters],
    queryFn: () => listAdminAuditLogs(filters),
    placeholderData: keepPreviousData,
  });

  const setAndResetPage = (apply: () => void) => {
    apply();
    setPage(0);
  };

  const items = data?.items ?? [];
  const columns: ColDef<AdminAuditLogEntryDTO>[] = [
    {
      id: "created_at",
      header: t("admin.audit_log.time"),
      cell: (row) => formatDateTime(row.created_at),
      sortValue: (row) => row.created_at,
      minWidth: 140,
    },
    {
      id: "actor",
      header: t("admin.audit_log.actor"),
      cell: (row) => row.actor_name ?? t("admin.audit_log.system"),
      sortValue: (row) => row.actor_name ?? "",
      minWidth: 140,
    },
    {
      id: "action",
      header: t("admin.audit_log.action"),
      cell: (row) => (
        <button
          type="button"
          data-testid={`audit-log-action-${row.id}`}
          className="text-indigo-600 dark:text-indigo-300 underline underline-offset-2 hover:text-indigo-800 dark:hover:text-indigo-200 text-start"
          onClick={() => setSelected(row)}
        >
          {row.action}
        </button>
      ),
      sortValue: (row) => row.action,
      minWidth: 200,
    },
    {
      id: "entity_type",
      header: t("admin.audit_log.entity_type"),
      cell: (row) => row.entity_type,
      sortValue: (row) => row.entity_type,
      minWidth: 140,
    },
    {
      id: "entity_id",
      header: t("admin.audit_log.entity_id"),
      cell: (row) => (row.entity_id ? row.entity_id.slice(0, 8) : "—"),
      minWidth: 110,
    },
  ];

  const total = data?.total ?? 0;
  const showingFrom = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const showingTo = Math.min((page + 1) * PAGE_SIZE, total);
  const hasPrev = page > 0;
  const hasNext = showingTo < total;

  const selectClass =
    "block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-sm p-1.5";
  const inputClass = selectClass;

  return (
    <div className="space-y-3" data-testid="audit-log-content">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 items-end">
        <label className="block text-sm">
          <span className="block mb-1 text-gray-600 dark:text-gray-300">{t("admin.audit_log.filter_action")}</span>
          <input
            type="text"
            data-testid="audit-log-filter-action"
            className={inputClass}
            value={actionFilter}
            onChange={(e) => setAndResetPage(() => setActionFilter(e.target.value))}
            placeholder={t("admin.audit_log.filter_action_placeholder")}
          />
        </label>
        <label className="block text-sm">
          <span className="block mb-1 text-gray-600 dark:text-gray-300">{t("admin.audit_log.filter_entity_type")}</span>
          <select
            data-testid="audit-log-filter-entity-type"
            className={selectClass}
            value={entityTypeFilter}
            onChange={(e) => setAndResetPage(() => setEntityTypeFilter(e.target.value))}
          >
            <option value="">{t("admin.audit_log.filter_all")}</option>
            {(data?.facets.entity_types ?? []).map((et) => (
              <option key={et} value={et}>
                {et}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="block mb-1 text-gray-600 dark:text-gray-300">{t("admin.audit_log.filter_actor")}</span>
          <select
            data-testid="audit-log-filter-actor"
            className={selectClass}
            value={actorFilter}
            onChange={(e) => setAndResetPage(() => setActorFilter(e.target.value))}
          >
            <option value="">{t("admin.audit_log.filter_all")}</option>
            {(data?.facets.actors ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.full_name}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="block mb-1 text-gray-600 dark:text-gray-300">{t("admin.audit_log.filter_from")}</span>
          <input
            type="date"
            data-testid="audit-log-filter-from"
            className={inputClass}
            value={fromFilter}
            onChange={(e) => setAndResetPage(() => setFromFilter(e.target.value))}
          />
        </label>
        <label className="block text-sm">
          <span className="block mb-1 text-gray-600 dark:text-gray-300">{t("admin.audit_log.filter_to")}</span>
          <input
            type="date"
            data-testid="audit-log-filter-to"
            className={inputClass}
            value={toFilter}
            onChange={(e) => setAndResetPage(() => setToFilter(e.target.value))}
          />
        </label>
      </div>

      {isError ? (
        <div className="text-red-600 text-sm" data-testid="audit-log-error">
          {t("admin.audit_log.load_error")}
        </div>
      ) : isLoading ? (
        <div className="text-sm text-gray-500" data-testid="audit-log-loading">
          {t("admin.audit_log.loading")}
        </div>
      ) : (
        <DataTable
          columns={columns}
          data={items}
          testId="audit-log-table"
          emptyMessage={t("admin.audit_log.empty")}
        />
      )}

      {selected && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/50"
          data-testid="audit-log-detail-modal"
          onClick={() => setSelected(null)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto p-4 space-y-3 text-sm"
            dir="rtl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold">{selected.action}</h3>
              <button
                type="button"
                data-testid="audit-log-detail-close"
                onClick={() => setSelected(null)}
                className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              >
                <X size={18} />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-2 text-gray-700 dark:text-gray-300">
              <div>
                <span className="text-gray-500 dark:text-gray-400">{t("admin.audit_log.actor")}: </span>
                {selected.actor_name ?? t("admin.audit_log.system")}
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">{t("admin.audit_log.time")}: </span>
                {formatDateTime(selected.created_at)}
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">{t("admin.audit_log.entity_type")}: </span>
                {selected.entity_type}
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">{t("admin.audit_log.entity_id")}: </span>
                <span dir="ltr">{selected.entity_id ?? "—"}</span>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div>
                <div className="mb-1 text-gray-500 dark:text-gray-400">{t("admin.audit_log.before")}</div>
                <pre
                  dir="ltr"
                  data-testid="audit-log-detail-before"
                  className="bg-red-50 dark:bg-gray-900 rounded p-2 text-xs overflow-x-auto whitespace-pre-wrap break-all text-red-800 dark:text-red-300"
                >
                  {selected.before ? JSON.stringify(selected.before, null, 2) : "—"}
                </pre>
              </div>
              <div>
                <div className="mb-1 text-gray-500 dark:text-gray-400">{t("admin.audit_log.after")}</div>
                <pre
                  dir="ltr"
                  data-testid="audit-log-detail-after"
                  className="bg-green-50 dark:bg-gray-900 rounded p-2 text-xs overflow-x-auto whitespace-pre-wrap break-all text-green-800 dark:text-green-300"
                >
                  {selected.after ? JSON.stringify(selected.after, null, 2) : "—"}
                </pre>
              </div>
            </div>

            {selected.context && (
              <div>
                <div className="mb-1 text-gray-500 dark:text-gray-400">{t("admin.audit_log.context")}</div>
                <pre
                  dir="ltr"
                  data-testid="audit-log-detail-context"
                  className="bg-gray-50 dark:bg-gray-900 rounded p-2 text-xs overflow-x-auto whitespace-pre-wrap break-all"
                >
                  {JSON.stringify(selected.context, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="flex items-center justify-between text-sm" data-testid="audit-log-pagination">
        <span className="text-gray-600 dark:text-gray-300">
          {t("admin.audit_log.showing", { from: showingFrom, to: showingTo, total })}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            className="px-3 py-1 rounded border border-gray-300 dark:border-gray-600 disabled:opacity-40"
            disabled={!hasPrev}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            {t("admin.audit_log.prev")}
          </button>
          <button
            type="button"
            className="px-3 py-1 rounded border border-gray-300 dark:border-gray-600 disabled:opacity-40"
            disabled={!hasNext}
            onClick={() => setPage((p) => p + 1)}
          >
            {t("admin.audit_log.next")}
          </button>
        </div>
      </div>
    </div>
  );
}
