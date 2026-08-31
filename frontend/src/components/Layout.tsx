import { ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CircleUser, Settings, HelpCircle, Sun, Moon, Monitor, LogOut } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../theme/ThemeContext";
import NotificationBell from "./NotificationBell";
import UnifiedNav from "./UnifiedNav";
import HelpModal from "./HelpModal";
import HeaderSearch from "./HeaderSearch";
import { getPublicSettings } from "../api/publicSettings";
import JusticeLogo from "./JusticeLogo";
import BugReportTrigger from "./BugReportTrigger";
import { getAdminBugReportUnreadCount, getAdminErrorUnreadCount } from "../api/bugReports";
import { useQuery } from "@tanstack/react-query";

export default function Layout({ children }: { children: ReactNode | ((openHelp: (tab?: string) => void) => ReactNode) }) {
  const { t } = useTranslation();
  const { logout, user } = useAuth();
  const { theme, cycleTheme } = useTheme();
  const themeIcon = theme === "light" ? <Sun size={20} /> : theme === "dark" ? <Moon size={20} /> : <Monitor size={20} />;
  const themeLabel =
    theme === "light" ? "מצב תאורה: בהיר (לחץ למעבר לכהה)" :
    theme === "dark" ? "מצב תאורה: כהה (לחץ למעבר לפי מערכת)" :
    "מצב תאורה: לפי מערכת (לחץ למעבר לבהיר)";
  const isAdmin = user?.role === "admin";
  const errorUnread = useQuery({ queryKey: ["admin-errors-unread"], queryFn: getAdminErrorUnreadCount, enabled: isAdmin, refetchInterval: 30000 });
  const bugUnread = useQuery({ queryKey: ["admin-bug-reports-unread"], queryFn: getAdminBugReportUnreadCount, enabled: isAdmin, refetchInterval: 30000 });
  const adminUnread = (errorUnread.data ?? 0) + (bugUnread.data ?? 0);
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpTab, setHelpTab] = useState<string | undefined>(undefined);
  const [gimelimEnabled, setGimelimEnabled] = useState(true);
  const [hakpazaEnabled, setHakpazaEnabled] = useState(false);

  function openHelp(tab?: string) {
    setHelpTab(tab);
    setHelpOpen(true);
  }

  useEffect(() => {
    getPublicSettings().then((settings) => {
      const enabled = settings["gimalim.enabled"];
      setGimelimEnabled(enabled === true || enabled === undefined);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    getPublicSettings().then((settings) => {
      setHakpazaEnabled(settings["forced_callup.enabled"] === true);
    }).catch(() => {});
  }, []);

  return (
    <div className="h-[100dvh] flex flex-col md:mr-24 dark:bg-gray-900 dark:text-gray-100">
      <UnifiedNav />
      <BugReportTrigger />
      {helpOpen && <HelpModal onClose={() => setHelpOpen(false)} gimelimEnabled={gimelimEnabled} hakpazaEnabled={hakpazaEnabled} initialTab={helpTab} />}
      <header className="bg-white shadow-sm border-b dark:bg-gray-800 dark:border-gray-700">
        <div className="px-2 py-2 sm:px-4 sm:py-3 flex items-center justify-between gap-1">
          {/* Left side (DOM order): profile icon + optional gear icon + theme toggle.
              This renders on the screen's visual RIGHT edge, since the app is RTL. */}
          <div className="flex items-center gap-1.5 sm:gap-3 shrink-0">
            <Link to="/profile" aria-label={t("nav.profile")} className="text-gray-500 hover:text-indigo-600">
              <CircleUser size={20} />
            </Link>
            {isAdmin && (
              <Link to="/admin/settings" aria-label={t("nav.admin_settings")} className="relative text-gray-500 hover:text-indigo-600">
                <Settings size={20} />
                {adminUnread > 0 && <span className="absolute -top-2 -right-2 min-w-4 h-4 px-1 rounded-full bg-red-600 text-white text-[10px] leading-4 text-center" data-testid="admin-settings-unread-badge">{adminUnread > 99 ? "99+" : adminUnread}</span>}
              </Link>
            )}
            <button
              onClick={cycleTheme}
              aria-label={themeLabel}
              title={themeLabel}
              data-testid="theme-toggle-button"
              className="text-gray-500 hover:text-indigo-600"
            >
              {themeIcon}
            </button>
          </div>
          {/* Center: app logo */}
          <Link to="/" aria-label={t("nav.home")} className="min-w-0 shrink overflow-hidden">
            <JusticeLogo size="sm" />
          </Link>
          {/* Right side (DOM order): search + help + notification bell + logout.
              This renders on the screen's visual LEFT edge, since the app is RTL. */}
          <div className="flex items-center gap-1.5 sm:gap-4 shrink-0">
            <HeaderSearch openHelp={openHelp} />
            <button
              onClick={() => openHelp()}
              aria-label="עזרה"
              className="text-gray-500 hover:text-indigo-600"
            >
              <HelpCircle size={20} />
            </button>
            <NotificationBell />
            <button
              onClick={() => logout()}
              aria-label={t("home.logout")}
              title={t("home.logout")}
              className="sm:hidden text-indigo-600 dark:text-indigo-300 hover:text-indigo-800 dark:hover:text-indigo-200"
              data-testid="logout-button-mobile"
            >
              <LogOut size={20} />
            </button>
            <button
              onClick={() => logout()}
              className="hidden sm:inline text-sm whitespace-nowrap text-indigo-600 dark:text-indigo-300 hover:text-indigo-800 dark:hover:text-indigo-200"
              data-testid="logout-button"
            >
              {t("home.logout")}
            </button>
          </div>
        </div>
      </header>
      <main
        className="flex-1 overflow-y-auto px-4 py-6 pb-24 md:pb-6"
        data-bug-report-scroll-container
      >
        <div data-bug-report-scroll-content>
          {typeof children === "function" ? children(openHelp) : children}
        </div>
      </main>
    </div>
  );
}
