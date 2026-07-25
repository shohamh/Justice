import { ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CircleUser, Settings, HelpCircle } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import NotificationBell from "./NotificationBell";
import UnifiedNav from "./UnifiedNav";
import HelpModal from "./HelpModal";
import HeaderSearch from "./HeaderSearch";
import { getPublicSettings } from "../api/publicSettings";
import JusticeLogo from "./JusticeLogo";

export default function Layout({ children }: { children: ReactNode | ((openHelp: (tab?: string) => void) => ReactNode) }) {
  const { t } = useTranslation();
  const { logout, user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpTab, setHelpTab] = useState<string | undefined>(undefined);
  const [gimelimEnabled, setGimelimEnabled] = useState(true);

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

  return (
    <div className="h-[100dvh] flex flex-col md:mr-24 dark:bg-gray-900 dark:text-gray-100">
      <UnifiedNav />
      {helpOpen && <HelpModal onClose={() => setHelpOpen(false)} gimelimEnabled={gimelimEnabled} initialTab={helpTab} />}
      <header className="bg-white shadow-sm border-b dark:bg-gray-800 dark:border-gray-700">
        <div className="px-4 py-3 flex items-center justify-between">
          {/* Left side: profile icon + optional gear icon */}
          <div className="flex items-center gap-3">
            <Link to="/profile" aria-label={t("nav.profile")} className="text-gray-500 hover:text-indigo-600">
              <CircleUser size={22} />
            </Link>
            {isAdmin && (
              <Link to="/admin/settings" aria-label={t("nav.admin_settings")} className="text-gray-500 hover:text-indigo-600">
                <Settings size={22} />
              </Link>
            )}
          </div>
          {/* Center: app logo */}
          <JusticeLogo size="sm" />
          {/* Right side: help + notification bell + logout */}
          <div className="flex items-center gap-4">
            <HeaderSearch openHelp={openHelp} />
            <button
              onClick={() => openHelp()}
              aria-label="עזרה"
              className="text-gray-500 hover:text-indigo-600"
            >
              <HelpCircle size={22} />
            </button>
            <NotificationBell />
            <button
              onClick={() => logout()}
              className="text-sm text-indigo-600 dark:text-indigo-300 hover:text-indigo-800 dark:hover:text-indigo-200"
              data-testid="logout-button"
            >
              {t("home.logout")}
            </button>
          </div>
        </div>
      </header>
      <main className="flex-1 overflow-y-auto px-4 py-6 pb-24 md:pb-6">
        {typeof children === "function" ? children(openHelp) : children}
      </main>
    </div>
  );
}
