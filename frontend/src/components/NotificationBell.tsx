import { useState, useEffect, useRef, type CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { getUnreadCount, listNotifications, markRead, markAllRead, deleteNotification, NotificationDTO } from "../api/notifications";

export default function NotificationBell() {
  const { t } = useTranslation();
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationDTO[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [dropdownStyle, setDropdownStyle] = useState<CSSProperties>({});
  const navigate = useNavigate();

  function notifLink(n: NotificationDTO): string | null {
    if (n.reference_type === "algorithm_job" && n.reference_id) {
      return `/algorithm?jobId=${n.reference_id}`;
    }
    if (n.reference_type === "swap_request") {
      return n.type === "swap_offer" ? "/swaps?tab=incoming" : "/swaps?tab=mine";
    }
    if (n.reference_type === "personal_constraint" || n.reference_type === "exemption_request") {
      return "/my-requests";
    }
    if (n.reference_type === "duty_assignment") {
      return "/";
    }
    return null;
  }

  useEffect(() => {
    const fetch = async () => {
      try {
        const { count } = await getUnreadCount();
        setUnread(count);
      } catch { /* ignore */ }
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

  const typeLabels: Record<string, string> = {
    swap_offer: "🔄", swap_accepted: "✅", swap_rejected: "❌",
    exemption_approved: "✔️", exemption_rejected: "✖️",
    constraint_approved: "✔️", constraint_rejected: "✖️",
    assignment_created: "📋", assignment_removed: "🗑️",
    range_reminder: "🔔", range_reminder_shortfall: "⚠️", range_assignment_confirmed: "🎯",
    score_adjusted: "⭐", announcement: "📢", system_announcement: "📣",
    algorithm_job_done: "🤖", algorithm_job_failed: "⚠️",
  };

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
                  <span className="text-lg">{typeLabels[n.type] || "🔔"}</span>
                  <div className="flex-1 min-w-0">
                    {notifLink(n) ? (
                      <button
                        className="text-sm font-medium truncate text-right w-full hover:text-indigo-600"
                        onClick={() => { void handleMarkRead(n.id); navigate(notifLink(n)!); setOpen(false); }}
                      >
                        {n.title}
                      </button>
                    ) : (
                      <p className="text-sm font-medium truncate">{n.title}</p>
                    )}
                    {n.body && <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{n.body}</p>}
                  </div>
                  <div className="flex gap-1">
                    <button onClick={() => handleMarkRead(n.id)} className="text-xs text-gray-400 hover:text-gray-600" title={t("notifications.mark_read")}>✓</button>
                    <button onClick={() => handleDelete(n.id)} className="text-xs text-gray-400 hover:text-red-600" title={t("notifications.dismiss")}>✕</button>
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
