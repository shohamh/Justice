import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import { usePagePagination } from "../hooks/usePagePagination";
import { listNotifications, markRead, markAllRead, deleteNotification, getNotificationLink, NotificationDTO, NOTIFICATION_TYPE_ICONS, isQuickDecisionNotification } from "../api/notifications";
import { soldierApproveSwap, soldierRejectSwap } from "../api/swaps";
import { decideRangeExcusal } from "../api/ranges";
import { Check, ChevronDown, ChevronUp, Eye, X, Trash2 } from "lucide-react";
import { useBugReportModal } from "../contexts/BugReportModalContext";
import { getNotificationTitle, NotificationDetails } from "../components/notifications/NotificationDetails";

export default function NotificationsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { openBugReportModal } = useBugReportModal();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<string>("all");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
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

  async function handleDecision(n: NotificationDTO, approve: boolean) {
    try {
      if (n.type === "swap_offer_incoming" && n.reference_id) {
        await (approve ? soldierApproveSwap(n.reference_id) : soldierRejectSwap(n.reference_id));
      } else if (n.type === "range_excusal_pending" && n.reference_id) {
        const eventId = n.metadata?.event_id as string | undefined;
        if (!eventId) return;
        await decideRangeExcusal(eventId, n.reference_id, approve);
      } else {
        return;
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.notificationsList() });
    } catch { /* ignore — individual failures surface through the swap/range pages */ }
  }

  function handleNotificationClick(n: NotificationDTO) {
    if (n.reference_type === "bug_report" && n.reference_id) {
      openBugReportModal({ tab: "mine", reportId: n.reference_id });
    } else {
      const link = getNotificationLink(n);
      if (link) navigate(link);
    }
  }

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
        {notificationsQuery.isError && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400 mb-4" dir="rtl">
            {t("notifications.load_error")}
          </p>
        )}
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
          !notificationsQuery.isError && <p className="text-gray-500">{t("notifications.none")}</p>
        ) : (
          <div className="space-y-2">
            {notifications.map((n) => (
              <div key={n.id} className={`flex items-start gap-3 p-3 rounded border dark:border-gray-600 ${n.is_read ? "bg-gray-50 dark:bg-gray-700" : "bg-white dark:bg-gray-800"}`}>
                <span className="text-xl" aria-label={t(`notifications.type_${n.type}`, { defaultValue: n.type })}>{NOTIFICATION_TYPE_ICONS[n.type] || "🔔"}</span>
                <div className="flex-1">
                  {getNotificationLink(n) || (n.reference_type === "bug_report" && n.reference_id) ? (
                    <button className={`text-right ${n.is_read ? "text-gray-600 dark:text-gray-300" : "font-semibold"}`} onClick={() => handleNotificationClick(n)}>{getNotificationTitle(n, t)}</button>
                  ) : (
                    <p className={`${n.is_read ? "text-gray-600 dark:text-gray-300" : "font-semibold"}`}>{getNotificationTitle(n, t)}</p>
                  )}
                  <NotificationDetails notification={n} expanded={expandedIds.has(n.id)} t={t} />
                  {n.sender_name && <p className="text-xs text-gray-400 mt-0.5">{t("notifications.sent_by", { name: n.sender_name })}</p>}
                  <p className="text-xs text-gray-400 mt-1">{new Date(n.created_at).toLocaleString("he-IL")}</p>
                  {n.body && <button
                    type="button"
                    className="mt-1 text-xs text-indigo-600 hover:text-indigo-800 dark:text-indigo-300"
                    aria-expanded={expandedIds.has(n.id)}
                    aria-label={expandedIds.has(n.id) ? t("notifications.collapse_details") : t("notifications.expand_details")}
                    onClick={() => setExpandedIds((current) => {
                      const next = new Set(current);
                      if (next.has(n.id)) next.delete(n.id); else next.add(n.id);
                      return next;
                    })}
                  >
                    {expandedIds.has(n.id) ? <><ChevronUp size={14} className="inline" /> {t("notifications.collapse_details")}</>
                      : <><ChevronDown size={14} className="inline" /> {t("notifications.expand_details")}</>}
                  </button>}
                </div>
                <div className="flex gap-1">
                  {isQuickDecisionNotification(n) && (
                    <>
                      <button
                        onClick={() => handleDecision(n, true)}
                        className="p-1.5 rounded bg-green-100 text-green-700 hover:bg-green-200 dark:bg-green-900 dark:text-green-300 dark:hover:bg-green-800"
                        aria-label={t("notifications.approve")}
                        title={t("notifications.approve")}
                      >
                        <Check size={14} />
                      </button>
                      <button
                        onClick={() => handleDecision(n, false)}
                        className="p-1.5 rounded bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-900 dark:text-red-300 dark:hover:bg-red-800"
                        aria-label={t("notifications.reject")}
                        title={t("notifications.reject")}
                      >
                        <X size={14} />
                      </button>
                    </>
                  )}
                  <button onClick={() => handleMarkRead(n.id)} className="p-1.5 rounded text-gray-500 hover:bg-gray-200 dark:text-gray-400 dark:hover:bg-gray-600" aria-label={t("notifications.mark_read")} title={t("notifications.mark_read")}>
                    <Eye size={14} />
                  </button>
                  <button onClick={() => handleDelete(n.id)} className="p-1.5 rounded text-gray-500 hover:bg-red-100 hover:text-red-600 dark:text-gray-400 dark:hover:bg-red-900" aria-label={t("notifications.dismiss")} title={t("notifications.dismiss")}>
                    <Trash2 size={14} />
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
