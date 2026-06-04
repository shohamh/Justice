import { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CircleUser, Settings } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import NotificationBell from "./NotificationBell";
import UnifiedNav from "./UnifiedNav";

export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { logout, user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <div className="min-h-screen flex flex-col md:mr-24">
      <UnifiedNav />
      <header className="bg-white shadow-sm border-b">
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
          {/* Center: app title */}
          <h1 className="text-lg font-bold">{t("app.title")}</h1>
          {/* Right side: notification bell + logout */}
          <div className="flex items-center gap-4">
            <NotificationBell />
            <button
              onClick={() => logout()}
              className="text-sm text-indigo-600 hover:text-indigo-800"
              data-testid="logout-button"
            >
              {t("home.logout")}
            </button>
          </div>
        </div>
      </header>
      <main className="flex-1 px-4 py-6 pb-20 md:pb-6">{children}</main>
    </div>
  );
}
