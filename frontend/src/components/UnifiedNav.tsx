import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  House, FileText, ArrowLeftRight, Users, Wrench,
  Calendar, BarChart2,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";
import { getIncomingSwapCount } from "../api/swaps";
import { listPendingEnrollments } from "../api/enrollment";
import { getPendingHakpazaCount } from "../api/hakpaza";
import NavSheet from "./NavSheet";

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
  const canApprove = role === "commander" || role === "duty_manager" || role === "admin";
  const canPlan = role === "duty_manager" || role === "admin";

  const [pendingCount, setPendingCount] = useState(0);
  const [swapIncomingCount, setSwapIncomingCount] = useState(0);
  const [commanderSheetOpen, setCommanderSheetOpen] = useState(false);
  const [planningSheetOpen, setPlanningSheetOpen] = useState(false);

  useEffect(() => {
    if (!canApprove) return;
    void (async () => {
      const [c, e, f, enroll, hk] = await Promise.all([
        getPendingCount().catch(() => 0),
        getPendingExemptionCount().catch(() => 0),
        getPendingFieldUpdateCount().catch(() => 0),
        listPendingEnrollments().then((r) => r.length).catch(() => 0),
        getPendingHakpazaCount().catch(() => 0),
      ]);
      setPendingCount(c + e + f + enroll + hk);
    })();
  }, [canApprove, location.pathname]);

  useEffect(() => {
    void (async () => {
      const count = await getIncomingSwapCount().catch(() => 0);
      setSwapIncomingCount(count);
    })();
  }, [location.pathname]);

  useEffect(() => {
    const vv = (window as Window & { visualViewport?: VisualViewport }).visualViewport;
    if (!vv) return;
    const update = () => {
      document.documentElement.style.setProperty("--vvh", `${vv.height}px`);
    };
    vv.addEventListener("resize", update);
    vv.addEventListener("scroll", update);
    update();
    return () => {
      vv.removeEventListener("resize", update);
      vv.removeEventListener("scroll", update);
    };
  }, []);

  const baseTabs: NavTab[] = [
    { label: t("nav.home"), icon: <House size={20} />, to: "/", testId: "nav-home" },
    { label: t("nav.my_requests"), icon: <FileText size={20} />, to: "/my-requests", testId: "nav-my-requests" },
    { label: t("nav.swaps"), icon: <ArrowLeftRight size={20} />, to: "/swaps", badge: swapIncomingCount, testId: "nav-swaps" },
    { label: t("nav.unit_calendar"), icon: <Calendar size={20} />, to: "/unit-calendar", testId: "nav-unit-calendar" },
    { label: t("nav.transparency"), icon: <BarChart2 size={20} />, to: "/transparency", testId: "nav-transparency" },
  ];

  const commanderTab: NavTab = {
    label: t("nav.commander"),
    icon: <Users size={20} />,
    onClick: () => setCommanderSheetOpen(true),
    badge: pendingCount,
    testId: "nav-commander",
  };

  const planningTab: NavTab = {
    label: t("nav.planning"),
    icon: <Wrench size={20} />,
    onClick: () => setPlanningSheetOpen(true),
    testId: "nav-planning",
  };

  const tabs: NavTab[] = [
    ...baseTabs,
    ...(canApprove ? [commanderTab] : []),
    ...(canPlan ? [planningTab] : []),
  ];

  const commanderItems = [
    { label: t("nav.team_hierarchy"), to: "/team", testId: "nav-team" },
    { label: t("nav.approvals"), to: "/approvals", badge: pendingCount, testId: "nav-approvals" },
    { label: t("nav.command_dashboard"), to: "/command-dashboard", testId: "nav-command-dashboard" },
    { label: "הקפצה פיקודית", to: "/commander/hakpaza", testId: "nav-hakpaza" },
  ];

  const planningItems = [
    { label: t("nav.planning_shifts"), to: "/planning/shifts", testId: "nav-shifts-management" },
    { label: t("nav.planning_assignment"), to: "/planning/assignment", testId: "nav-assignment" },
    { label: t("nav.planning_config"), to: "/planning/config", testId: "nav-duty-config" },
    { label: t("nav.score_adjustments"), to: "/planning/score-adjustments", testId: "nav-score-adjustments" },
    { label: "ייבוא מ-Excel", to: "/import", testId: "nav-import" },
  ];

  const isActive = (to?: string) => {
    if (!to) return false;
    if (to === "/") return location.pathname === "/";
    return location.pathname.startsWith(to);
  };

  const tabContent = (tab: NavTab) => (
    <>
      {tab.icon}
      {tab.badge != null && tab.badge > 0 && (
        <span
          className="absolute top-1 right-1/4 md:top-2 md:left-3 bg-red-500 text-white text-[10px] rounded-full px-1.5 leading-5"
          data-testid="pending-badge"
        >
          {tab.badge}
        </span>
      )}
      <span className="text-center leading-tight">{tab.label}</span>
    </>
  );

  const mobileTabClass = (active: boolean) =>
    `flex-1 flex flex-col items-center justify-center py-2 min-h-[56px] text-xs gap-1 relative ${
      active ? "text-indigo-600 dark:text-indigo-300" : "text-gray-400 dark:text-gray-500"
    }`;

  const desktopTabClass = (active: boolean) =>
    `relative flex flex-col items-center justify-center py-4 gap-1 text-xs w-full ${
      active ? "text-indigo-600 dark:text-indigo-300" : "text-gray-400 hover:text-gray-600 dark:text-gray-500"
    }`;

  return (
    <>
      <NavSheet
        open={commanderSheetOpen}
        onClose={() => setCommanderSheetOpen(false)}
        items={commanderItems}
        testId="commander-sheet"
      />
      <NavSheet
        open={planningSheetOpen}
        onClose={() => setPlanningSheetOpen(false)}
        items={planningItems}
        testId="planning-sheet"
      />

      {/* Mobile bottom bar */}
      <nav
        aria-label="ניווט ראשי"
        className="md:hidden fixed bottom-0 left-0 right-0 bg-white border-t z-30 dark:bg-gray-800 dark:border-gray-700"
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
                {tabContent(tab)}
              </Link>
            ) : (
              <button
                key={tab.testId}
                onClick={tab.onClick}
                className={mobileTabClass(false)}
                data-testid={tab.testId}
              >
                {tabContent(tab)}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Desktop sidebar */}
      <nav
        aria-label="ניווט צדדי"
        className="hidden md:flex fixed right-0 top-0 bottom-0 w-24 bg-white border-l flex-col z-30 dark:bg-gray-800 dark:border-gray-700"
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
                <span className="absolute inset-x-2 inset-y-1 bg-indigo-50 dark:bg-indigo-900 rounded-lg -z-10" />
              )}
              {tabContent(tab)}
            </Link>
          ) : (
            <button
              key={tab.testId}
              onClick={tab.onClick}
              className={desktopTabClass(false)}
              data-testid={`desktop-${tab.testId}`}
            >
              {tabContent(tab)}
            </button>
          );
        })}
      </nav>
    </>
  );
}
