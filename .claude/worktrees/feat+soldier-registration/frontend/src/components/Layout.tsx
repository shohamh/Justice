import { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";
import NotificationBell from "./NotificationBell";
import UnifiedNav from "./UnifiedNav";

export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { logout } = useAuth();

  return (
    <div className="min-h-screen flex flex-col md:mr-24">
      <UnifiedNav />
      <header className="bg-white shadow-sm border-b">
        <div className="px-4 py-3 flex items-center justify-between">
          <h1 className="text-lg font-bold">{t("app.title")}</h1>
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
