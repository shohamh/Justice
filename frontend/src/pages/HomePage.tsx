import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useInfiniteQuery, useQuery, useQueries } from "@tanstack/react-query";

import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import AlertBanners from "../components/dashboard/AlertBanners";
import UnitCalendar from "../components/UnitCalendar";
import DutyDetailModal from "../components/dashboard/DutyDetailModal";
import UpcomingDutiesWidget from "../components/dashboard/UpcomingDutiesWidget";
import UpcomingRangesWidget from "../components/dashboard/UpcomingRangesWidget";
import RangeDetailModal from "../components/ranges/RangeDetailModal";
import SwapStatusWidget from "../components/dashboard/SwapStatusWidget";
import PendingApprovalsWidget from "../components/dashboard/PendingApprovalsWidget";
import CommandDashboardSection from "../components/dashboard/CommandDashboardSection";
import IneligibleSoldiersPanel from "../components/dashboard/IneligibleSoldiersPanel";
import DutyHistoryWidget from "../components/dashboard/DutyHistoryWidget";
import DutyTypeBreakdownChart from "../components/dashboard/DutyTypeBreakdownChart";
import ActiveDeputyBanner from "../components/ActiveDeputyBanner";
import UpcomingSnapshot from "../components/UpcomingSnapshot";
import AlertsPanel from "../components/AlertsPanel";
import DutyPotentialPanel from "../components/DutyPotentialPanel";
import { dateToLocalIso, formatDateTimeIsrael, todayIso } from "../utils/formatDate";

import { useAuth } from "../auth/AuthContext";
import { getTransparencyAuthorizationScope } from "../api/auth";
import { isCommandScopeAvailable } from "../auth/dashboardRoles";
import { usePublicSettings } from "../hooks/usePublicSettings";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { listDutyTypes, listLocations } from "../api/dutyConfig";
import { listMySwaps, listPendingSwaps } from "../api/swaps";
import { listPendingEnrollments } from "../api/enrollment";
import { SettingsMap, getSystemSettings } from "../api/systemSettings";
import { getBreakdown, getBurdenShare, getBurdenShareBreakdown } from "../api/scoring";
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";
import { getRangePage } from "../api/ranges";
import { getIneligibleSoldierCount } from "../api/ineligibleSoldiers";
import { listPendingTransferRequests } from "../api/hierarchyTransfers";
import { lastDutyDay } from "../utils/formatDate";
import { fetchMyCommandScope } from "../api/hierarchy";
import {
  getAlerts as getCommandAlerts,
  getPotential as getCommandPotential,
  getUpcoming as getCommandUpcoming,
} from "../api/commanderDashboard";
import { getPotentialSummary as getNodePotentialSummary, type PotentialSummary } from "../api/potential";
import { useLevelTypes } from "../hooks/useLevelTypes";

// Hebrew-style "X, Y and Z" join: comma-separates all but the last item,
// then attaches the last with "ו" (no comma) — e.g. "המדור, הפלוגה והמרכז".
function joinHebrewList(items: string[]): string {
  if (items.length === 0) return "";
  if (items.length === 1) return items[0];
  return `${items.slice(0, -1).join(", ")} ו${items[items.length - 1]}`;
}

function offsetDate(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return dateToLocalIso(d);
}

// end_date is exclusive (the first day NOT touched), so no +1 here.
function dayCount(d: { start_date: string; end_date: string }): number {
  const [sy, sm, sd] = d.start_date.split("-").map(Number);
  const [ey, em, ed] = d.end_date.split("-").map(Number);
  return (Date.UTC(ey, em - 1, ed) - Date.UTC(sy, sm - 1, sd)) / 86400000;
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 text-center">
      <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">{label}</div>
      <div className="text-2xl font-bold text-indigo-700 dark:text-indigo-300">{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  );
}

function QueryState({
  label,
  isPending,
  isError,
  onRetry,
  children,
}: {
  label: string;
  isPending: boolean;
  isError: boolean;
  onRetry: () => unknown;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  if (isPending) {
    return (
      <p role="status" className="text-sm text-gray-500 dark:text-gray-400">
        {t("home.section_loading", { section: label, defaultValue: `Loading ${label}…` })}
      </p>
    );
  }
  if (isError) {
    return (
      <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        {t("home.section_error", { section: label, defaultValue: `Could not load ${label}.` })}{" "}
        <button type="button" className="underline" onClick={() => void onRetry()}>
          {t("common.retry", { defaultValue: "Try again" })}
        </button>
      </p>
    );
  }
  return <>{children}</>;
}

export default function HomePage() {
  const { t } = useTranslation();
  const { user, authScopeReady } = useAuth();
  const navigate = useNavigate();
  const publicSettings = usePublicSettings();

  const [selectedDuty, setSelectedDuty] = useState<EffectiveDuty | null>(null);
  const [openRangeId, setOpenRangeId] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [primaryReadyScope, setPrimaryReadyScope] = useState<string | null>(null);
  const [ineligiblePanelOpen, setIneligiblePanelOpen] = useState(false);

  const commandScopeAvailable = isCommandScopeAvailable(user);
  const authorizationScope = authScopeReady ? getTransparencyAuthorizationScope(user) : null;
  const ineligibleSoldierCountQuery = useQuery({
    queryKey: [...queryKeys.ineligibleSoldierCount(), "commander", authorizationScope],
    queryFn: () => getIneligibleSoldierCount("commander"),
    enabled: commandScopeAvailable && primaryReadyScope === authorizationScope && authorizationScope !== null,
    retry: false,
  });

  const commandScopeQuery = useQuery({
    queryKey: queryKeys.myCommandScope(user?.id ?? null, authorizationScope),
    queryFn: fetchMyCommandScope,
    enabled: commandScopeAvailable && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });
  const commandNodesOwnedByUser = useMemo(
    () => commandScopeQuery.data?.commanded_nodes ?? [],
    [commandScopeQuery.data],
  );
  const assignedNodeFallbackActive =
    commandNodesOwnedByUser.length === 0 &&
    commandScopeAvailable &&
    !!user?.hierarchy_node_id &&
    (user.role === "admin" || user.role === "duty_manager" || user.is_duty_manager);
  const assignedNodeFallback =
    assignedNodeFallbackActive &&
    commandScopeQuery.data?.assigned_node?.id === user?.hierarchy_node_id
      ? commandScopeQuery.data.assigned_node
      : null;
  const commandCalendarNodeIds = useMemo(() => {
    if (commandNodesOwnedByUser.length > 0) {
      return commandNodesOwnedByUser.map((node) => node.id);
    }
    if (assignedNodeFallbackActive && user?.hierarchy_node_id) {
      return [user.hierarchy_node_id];
    }
    return [];
  }, [commandNodesOwnedByUser, assignedNodeFallbackActive, user]);

  const { levelTypes } = useLevelTypes();
  const commandScopeLabel = useMemo(() => {
    const scopeNodes =
      commandNodesOwnedByUser.length > 0
        ? commandNodesOwnedByUser
        : assignedNodeFallback
          ? [assignedNodeFallback]
          : [];
    if (scopeNodes.length === 0) return undefined;
    const labelByKey = new Map(levelTypes.map((lt) => [lt.key, lt.label]));
    const uniqueLabels = Array.from(
      new Set(scopeNodes.map((node) => labelByKey.get(node.level) ?? node.level)),
    );
    return `${joinHebrewList(uniqueLabels.map((label) => `ה${label}`))} שבאחריותך`;
  }, [commandNodesOwnedByUser, assignedNodeFallback, levelTypes]);

  const commandAlertsQuery = useQuery({
    queryKey: [...queryKeys.commandDashboardAlerts(), authorizationScope],
    queryFn: getCommandAlerts,
    enabled: commandScopeAvailable && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });
  const commandAlerts = commandAlertsQuery.data ?? null;

  const commandUpcomingQuery = useQuery({
    queryKey: [...queryKeys.commandDashboardUpcoming(), authorizationScope],
    queryFn: getCommandUpcoming,
    enabled: commandScopeAvailable && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });
  const commandUpcoming = commandUpcomingQuery.data ?? null;

  const commandPotentialQuery = useQuery({
    queryKey: [...queryKeys.commandDashboardPotential(), authorizationScope],
    queryFn: getCommandPotential,
    enabled: commandScopeAvailable && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });
  const commandPotential = commandPotentialQuery.data ?? null;

  const ownPotentialQueries = useQueries({
    queries: commandNodesOwnedByUser.map((node) => ({
      queryKey: [...queryKeys.commandDashboardOwnPotential(node.id), "summary", authorizationScope],
      queryFn: () => getNodePotentialSummary(node.id),
      enabled: commandScopeAvailable && primaryReadyScope === authorizationScope && authorizationScope !== null,
    })),
  });

  const ownPotential = useMemo(() => {
    const byId: Record<string, PotentialSummary> = {};
    commandNodesOwnedByUser.forEach((node, index) => {
      const result = ownPotentialQueries[index];
      if (result?.data) {
        byId[node.id] = result.data;
      } else if (result?.isError) {
        console.error(`Failed to fetch potential for node ${node.id}:`, result.error);
      }
    });
    return byId;
  }, [commandNodesOwnedByUser, ownPotentialQueries]);

  // These queries fetch required-object payloads (see api/scoring.ts) — a
  // malformed shape throws instead of silently rendering wrong totals, so
  // surface that as a single banner rather than letting the page's ?? []/??
  // null fallbacks mask the failure.
  const dutyWindow = { date_from: offsetDate(-365), date_to: offsetDate(60) };
  const dutiesQuery = useQuery({
    queryKey: user
      ? [...queryKeys.effectiveDuties(user.id, dutyWindow), authorizationScope]
      : ["effectiveDuties", "anonymous"],
    queryFn: () => listEffectiveDuties(user!.id, { ...dutyWindow, include_drafts: true }),
    enabled: !!user,
  });
  const duties = useMemo(() => dutiesQuery.data ?? [], [dutiesQuery.data]);

  const typesQuery = useQuery({ queryKey: queryKeys.dutyTypes(), queryFn: listDutyTypes });
  const typeNames = Object.fromEntries(
    (Array.isArray(typesQuery.data) ? typesQuery.data : []).map((t) => [t.id, t.name]),
  );

  const locsQuery = useQuery({ queryKey: queryKeys.dutyLocations(), queryFn: listLocations });
  const locationNames = Object.fromEntries(
    (Array.isArray(locsQuery.data) ? locsQuery.data : []).map((l) => [l.id, l.name]),
  );

  const mySwapsQuery = useQuery({
    queryKey: [...queryKeys.mySwaps(), authorizationScope],
    queryFn: listMySwaps,
    enabled: primaryReadyScope === authorizationScope && authorizationScope !== null,
  });
  const mySwaps = mySwapsQuery.data ?? [];

  const settingsQuery = useQuery({ queryKey: queryKeys.systemSettings(), queryFn: getSystemSettings });
  const settings = settingsQuery.data ?? ({} as SettingsMap);

  const rangeToday = todayIso();
  const rangesQuery = useInfiniteQuery({
    queryKey: [...queryKeys.ranges(), "home-upcoming", user?.hierarchy_node_id ?? null, authorizationScope, rangeToday],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => getRangePage({
      nodeId: user!.hierarchy_node_id as string,
      dateFrom: rangeToday,
      status: "planned",
      assignedToMe: true,
    }, pageParam),
    getNextPageParam: lastPage => lastPage.next_cursor ?? undefined,
    enabled:
      primaryReadyScope === authorizationScope &&
      authorizationScope !== null &&
      !!user?.hierarchy_node_id &&
      publicSettings?.["mitvachim.enabled"] === true,
  });
  const ranges = rangesQuery.data?.pages.flatMap(page => page.items) ?? [];

  const canViewScoring = user?.can_view_transparency !== false;

  const breakdownQuery = useQuery({
    queryKey: user ? [...queryKeys.breakdown(user.id), authorizationScope] : ["breakdown", "anonymous"],
    queryFn: () => getBreakdown(user!.id),
    enabled: !!user && canViewScoring && historyOpen && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });
  const breakdown = breakdownQuery.data ?? null;

  const burdenShareQuery = useQuery({
    queryKey: user ? [...queryKeys.burdenShare(user.id), authorizationScope] : ["burdenShare", "anonymous"],
    queryFn: () => getBurdenShare(user!.id),
    enabled: !!user && canViewScoring && historyOpen && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });

  const burdenShareBreakdownQuery = useQuery({
    queryKey: user ? [...queryKeys.burdenShareBreakdown(user.id), authorizationScope] : ["burdenShareBreakdown", "anonymous"],
    queryFn: () => getBurdenShareBreakdown(user!.id),
    enabled: !!user && canViewScoring && historyOpen && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });

  const historyLoading = canViewScoring && (breakdownQuery.isPending || burdenShareQuery.isPending || burdenShareBreakdownQuery.isPending);
  const historyError = canViewScoring && (breakdownQuery.isError || burdenShareQuery.isError || burdenShareBreakdownQuery.isError);
  const retryHistory = () => Promise.all([
    breakdownQuery.refetch(),
    burdenShareQuery.refetch(),
    burdenShareBreakdownQuery.refetch(),
  ]);

  const primaryDataPending = dutiesQuery.isPending || typesQuery.isPending || locsQuery.isPending || settingsQuery.isPending;
  useEffect(() => {
    setPrimaryReadyScope(
      authorizationScope !== null && !primaryDataPending ? authorizationScope : null,
    );
  }, [authorizationScope, primaryDataPending]);
  const primaryDataReady =
    authorizationScope !== null && primaryReadyScope === authorizationScope;

  const enrollQuery = useQuery({
    queryKey: [...queryKeys.pendingEnrollments(), authorizationScope],
    queryFn: listPendingEnrollments,
    enabled: commandScopeAvailable && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });
  const pendingEnrollments = enrollQuery.data ?? [];

  const pendingSwapsQuery = useQuery({
    queryKey: [...queryKeys.pendingSwaps(), authorizationScope],
    queryFn: listPendingSwaps,
    enabled: commandScopeAvailable && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });
  const pendingSwaps = pendingSwapsQuery.data ?? [];

  const pendingConstraintsQuery = useQuery({
    queryKey: [...queryKeys.pendingConstraintsCount(), authorizationScope],
    queryFn: getPendingCount,
    enabled: commandScopeAvailable && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });
  const pendingConstraints = pendingConstraintsQuery.data ?? 0;

  const pendingExemptionsQuery = useQuery({
    queryKey: [...queryKeys.pendingExemptionsCount(), authorizationScope],
    queryFn: getPendingExemptionCount,
    enabled: commandScopeAvailable && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });
  const pendingExemptions = pendingExemptionsQuery.data ?? 0;

  const pendingFieldUpdatesQuery = useQuery({
    queryKey: [...queryKeys.pendingFieldUpdatesCount(), authorizationScope],
    queryFn: getPendingFieldUpdateCount,
    enabled: commandScopeAvailable && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });
  const pendingFieldUpdates = pendingFieldUpdatesQuery.data ?? 0;

  const pendingTransfersQuery = useQuery({
    queryKey: [...queryKeys.pendingHierarchyTransfers(), authorizationScope],
    queryFn: listPendingTransferRequests,
    enabled: commandScopeAvailable && primaryReadyScope === authorizationScope && authorizationScope !== null,
  });
  const pendingTransfers = pendingTransfersQuery.data ?? [];

  const approvalQueries = [
    enrollQuery,
    pendingSwapsQuery,
    pendingConstraintsQuery,
    pendingExemptionsQuery,
    pendingFieldUpdatesQuery,
    pendingTransfersQuery,
  ];
  const approvalsLoading = approvalQueries.some((query) => query.isPending);
  const approvalsError = approvalQueries.some((query) => query.isError);
  const retryApprovals = () => Promise.all(approvalQueries.map((query) => query.refetch()));

  const commandPanels: { id: string; title: ReactNode; content: ReactNode }[] = [
    {
      id: "ineligible-soldiers",
      title: (
        <span className="flex items-center justify-between gap-3">
          <span>חיילים ללא מטווחים בתוקף</span>
          <span
            data-testid="ineligible-range-badge"
            aria-label={`חיילים ללא מטווחים בתוקף: ${ineligibleSoldierCountQuery.data?.count ?? 0}`}
            className={`rounded-full px-2 py-0.5 text-sm font-semibold text-white ${
              (ineligibleSoldierCountQuery.data?.count ?? 0) > 0 ? "bg-red-600" : "bg-green-600"
            }`}
          >
            {ineligibleSoldierCountQuery.data?.count ?? 0}
          </span>
        </span>
      ),
      content: (
        <>
          {ineligibleSoldierCountQuery.isError && (
            <QueryState label="ineligible soldier count" isPending={false} isError onRetry={() => ineligibleSoldierCountQuery.refetch()}>
              {null}
            </QueryState>
          )}
          <IneligibleSoldiersPanel
            scope="command"
            isOpen={ineligiblePanelOpen}
            authorizationScope={authorizationScope}
          />
        </>
      ),
    },
    {
      id: "alerts",
      title: t("command_dashboard.alerts"),
      content: (
        <QueryState label={t("command_dashboard.alerts")} isPending={commandAlertsQuery.isPending} isError={commandAlertsQuery.isError} onRetry={() => commandAlertsQuery.refetch()}>
          <AlertsPanel data={commandAlerts} scope="command" />
        </QueryState>
      ),
    },
    {
      id: "approvals",
      title: t("command_dashboard.approvals"),
      content: (
        <QueryState label={t("command_dashboard.approvals")} isPending={approvalsLoading} isError={approvalsError} onRetry={retryApprovals}>
          <PendingApprovalsWidget
            pendingEnrollments={pendingEnrollments}
            pendingSwaps={pendingSwaps}
            pendingConstraints={pendingConstraints}
            pendingExemptions={pendingExemptions}
            pendingFieldUpdates={pendingFieldUpdates}
            pendingTransfers={pendingTransfers}
            scope="command"
          />
        </QueryState>
      ),
    },
    {
      id: "upcoming",
      title: t("command_dashboard.upcoming"),
      content: <UpcomingSnapshot data={commandUpcoming} scope="command" scopeLabel="תורנויות קרובות של חיילים שלך" />,
    },
    {
      id: "calendar",
      title: t("command_dashboard.calendar"),
      content: (
        <QueryState label={t("command_dashboard.calendar")} isPending={commandScopeQuery.isPending} isError={commandScopeQuery.isError} onRetry={() => commandScopeQuery.refetch()}>
          {commandCalendarNodeIds.length > 0 ? (
            <UnitCalendar nodeIds={commandCalendarNodeIds} scope="command" highlightSoldierId={user?.id} />
          ) : null}
        </QueryState>
      ),
    },
    {
      id: "potential",
      title: t("command_dashboard.potential"),
      content: (
        <QueryState label={t("command_dashboard.potential")} isPending={commandPotentialQuery.isPending} isError={commandPotentialQuery.isError} onRetry={() => commandPotentialQuery.refetch()}>
          <DutyPotentialPanel data={commandPotential} scope="command" />
        </QueryState>
      ),
    },
    {
      id: "own_potential",
      title: t("command_dashboard.own_potential"),
      content: commandNodesOwnedByUser.length === 0 ? (
        <p className="text-gray-500">{t("command_dashboard.no_own_potential")}</p>
      ) : (
        <table className="w-full border-collapse" data-testid="own-potential-table">
          <thead>
            <tr>
              <th className="border p-2">{t("command_dashboard.node")}</th>
              <th className="border p-2">{t("command_dashboard.eligible")}</th>
              <th className="border p-2">{t("command_dashboard.modifiers")}</th>
              <th className="border p-2">{t("command_dashboard.final_potential")}</th>
            </tr>
          </thead>
          <tbody>
            {commandNodesOwnedByUser.map((node) => {
              const result = ownPotential[node.id];
              return (
                <tr key={node.id}>
                  <td className="border p-2">{node.name}</td>
                  <td className="border p-2">{result?.raw_eligible_count ?? "-"}</td>
                  <td className="border p-2">{result?.modifier_total ?? "-"}</td>
                  <td className="border p-2">{result?.final_potential ?? "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ),
    },
  ];

  const commandPanelsWithStatus = commandPanels.map((panel) => {
    if (panel.id === "upcoming") {
      return {
        ...panel,
        content: (
          <QueryState label={t("command_dashboard.upcoming")} isPending={commandUpcomingQuery.isPending} isError={commandUpcomingQuery.isError} onRetry={() => commandUpcomingQuery.refetch()}>
            {panel.content}
          </QueryState>
        ),
      };
    }
    if (panel.id === "own_potential") {
      return {
        ...panel,
        content: (
          <QueryState
            label={t("command_dashboard.own_potential")}
            isPending={
              commandScopeQuery.isPending ||
              commandScopeQuery.isFetching ||
              (!commandScopeQuery.isSuccess && !commandScopeQuery.isError) ||
              ownPotentialQueries.some((query) => query.isPending || query.isFetching)
            }
            isError={
              commandScopeQuery.isError || ownPotentialQueries.some((query) => query.isError)
            }
            onRetry={() =>
              Promise.all([
                commandScopeQuery.refetch(),
                ...ownPotentialQueries.map((query) => query.refetch()),
              ])
            }
          >
            {panel.content}
          </QueryState>
        ),
      };
    }
    return panel;
  });

  function handleOpenDuty(duty: EffectiveDuty) {
    setSelectedDuty(duty);
  }

  function handleRequestSwap(duty: EffectiveDuty) {
    setSelectedDuty(null);
    navigate(`/swaps?new=${duty.assignment_id}`);
  }

  const personalScore = useMemo(() => {
    if (!breakdown) return null;
    const dutyScore = breakdown.per_type.reduce((sum, row) => sum + Number(row.score), 0);
    const adjustments = breakdown.adjustments.reduce((sum, row) => sum + Number(row.delta), 0);
    return dutyScore + adjustments;
  }, [breakdown]);

  const today = todayIso();

  const pastDuties = useMemo(
    // end_date is exclusive, so a duty whose last day is today has end_date === today+1;
    // "over" means end_date is today or earlier.
    () => duties.filter((d) => d.end_date <= today),
    [duties, today],
  );
  const pastCount = pastDuties.length;
  const pastDays = useMemo(
    () => pastDuties.reduce((s, d) => s + dayCount(d), 0),
    [pastDuties],
  );
  // Unit-wide averages intentionally stay on the Transparency page. Home must not
  // materialize the full caller-visible projection just to fill these captions.
  const unitAvgDays = "—";
  const unitAvgShifts = "—";

  const currentMonthStart = useMemo(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
  }, []);

  const currentMonthEnd = useMemo(() => {
    const d = new Date();
    const last = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    return dateToLocalIso(last);
  }, []);

  const monthReserveDays = useMemo(() => {
    return duties
      .filter(
        (d) =>
          d.is_reserve &&
          d.start_date <= currentMonthEnd &&
          d.end_date > currentMonthStart
      )
      .reduce((sum, d) => {
        const dutyLastDay = lastDutyDay(d.end_date);
        const start = d.start_date < currentMonthStart ? currentMonthStart : d.start_date;
        const end = dutyLastDay > currentMonthEnd ? currentMonthEnd : dutyLastDay;
        const [sy, sm, sd] = start.split("-").map(Number);
        const [ey, em, ed] = end.split("-").map(Number);
        const days = (Date.UTC(ey, em - 1, ed) - Date.UTC(sy, sm - 1, sd)) / 86400000 + 1;
        return sum + Math.max(0, days);
      }, 0);
  }, [duties, currentMonthStart, currentMonthEnd]);

  const yearReserveDays = useMemo(() => {
    const yearStart = `${new Date().getFullYear()}-01-01`;
    const yearEnd = `${new Date().getFullYear()}-12-31`;
    return duties
      .filter(
        (d) =>
          d.is_reserve &&
          d.start_date <= yearEnd &&
          d.end_date > yearStart
      )
      .reduce((sum, d) => {
        const dutyLastDay = lastDutyDay(d.end_date);
        const start = d.start_date < yearStart ? yearStart : d.start_date;
        const end = dutyLastDay > yearEnd ? yearEnd : dutyLastDay;
        const [sy, sm, sd] = start.split("-").map(Number);
        const [ey, em, ed] = end.split("-").map(Number);
        const days = (Date.UTC(ey, em - 1, ed) - Date.UTC(sy, sm - 1, sd)) / 86400000 + 1;
        return sum + Math.max(0, days);
      }, 0);
  }, [duties]);

  return (
    <Layout>
      <div className="space-y-4 max-w-3xl mx-auto" dir="rtl">
        <h2 className="text-xl font-semibold">{t("home.welcome", { name: user?.full_name ?? "" })}</h2>

        <QueryState
          label={t("home.current_duties", { defaultValue: "current duties" })}
          isPending={dutiesQuery.isPending}
          isError={dutiesQuery.isError}
          onRetry={() => dutiesQuery.refetch()}
        >
          {null}
        </QueryState>
        {typesQuery.isError && (
          <QueryState label={t("home.duty_types", { defaultValue: "duty types" })} isPending={false} isError onRetry={() => typesQuery.refetch()}>
            {null}
          </QueryState>
        )}
        {locsQuery.isError && (
          <QueryState label={t("home.locations", { defaultValue: "locations" })} isPending={false} isError onRetry={() => locsQuery.refetch()}>
            {null}
          </QueryState>
        )}
        {settingsQuery.isError && (
          <QueryState label={t("home.settings", { defaultValue: "settings" })} isPending={false} isError onRetry={() => settingsQuery.refetch()}>
            {null}
          </QueryState>
        )}

        <ActiveDeputyBanner grants={user?.active_deputy_grants ?? []} />

        {!settingsQuery.isPending && (
          <AlertBanners
            lastMitvahimDate={user?.last_mitvahim_date ?? null}
            lastAlalDate={user?.last_alal_date ?? null}
            settings={settings}
            duties={dutiesQuery.isError ? [] : duties}
          />
        )}

        {primaryDataReady && commandScopeAvailable && (
          <CommandDashboardSection
            scopeLabel={
              commandScopeLabel ??
              t("command_dashboard.management_section_scope", {
                defaultValue: "היחידה שבאחריותך",
              })
            }
          >
            <div className="space-y-3">
              {commandPanelsWithStatus.map((panel) => (
                <details
                  key={panel.id}
                  open={panel.id === "ineligible-soldiers" ? undefined : true}
                  onToggle={panel.id === "ineligible-soldiers"
                    ? (event) => setIneligiblePanelOpen(event.currentTarget.open)
                    : undefined}
                  className="bg-white dark:bg-gray-800 rounded-lg shadow p-4"
                  data-testid={`panel-${panel.id}`}
                >
                  <summary className="cursor-pointer font-medium text-lg mb-2 dark:text-gray-100">
                    {panel.title}
                  </summary>
                  {panel.content}
                </details>
              ))}
            </div>
          </CommandDashboardSection>
        )}

        {primaryDataReady && !commandScopeAvailable && user && (
          <UnitCalendar nodeId={user.hierarchy_node_id ?? undefined} soldierId={user.id} scope="personal" />
        )}

        <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-4" aria-labelledby="personal-data-heading" data-testid="personal-data-panel">
          <h2 id="personal-data-heading" className="text-xl font-semibold">הנתונים שלי</h2>

          <div hidden={dutiesQuery.isPending || dutiesQuery.isError}>
          <UpcomingDutiesWidget
            duties={duties}
            typeNames={typeNames}
            locationNames={locationNames}
            onOpenDuty={handleOpenDuty}
            title="תורנויות קרובות שלי"
          />

        </div>
        {primaryDataReady && publicSettings?.["mitvachim.enabled"] === true && (
          <QueryState
            label={t("home.upcoming_ranges", { defaultValue: "upcoming ranges" })}
            isPending={rangesQuery.isPending}
            isError={rangesQuery.isError && !rangesQuery.isFetchNextPageError}
            onRetry={() => rangesQuery.refetch()}
          >
            {null}
          </QueryState>
        )}
        {primaryDataReady && !rangesQuery.isPending && (!rangesQuery.isError || rangesQuery.isFetchNextPageError) && publicSettings?.["mitvachim.enabled"] === true && (
          <UpcomingRangesWidget
            ranges={ranges}
            hasMore={rangesQuery.hasNextPage}
            loadingMore={rangesQuery.isFetchingNextPage}
            loadError={rangesQuery.isFetchNextPageError}
            onLoadMore={() => { if (!rangesQuery.isFetchingNextPage) void rangesQuery.fetchNextPage(); }}
            onOpenRange={(range) => setOpenRangeId(range.id)}
            title="מטווחים קרובים שלי"
          />
        )}

        {openRangeId && (
          <RangeDetailModal rangeId={openRangeId} onClose={() => setOpenRangeId(null)} />
        )}

        {primaryDataReady && (
          <QueryState label={t("home.swap_status", { defaultValue: "swap status" })} isPending={mySwapsQuery.isPending} isError={mySwapsQuery.isError} onRetry={() => mySwapsQuery.refetch()}>
            <SwapStatusWidget swaps={mySwaps} />
          </QueryState>
        )}
        <details
          hidden={!primaryDataReady}
          onToggle={(event) => setHistoryOpen(event.currentTarget.open)}
          className="rounded-lg border border-gray-200 dark:border-gray-700 p-3"
        >
          <summary className="cursor-pointer font-medium">
            {t("home.history_details", { defaultValue: "History and score details" })}
          </summary>
          {historyOpen && (
            <div className="mt-3 space-y-3">
              {canViewScoring && (
                <QueryState
                  label={t("home.history_details", { defaultValue: "History and score details" })}
                  isPending={historyLoading}
                  isError={historyError}
                  onRetry={retryHistory}
                >
                  {null}
                </QueryState>
              )}
              <DutyHistoryWidget
                duties={duties}
                typeNames={typeNames}
                locationNames={locationNames}
                personalScore={personalScore}
                canViewTransparency={canViewScoring}
                burdenShare={burdenShareQuery.data}
                burdenShareBreakdown={burdenShareBreakdownQuery.data}
                soldierName={user?.full_name}
              />
            </div>
          )}
        </details>

        {/* Reserve days this month */}
        <div hidden={dutiesQuery.isPending || dutiesQuery.isError} className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 flex items-center justify-between">
          <div>
            <p className="text-xs text-gray-500 dark:text-gray-400">ימי רזרבה החודש</p>
            <p className="text-2xl font-bold text-amber-600 dark:text-amber-400">{monthReserveDays}</p>
            <p className="text-xs text-gray-400 mt-0.5">{"סה\"כ"} השנה: {yearReserveDays}</p>
          </div>
        </div>

        {/* היומן שלי — stat cards */}
        <div hidden={dutiesQuery.isPending || dutiesQuery.isError} className="grid grid-cols-2 gap-3">
          <StatCard
            label="תורנויות שביצעתי"
            value={pastCount}
            sub={`ממוצע יחידה: ${unitAvgShifts}`}
          />
          <StatCard
            label="ימי תורנות"
            value={pastDays}
            sub={`ממוצע יחידה: ${unitAvgDays}`}
          />
        </div>

        {/* Breakdown by duty type */}
        {historyOpen && canViewScoring && (
          <QueryState
            label={t("home.score_breakdown", { defaultValue: "score breakdown" })}
            isPending={breakdownQuery.isPending}
            isError={breakdownQuery.isError}
            onRetry={() => breakdownQuery.refetch()}
          >
            <DutyTypeBreakdownChart perType={breakdown?.per_type ?? []} mirrored />
          </QueryState>
        )}

        {/* Manual score adjustments */}
        {historyOpen && breakdown && breakdown.adjustments.length > 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
            <h3 className="font-medium text-sm">התאמות ניקוד ידניות</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 dark:text-gray-400 border-b dark:border-gray-600">
                  <th className="text-right pb-2 font-medium">תאריך</th>
                  <th className="text-right pb-2 font-medium">שינוי</th>
                  <th className="text-right pb-2 font-medium">סיבה</th>
                </tr>
              </thead>
              <tbody>
                {breakdown.adjustments.map((a) => (
                  <tr key={a.id} className="border-b dark:border-gray-600 last:border-0">
                    <td className="py-2">{formatDateTimeIsrael(a.created_at)}</td>
                    <td
                      className={`py-2 font-medium ${
                        Number(a.delta) >= 0 ? "text-green-600" : "text-red-600"
                      }`}
                    >
                      {Number(a.delta) >= 0 ? "+" : ""}
                      {Number(a.delta).toFixed(3)}
                    </td>
                    <td className="py-2">{a.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        </section>
      </div>

      <DutyDetailModal
        duty={selectedDuty}
        typeNames={typeNames}
        locationNames={locationNames}
        onClose={() => setSelectedDuty(null)}
        onRequestSwap={handleRequestSwap}
      />
    </Layout>
  );
}
