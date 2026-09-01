import { useState, useEffect, useMemo, useRef } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  House, FileText, ArrowLeftRight, Users, Wrench,
  Calendar, BarChart2,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { usePublicSettings } from "../hooks/usePublicSettings";
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";
import { getIncomingSwapCount, isSwapActionableForUser, listPendingSwaps } from "../api/swaps";
import { listPendingEnrollments } from "../api/enrollment";
import { listPendingTransferRequests } from "../api/hierarchyTransfers";
import { getPendingHakpazaCount } from "../api/hakpaza";
import { getIneligibleSoldierCount } from "../api/ineligibleSoldiers";
import { queryKeys } from "../queryKeys";
import { listJobs } from "../api/algorithm";
import { computeRunBadgeCounts, RunBadgeCounts, RunBadgeJob } from "../utils/algorithmRunBadges";
import { useSeenJobs } from "../contexts/AlgorithmSeenContext";
import NavSheet, { BadgeColor } from "./NavSheet";

interface NavTab {
  label: string;
  icon: React.ReactNode;
  to?: string;
  onClick?: () => void;
  badge?: number;
  badgeColor?: BadgeColor;
  testId: string;
}

const BADGE_COLOR_CLASSES: Record<BadgeColor, string> = {
  red: "bg-red-500 text-white",
  blue: "bg-blue-500 text-white",
  yellow: "bg-yellow-500 text-gray-900",
  green: "bg-green-500 text-white",
};

function pickBadgeColor(counts: RunBadgeCounts): BadgeColor {
  if (counts.failed > 0) return "red";
  if (counts.running > 0) return "blue";
  if (counts.draft > 0) return "yellow";
  return "green";
}

type BadgeInput = Pick<NavTab, "badge" | "badgeColor">;

/** Yellow is the existing nav color for the brief's orange severity. */
export function aggregateBadgeCounts(items: BadgeInput[]): Pick<NavTab, "badge" | "badgeColor"> {
  const colorPriority: Record<BadgeColor, number> = { green: 0, blue: 1, yellow: 2, red: 3 };
  let badgeColor: BadgeColor = "green";
  let badge = 0;

  for (const item of items) {
    if (item.badge == null || item.badge <= 0) continue;
    badge += item.badge;
    const color = item.badgeColor ?? "red";
    if (colorPriority[color] > colorPriority[badgeColor]) badgeColor = color;
  }

  return { badge, badgeColor };
}

export default function UnifiedNav() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const location = useLocation();
  const settings = usePublicSettings();
  const queryClient = useQueryClient();
  const hakpazaEnabled = settings?.["forced_callup.enabled"] === true;
  const mitvachimEnabled = settings?.["mitvachim.enabled"] === true;
  const canViewTransparency = user?.can_view_transparency !== false;
  const canApprove = user?.role === "admin" || user?.is_commander || user?.is_duty_manager;
  const canPlan = user?.role === "admin" || user?.is_duty_manager;
  const [pendingCount, setPendingCount] = useState(0);
  const [swapIncomingCount, setSwapIncomingCount] = useState(0);
  const { seenIds, seedSeenIds } = useSeenJobs();
  const ineligibleCountQuery = useQuery({
    queryKey: queryKeys.ineligibleSoldierCount(),
    queryFn: getIneligibleSoldierCount,
    enabled: canPlan && mitvachimEnabled,
    retry: false,
  });
  const ineligibleCount = ineligibleCountQuery.data?.count ?? 0;
  const [algorithmJobs, setAlgorithmJobs] = useState<RunBadgeJob[]>([]);
  const algorithmCounts = useMemo(
    () => computeRunBadgeCounts(algorithmJobs, seenIds),
    [algorithmJobs, seenIds]
  );
  const algorithmBadgeCount = algorithmCounts.running + algorithmCounts.draft + algorithmCounts.done + algorithmCounts.failed;
  const algorithmBadgeColor = pickBadgeColor(algorithmCounts);
  const planningBadge = aggregateBadgeCounts([
    { badge: algorithmBadgeCount, badgeColor: algorithmBadgeColor },
    { badge: ineligibleCountQuery.data?.count, badgeColor: "red" },
  ]);
  const [commanderSheetOpen, setCommanderSheetOpen] = useState(false);
  const [planningSheetOpen, setPlanningSheetOpen] = useState(false);
  const previousPathname = useRef(location.pathname);

  useEffect(() => {
    if (!canApprove) return;
    void (async () => {
      const [c, e, f, enroll, hk, swaps, transfers] = await Promise.all([
        getPendingCount().catch(() => 0),
        getPendingExemptionCount().catch(() => 0),
        getPendingFieldUpdateCount().catch(() => 0),
        listPendingEnrollments().then((r) => r.length).catch(() => 0),
        getPendingHakpazaCount().catch(() => 0),
        listPendingSwaps().then((rows) => rows.filter((swap) => isSwapActionableForUser(swap, user?.id, user?.role === "admin")).length).catch(() => 0),
        listPendingTransferRequests().then((rows) => rows.length).catch(() => 0),
      ]);
      setPendingCount(c + e + f + enroll + hk + swaps + transfers);
    })();
  }, [canApprove, location.pathname, user?.id, user?.role]);

  useEffect(() => {
    void (async () => {
      const count = await getIncomingSwapCount().catch(() => 0);
      setSwapIncomingCount(count);
    })();
  }, [location.pathname]);

  useEffect(() => {
    if (!canPlan) return;

    async function fetchAlgorithmBadge() {
      try {
        const result = await listJobs(50);
        const items = Array.isArray(result?.items) ? result.items : [];
        setAlgorithmJobs(items);
        seedSeenIds(items);
      } catch {
        // ignore
      }
    }

    void fetchAlgorithmBadge();

    const interval = setInterval(() => void fetchAlgorithmBadge(), 30_000);
    return () => clearInterval(interval);
  }, [canPlan, location.pathname, seedSeenIds]);

  useEffect(() => {
    if (!canPlan || !mitvachimEnabled) return;
    if (previousPathname.current === location.pathname) return;
    previousPathname.current = location.pathname;
    void queryClient.invalidateQueries({ queryKey: queryKeys.ineligibleSoldierCount() });
  }, [canPlan, location.pathname, mitvachimEnabled, queryClient]);

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
    ...(canViewTransparency
      ? [{ label: t("nav.transparency"), icon: <BarChart2 size={20} />, to: "/transparency", testId: "nav-transparency" }]
      : []),
  ];

  const commanderTab: NavTab = {
    label: t("nav.commander"),
    icon: <Users size={20} />,
    onClick: () => setCommanderSheetOpen(true),
    badge: pendingCount,
    badgeColor: "blue",
    testId: "nav-commander",
  };

  const planningTab: NavTab = {
    label: t("nav.planning"),
    icon: <Wrench size={20} />,
    onClick: () => setPlanningSheetOpen(true),
    badge: planningBadge.badge,
    badgeColor: planningBadge.badgeColor,
    testId: "nav-planning",
  };

  const tabs: NavTab[] = [
    ...baseTabs,
    ...(canApprove ? [commanderTab] : []),
    ...(canPlan ? [planningTab] : []),
  ];

  const commanderItems = [
    { label: t("nav.team_hierarchy"), to: "/team", testId: "nav-team" },
    { label: t("nav.approvals"), to: "/approvals", badge: pendingCount, badgeColor: "blue" as BadgeColor, testId: "nav-approvals" },
    { label: t("nav.announcements"), to: "/announcements", testId: "nav-announcements" },
    ...(hakpazaEnabled
      ? [{ label: "הקפצה פיקודית", to: "/commander/hakpaza", testId: "nav-hakpaza" }]
      : []),
  ];

  const planningItems = [
    { label: t("nav.planning_shifts"), to: "/planning/shifts", badge: algorithmBadgeCount, badgeColor: algorithmBadgeColor, testId: "nav-shifts-management" },
    { label: t("nav.planning_config"), to: "/planning/config", testId: "nav-duty-config" },
    { label: t("nav.score_adjustments"), to: "/planning/score-adjustments", testId: "nav-score-adjustments" },
    { label: "ייבוא מ-Excel", to: "/import", testId: "nav-import" },
    { label: t("nav.planning_export"), to: "/planning/export", testId: "nav-export" },
    { label: "פוטנציאל", to: "/planning/potential", testId: "nav-potential" },
    ...(mitvachimEnabled
      ? [{ label: "מטווחים", to: "/ranges", badge: ineligibleCount, badgeColor: "red" as BadgeColor, testId: "nav-ranges" }]
      : []),
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
          className={`absolute top-1 right-1/4 md:top-2 md:left-3 ${BADGE_COLOR_CLASSES[tab.badgeColor ?? "red"]} text-[10px] rounded-full px-1.5 leading-5`}
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
