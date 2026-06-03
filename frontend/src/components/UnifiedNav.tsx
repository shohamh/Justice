import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  House, Shield, FileText, ArrowLeftRight, CircleUser,
  ClipboardCheck, LayoutGrid,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";
import ManageSheet from "./ManageSheet";

interface NavTab {
  label: string;
  icon: React.ReactNode;
  to?: string;
  onClick?: () => void;
  badge?: number;
  testId: string;
}

export default function UnifiedNav() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const location = useLocation();
  const role = user?.role;
  const canApprove = role === "duty_manager" || role === "admin" || role === "commander";
  const [pendingCount, setPendingCount] = useState(0);
  const [manageOpen, setManageOpen] = useState(false);

  useEffect(() => {
    if (!canApprove) return;
    void (async () => {
      const [c, e, f] = await Promise.all([
        getPendingCount().catch(() => 0),
        getPendingExemptionCount().catch(() => 0),
        getPendingFieldUpdateCount().catch(() => 0),
      ]);
      setPendingCount(c + e + f);
    })();
  }, [canApprove, location.pathname]);

  const soldierTabs: NavTab[] = [
    { label: t("nav.home"), icon: <House size={20} />, to: "/", testId: "nav-home" },
    { label: t("nav.my_duties"), icon: <Shield size={20} />, to: "/my-duties", testId: "nav-my-duties" },
    { label: t("nav.my_requests"), icon: <FileText size={20} />, to: "/my-requests", testId: "nav-my-requests" },
    { label: t("nav.swaps"), icon: <ArrowLeftRight size={20} />, to: "/swaps", testId: "nav-swaps" },
    { label: t("nav.profile"), icon: <CircleUser size={20} />, to: "/profile", testId: "nav-profile" },
  ];

  const managerTabs: NavTab[] = [
    { label: t("nav.home"), icon: <House size={20} />, to: "/", testId: "nav-home" },
    { label: t("nav.my_duties"), icon: <Shield size={20} />, to: "/my-duties", testId: "nav-my-duties" },
    { label: t("nav.approvals"), icon: <ClipboardCheck size={20} />, to: "/approvals", badge: pendingCount, testId: "nav-approvals" },
    { label: t("nav.manage"), icon: <LayoutGrid size={20} />, onClick: () => setManageOpen(true), testId: "nav-manage" },
    { label: t("nav.profile"), icon: <CircleUser size={20} />, to: "/profile", testId: "nav-profile" },
  ];

  const tabs = canApprove ? managerTabs : soldierTabs;

  const isActive = (to?: string) => {
    if (!to) return false;
    if (to === "/") return location.pathname === "/";
    return location.pathname.startsWith(to);
  };

  const tabContent = (tab: NavTab, active: boolean, isDesktop = false) => (
    <>
      {tab.icon}
      {tab.badge != null && tab.badge > 0 && (
        <span
          className="absolute top-1 right-1/4 md:top-2 md:left-3 bg-red-500 text-white text-[10px] rounded-full px-1.5 leading-5"
          data-testid={isDesktop ? "desktop-pending-badge" : "pending-badge"}
        >
          {tab.badge}
        </span>
      )}
      <span className="text-center leading-tight">{tab.label}</span>
    </>
  );

  const mobileTabClass = (active: boolean) =>
    `flex-1 flex flex-col items-center justify-center py-2 min-h-[56px] text-xs gap-1 relative ${
      active ? "text-indigo-600" : "text-gray-400"
    }`;

  const desktopTabClass = (active: boolean) =>
    `relative flex flex-col items-center justify-center py-4 gap-1 text-xs w-full ${
      active ? "text-indigo-600" : "text-gray-400 hover:text-gray-600"
    }`;

  return (
    <>
      <ManageSheet open={manageOpen} onClose={() => setManageOpen(false)} />

      {/* Mobile bottom bar */}
      <nav
        aria-label="ניווט ראשי"
        className="md:hidden fixed bottom-0 left-0 right-0 bg-white border-t z-30"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <div className="flex">
          {tabs.map((tab) => {
            const active = isActive(tab.to);
            return tab.to ? (
              <Link
                key={tab.testId}
                to={tab.to}
                className={mobileTabClass(active)}
                data-testid={tab.testId}
              >
                {tabContent(tab, active)}
              </Link>
            ) : (
              <button
                key={tab.testId}
                onClick={tab.onClick}
                className={mobileTabClass(active)}
                data-testid={tab.testId}
              >
                {tabContent(tab, active)}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Desktop sidebar */}
      <nav
        aria-label="ניווט צדדי"
        className="hidden md:flex fixed right-0 top-0 bottom-0 w-24 bg-white border-l flex-col z-30"
        data-testid="sidebar"
      >
        {tabs.map((tab) => {
          const active = isActive(tab.to);
          return tab.to ? (
            <Link
              key={tab.testId}
              to={tab.to}
              className={desktopTabClass(active)}
              data-testid={`desktop-${tab.testId}`}
            >
              {active && (
                <span className="absolute inset-x-2 inset-y-1 bg-indigo-50 rounded-lg -z-10" />
              )}
              {tabContent(tab, active, true)}
            </Link>
          ) : (
            <button
              key={tab.testId}
              onClick={tab.onClick}
              className={desktopTabClass(active)}
              data-testid={`desktop-${tab.testId}`}
            >
              {active && (
                <span className="absolute inset-x-2 inset-y-1 bg-indigo-50 rounded-lg -z-10" />
              )}
              {tabContent(tab, active, true)}
            </button>
          );
        })}
      </nav>
    </>
  );
}
