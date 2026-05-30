import { ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/AuthContext";
import { getPendingCount } from "../api/constraints";

export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const role = user?.role;
  const canManageTeam = role === "duty_manager" || role === "admin" || role === "commander";
  const canManageDuties = role === "duty_manager" || role === "admin";
  const canApprove = role === "duty_manager" || role === "admin" || role === "commander";
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    if (canApprove) {
      getPendingCount().then(setPendingCount).catch(() => {});
    }
  }, [canApprove]);

  return (
    <div className="min-h-screen flex">
      <aside className="w-56 bg-white border-l shadow-sm p-4 space-y-2" data-testid="sidebar">
        <Link to="/" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-home">{t("nav.home")}</Link>
        <Link to="/my-duties" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-my-duties">{t("nav.my_duties")}</Link>
        <Link to="/my-requests" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-my-requests">{t("nav.my_requests")}</Link>
        <Link to="/transparency" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-transparency">{t("nav.transparency")}</Link>
        {canManageTeam && (
          <Link to="/team" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-team">{t("nav.team_hierarchy")}</Link>
        )}
        {canManageTeam && (
          <Link to="/unit-calendar" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-unit-calendar">{t("nav.unit_calendar")}</Link>
        )}
        {canApprove && (
          <Link to="/approvals" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-approvals">
            {t("nav.approvals")}
            {pendingCount > 0 && (
              <span className="mr-2 bg-red-500 text-white text-xs rounded-full px-2 py-0.5" data-testid="pending-badge">
                {pendingCount}
              </span>
            )}
          </Link>
        )}
        {canManageDuties && (
          <Link to="/duty-config" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-duty-config">{t("nav.duty_config")}</Link>
        )}
        {canManageDuties && (
          <Link to="/duty-management" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-duty-management">{t("nav.duty_management")}</Link>
        )}
        {canManageDuties && (
          <Link to="/shifts" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-shifts">{t("shifts.title")}</Link>
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
