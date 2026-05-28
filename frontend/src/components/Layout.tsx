import { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/AuthContext";

export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { logout, mustChangePassword } = useAuth();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <h1 className="text-lg font-bold">{t("app.title")}</h1>
          <button onClick={() => logout()} className="text-sm text-indigo-600 hover:text-indigo-800" data-testid="logout-button">
            {t("home.logout")}
          </button>
        </div>
      </header>
      {mustChangePassword && (
        <div className="bg-pending/10 border-b border-pending/30 text-pending px-4 py-2 text-sm" data-testid="must-change-password-banner">
          {t("common.must_change_password")}
        </div>
      )}
      <main className="flex-1 max-w-6xl mx-auto w-full px-4 py-6">{children}</main>
    </div>
  );
}
