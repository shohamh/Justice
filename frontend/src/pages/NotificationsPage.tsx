import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import { usePagePagination } from "../hooks/usePagePagination";
import { listNotifications, markRead, markAllRead, deleteNotification } from "../api/notifications";

export default function NotificationsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<string>("all");
  const { page, setPage, offset, limit } = usePagePagination({ limit: 20 });

  const notificationsQuery = useQuery({
    queryKey: queryKeys.notifications(filter, offset),
    queryFn: () => {
      const params: Record<string, unknown> = { offset, limit };
      if (filter === "unread") params.is_read = false;
      return listNotifications(params);
    },
  });
  const notifications = notificationsQuery.data?.items ?? [];
  const total = notificationsQuery.data?.total ?? 0;

  async function handleMarkRead(id: string) {
    await markRead(id);
    await queryClient.invalidateQueries({ queryKey: queryKeys.notificationsList() });
  }

  async function handleMarkAll() {
    await markAllRead();
    await queryClient.invalidateQueries({ queryKey: queryKeys.notificationsList() });
  }

  async function handleDelete(id: string) {
    await deleteNotification(id);
    await queryClient.invalidateQueries({ queryKey: queryKeys.notificationsList() });
  }

  const typeLabels: Record<string, string> = {
    swap_offer: "🔄", swap_accepted: "✅", swap_rejected: "❌",
    exemption_approved: "✔️", exemption_rejected: "✖️",
    constraint_approved: "✔️", constraint_rejected: "✖️",
    assignment_created: "📋", assignment_removed: "🗑️",
    score_adjusted: "⭐", announcement: "📢", system_announcement: "📣",
  };

  const pages = Math.ceil(total / limit);

  useEffect(() => {
    if (pages > 0 && page > pages) setPage(pages);
  }, [page, pages, setPage]);

  return (
    <Layout>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">{t("notifications.title")}</h2>
          <button onClick={handleMarkAll} className="text-sm text-indigo-600 hover:text-indigo-800">
            {t("notifications.mark_all_read")}
          </button>
        </div>
        <div className="flex gap-2 mb-4">
          <button onClick={() => { setFilter("all"); setPage(1); }}
                  className={`px-3 py-1 rounded text-sm ${filter === "all" ? "bg-indigo-100 text-indigo-700" : "bg-gray-100 dark:bg-gray-700 dark:text-gray-300"}`}>
            {t("notifications.all")} ({total})
          </button>
          <button onClick={() => { setFilter("unread"); setPage(1); }}
                  className={`px-3 py-1 rounded text-sm ${filter === "unread" ? "bg-indigo-100 text-indigo-700" : "bg-gray-100 dark:bg-gray-700 dark:text-gray-300"}`}>
            {t("notifications.unread")}
          </button>
        </div>
        {notifications.length === 0 ? (
          <p className="text-gray-500">{t("notifications.none")}</p>
        ) : (
          <div className="space-y-2">
            {notifications.map((n) => (
              <div key={n.id} className={`flex items-start gap-3 p-3 rounded border dark:border-gray-600 ${n.is_read ? "bg-gray-50 dark:bg-gray-700" : "bg-white dark:bg-gray-800"}`}>
                <span className="text-xl">{typeLabels[n.type] || "🔔"}</span>
                <div className="flex-1">
                  <p className={`${n.is_read ? "text-gray-600 dark:text-gray-300" : "font-semibold"}`}>{n.title}</p>
                  {n.body && <p className="text-sm text-gray-500 dark:text-gray-400">{n.body}</p>}
                  <p className="text-xs text-gray-400 mt-1">{new Date(n.created_at).toLocaleString("he-IL")}</p>
                </div>
                <div className="flex gap-1">
                  {!n.is_read && (
                    <button onClick={() => handleMarkRead(n.id)} className="text-xs text-gray-400 hover:text-indigo-600" title={t("notifications.mark_read")}>
                      ✓
                    </button>
                  )}
                  <button onClick={() => handleDelete(n.id)} className="text-xs text-gray-400 hover:text-red-600" title={t("notifications.dismiss")}>
                    ✕
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        {pages > 1 && (
          <div className="flex justify-center gap-2 mt-4">
            {Array.from({ length: pages }, (_, i) => (
              <button
                key={i}
                onClick={() => setPage(i + 1)}
                className={`px-3 py-1 rounded text-sm ${page === i + 1 ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-gray-700 dark:text-gray-300"}`}
              >
                {i + 1}
              </button>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
