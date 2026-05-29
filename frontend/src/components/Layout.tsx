import { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/AuthContext";

export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const role = user?.role;
  const canManageTeam = role === "duty_manager" || role === "admin" || role === "commander";

  return (
    <div className="min-h-screen flex">
      <aside className="w-56 bg-white border-l shadow-sm p-4 space-y-2" data-testid="sidebar">
        <Link to="/" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-home">{t("nav.home")}</Link>
        {canManageTeam && (
          <Link to="/team" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-team">{t("nav.team_hierarchy")}</Link>
        )}
        <Link to="/profile" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-profile">{t("nav.profile")}</Link>
      </aside>
      <div className="flex-1 flex flex-col">
        <header className="bg-white shadow-sm border-b">
          <div className="px-4 py-3 flex items-center justify-between">
            <h1 className="text-lg font-bold">{t("app.title")}</h1>
            <button onClick={() => logout()} className="text-sm text-indigo-600 hover:text-indigo-800" data-testid="logout-button">
              {t("home.logout")}
            </button>
          </div>
        </header>
        <main className="flex-1 px-4 py-6">{children}</main>
      </div>
    </div>
  );
}
