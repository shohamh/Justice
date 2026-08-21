import { useState, useEffect, useRef, type CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { getUnreadCount, listNotifications, markRead, markAllRead, deleteNotification, getNotificationLink, NotificationDTO, NOTIFICATION_TYPE_ICONS, isQuickDecisionNotification } from "../api/notifications";
import { soldierApproveSwap, soldierRejectSwap } from "../api/swaps";
import { decideRangeExcusal } from "../api/ranges";
import { Check, Eye, X, Trash2 } from "lucide-react";
import { useBugReportModal } from "../contexts/BugReportModalContext";

export default function NotificationBell() {
  const { t } = useTranslation();
  const { openBugReportModal } = useBugReportModal();
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationDTO[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [dropdownStyle, setDropdownStyle] = useState<CSSProperties>({});
  const navigate = useNavigate();

  const openRef = useRef(open);
  useEffect(() => { openRef.current = open; }, [open]);

  useEffect(() => {
    const fetch = async () => {
      try {
        const { count } = await getUnreadCount();
        setUnread(count);
      } catch { /* ignore */ }
      if (openRef.current) {
        listNotifications({ is_read: false, limit: 5 }).then((r) => setNotifications(r.items)).catch(() => {});
      }
    };
    fetch();
    const interval = setInterval(fetch, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (open) {
      listNotifications({ is_read: false, limit: 5 }).then((r) => setNotifications(r.items)).catch(() => {});
    }
  }, [open]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  async function handleMarkRead(id: string) {
    await markRead(id).catch(() => {});
    setNotifications((prev) => prev.filter((n) => n.id !== id));
    setUnread((u) => Math.max(0, u - 1));
  }

  async function handleDelete(id: string) {
    await deleteNotification(id).catch(() => {});
    setNotifications((prev) => prev.filter((n) => n.id !== id));
    setUnread((u) => Math.max(0, u - 1));
  }

  async function handleMarkAll() {
    const { count } = await markAllRead().catch(() => ({ count: 0 }));
    setUnread(Math.max(0, unread - count));
    setNotifications([]);
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
      setNotifications((prev) => prev.filter((x) => x.id !== n.id));
      setUnread((u) => Math.max(0, u - 1));
    } catch { /* ignore — surfaced via the full review page if it fails */ }
  }

  function handleNotificationClick(n: NotificationDTO) {
    void handleMarkRead(n.id);
    if (n.reference_type === "bug_report" && n.reference_id) {
      openBugReportModal({ tab: "mine", reportId: n.reference_id });
    } else {
      const link = getNotificationLink(n);
      if (link) navigate(link);
    }
    setOpen(false);
  }

  return (
    <div ref={ref}>
      <button
        ref={buttonRef}
        onClick={() => {
          if (!open && buttonRef.current) {
            const rect = buttonRef.current.getBoundingClientRect();
            const dropdownWidth = 320;
            const margin = 8;
            const left = Math.max(margin, Math.min(rect.left, window.innerWidth - dropdownWidth - margin));
            setDropdownStyle({ position: "fixed", top: rect.bottom + margin, left });
          }
          setOpen((o) => !o);
        }}
        className="relative text-gray-500 hover:text-indigo-600 p-1"
        data-testid="notification-bell"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div style={dropdownStyle} className="w-80 bg-white dark:bg-gray-800 rounded-lg shadow-lg border dark:border-gray-700 z-50 rtl:text-right" data-testid="notification-dropdown">
          <div className="flex items-center justify-between p-3 border-b dark:border-gray-700">
            <span className="font-semibold">{t("notifications.title")}</span>
            {notifications.length > 0 && (
              <button onClick={handleMarkAll} className="text-xs text-indigo-600 hover:text-indigo-800">
                {t("notifications.mark_all_read")}
              </button>
            )}
          </div>
          <div className="max-h-64 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="p-4 text-center text-gray-500 text-sm">{t("notifications.none")}</div>
            ) : (
              notifications.map((n) => (
                <div key={n.id} className="flex items-start gap-2 p-3 border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700">
                  <span className="text-lg" aria-label={t(`notifications.type_${n.type}`, { defaultValue: n.type })}>{NOTIFICATION_TYPE_ICONS[n.type] || "🔔"}</span>
                  <div className="flex-1 min-w-0">
                    {getNotificationLink(n) || (n.reference_type === "bug_report" && n.reference_id) ? (
                      <button
                        className="text-sm font-medium truncate text-right w-full hover:text-indigo-600"
                        onClick={() => handleNotificationClick(n)}
                      >
                        {n.title}
                      </button>
                    ) : (
                      <p className="text-sm font-medium truncate">{n.title}</p>
                    )}
                    {n.body && <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{n.body}</p>}
                    {n.sender_name && <p className="text-xs text-gray-400 truncate">{t("notifications.sent_by", { name: n.sender_name })}</p>}
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
              ))
            )}
          </div>
          <Link to="/notifications" className="block p-3 text-center text-sm text-indigo-600 hover:text-indigo-800 border-t">
            {t("notifications.view_all")}
          </Link>
        </div>
      )}
    </div>
  );
}
