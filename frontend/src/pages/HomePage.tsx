import { useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueries } from "@tanstack/react-query";

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
import { formatDateTimeIsrael } from "../utils/formatDate";

import { useAuth } from "../auth/AuthContext";
import { isCommandScopeAvailable } from "../auth/dashboardRoles";
import { usePublicSettings } from "../hooks/usePublicSettings";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { listDutyTypes, listLocations } from "../api/dutyConfig";
import { listMySwaps, listPendingSwaps } from "../api/swaps";
import { listPendingEnrollments } from "../api/enrollment";
import { SettingsMap, getSystemSettings } from "../api/systemSettings";
import { getTransparency, getBreakdown, getBurdenShare, getBurdenShareBreakdown } from "../api/scoring";
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";
import { getRanges } from "../api/ranges";
import { getIneligibleSoldiers } from "../api/ineligibleSoldiers";
import { listPendingTransferRequests } from "../api/hierarchyTransfers";
import { lastDutyDay } from "../utils/formatDate";
import { fetchFullTree } from "../api/hierarchy";
import {
  getAlerts as getCommandAlerts,
  getPotential as getCommandPotential,
  getUpcoming as getCommandUpcoming,
} from "../api/commanderDashboard";
import { getPotential as getNodePotential, type PotentialResult } from "../api/potential";
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
  return d.toISOString().split("T")[0];
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

export default function HomePage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const publicSettings = usePublicSettings();

  const [selectedDuty, setSelectedDuty] = useState<EffectiveDuty | null>(null);
  const [openRangeId, setOpenRangeId] = useState<string | null>(null);

  const commandScopeAvailable = isCommandScopeAvailable(user);
  const ineligibleSoldiersQuery = useQuery({
    queryKey: queryKeys.ineligibleSoldiers("commander"),
    queryFn: () => getIneligibleSoldiers("commander"),
    enabled: commandScopeAvailable,
    retry: false,
  });

  const commandNodesQuery = useQuery({
    queryKey: queryKeys.hierarchyTree(),
    queryFn: fetchFullTree,
    enabled: commandScopeAvailable,
  });
  const commandNodes = useMemo(() => commandNodesQuery.data ?? [], [commandNodesQuery.data]);
  const commandNodesOwnedByUser = useMemo(
    () => commandNodes.filter((node) => node.commander_id === user?.id),
    [commandNodes, user],
  );
  const commandCalendarNodeIds = useMemo(() => {
    if (commandNodesOwnedByUser.length > 0) {
      return commandNodesOwnedByUser.map((node) => node.id);
    }
    if (
      commandScopeAvailable &&
      user?.hierarchy_node_id &&
      (user.role === "admin" || user.role === "duty_manager" || user.is_duty_manager)
    ) {
      return [user.hierarchy_node_id];
    }
    return [];
  }, [commandNodesOwnedByUser, commandScopeAvailable, user]);

  const { levelTypes } = useLevelTypes();
  const commandScopeLabel = useMemo(() => {
    const scopeNodes = commandNodes.filter((node) => commandCalendarNodeIds.includes(node.id));
    if (scopeNodes.length === 0) return undefined;
    const labelByKey = new Map(levelTypes.map((lt) => [lt.key, lt.label]));
    const uniqueLabels = Array.from(
      new Set(scopeNodes.map((node) => labelByKey.get(node.level) ?? node.level)),
    );
    return `${joinHebrewList(uniqueLabels.map((label) => `ה${label}`))} שבאחריותך`;
  }, [commandNodes, commandCalendarNodeIds, levelTypes]);

  const commandAlertsQuery = useQuery({
    queryKey: queryKeys.commandDashboardAlerts(),
    queryFn: getCommandAlerts,
    enabled: commandScopeAvailable,
  });
  const commandAlerts = commandAlertsQuery.data ?? null;

  const commandUpcomingQuery = useQuery({
    queryKey: queryKeys.commandDashboardUpcoming(),
    queryFn: getCommandUpcoming,
    enabled: commandScopeAvailable,
  });
  const commandUpcoming = commandUpcomingQuery.data ?? null;

  const commandPotentialQuery = useQuery({
    queryKey: queryKeys.commandDashboardPotential(),
    queryFn: getCommandPotential,
    enabled: commandScopeAvailable,
  });
  const commandPotential = commandPotentialQuery.data ?? null;

  const ownPotentialQueries = useQueries({
    queries: commandNodesOwnedByUser.map((node) => ({
      queryKey: queryKeys.commandDashboardOwnPotential(node.id),
      queryFn: () => getNodePotential(node.id),
      enabled: commandScopeAvailable,
    })),
  });

  const ownPotential = useMemo(() => {
    const byId: Record<string, PotentialResult> = {};
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
  const dutiesQuery = useQuery({
    queryKey: user ? queryKeys.effectiveDuties(user.id, { date_from: offsetDate(-365), date_to: offsetDate(60) }) : ["effectiveDuties", "anonymous"],
    queryFn: () => listEffectiveDuties(user!.id, { date_from: offsetDate(-365), date_to: offsetDate(60), include_drafts: true }),
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

  const mySwapsQuery = useQuery({ queryKey: queryKeys.mySwaps(), queryFn: listMySwaps });
  const mySwaps = mySwapsQuery.data ?? [];

  const settingsQuery = useQuery({ queryKey: queryKeys.systemSettings(), queryFn: getSystemSettings });
  const settings = settingsQuery.data ?? ({} as SettingsMap);

  const rangesQuery = useQuery({
    queryKey: queryKeys.ranges(),
    queryFn: () => getRanges(user!.hierarchy_node_id as string),
    enabled: !!user?.hierarchy_node_id && publicSettings?.["mitvachim.enabled"] === true,
  });
  const ranges = rangesQuery.data ?? [];

  const transparencyQuery = useQuery({
    queryKey: queryKeys.transparency(),
    queryFn: getTransparency,
    select: (out) => out.rows,
  });
  const transparencyRows = useMemo(() => transparencyQuery.data ?? [], [transparencyQuery.data]);

  const breakdownQuery = useQuery({
    queryKey: user ? queryKeys.breakdown(user.id) : ["breakdown", "anonymous"],
    queryFn: () => getBreakdown(user!.id),
    enabled: !!user,
  });
  const breakdown = breakdownQuery.data ?? null;

  const burdenShareQuery = useQuery({
    queryKey: user ? queryKeys.burdenShare(user.id) : ["burdenShare", "anonymous"],
    queryFn: () => getBurdenShare(user!.id),
    enabled: !!user,
  });

  const burdenShareBreakdownQuery = useQuery({
    queryKey: user ? queryKeys.burdenShareBreakdown(user.id) : ["burdenShareBreakdown", "anonymous"],
    queryFn: () => getBurdenShareBreakdown(user!.id),
    enabled: !!user,
  });

  const hasScoreLoadError =
    transparencyQuery.isError ||
    breakdownQuery.isError ||
    burdenShareQuery.isError ||
    burdenShareBreakdownQuery.isError;

  const enrollQuery = useQuery({
    queryKey: queryKeys.pendingEnrollments(),
    queryFn: listPendingEnrollments,
    enabled: commandScopeAvailable,
  });
  const pendingEnrollments = enrollQuery.data ?? [];

  const pendingSwapsQuery = useQuery({
    queryKey: queryKeys.pendingSwaps(),
    queryFn: listPendingSwaps,
    enabled: commandScopeAvailable,
  });
  const pendingSwaps = pendingSwapsQuery.data ?? [];

  const pendingConstraintsQuery = useQuery({
    queryKey: queryKeys.pendingConstraintsCount(),
    queryFn: getPendingCount,
    enabled: commandScopeAvailable,
  });
  const pendingConstraints = pendingConstraintsQuery.data ?? 0;

  const pendingExemptionsQuery = useQuery({
    queryKey: queryKeys.pendingExemptionsCount(),
    queryFn: getPendingExemptionCount,
    enabled: commandScopeAvailable,
  });
  const pendingExemptions = pendingExemptionsQuery.data ?? 0;

  const pendingFieldUpdatesQuery = useQuery({
    queryKey: queryKeys.pendingFieldUpdatesCount(),
    queryFn: getPendingFieldUpdateCount,
    enabled: commandScopeAvailable,
  });
  const pendingFieldUpdates = pendingFieldUpdatesQuery.data ?? 0;

  const pendingTransfersQuery = useQuery({
    queryKey: queryKeys.pendingHierarchyTransfers(),
    queryFn: listPendingTransferRequests,
    enabled: commandScopeAvailable,
  });
  const pendingTransfers = pendingTransfersQuery.data ?? [];

  const commandPanels: { id: string; title: ReactNode; content: ReactNode }[] = [
    {
      id: "ineligible-soldiers",
      title: (
        <span className="flex items-center justify-between gap-3">
          <span>חיילים ללא מטווחים בתוקף</span>
          <span
            data-testid="ineligible-range-badge"
            aria-label={`חיילים ללא מטווחים בתוקף: ${ineligibleSoldiersQuery.data?.count ?? 0}`}
            className={`rounded-full px-2 py-0.5 text-sm font-semibold text-white ${
              (ineligibleSoldiersQuery.data?.count ?? 0) > 0 ? "bg-red-600" : "bg-green-600"
            }`}
          >
            {ineligibleSoldiersQuery.data?.count ?? 0}
          </span>
        </span>
      ),
      content: <IneligibleSoldiersPanel scope="command" />,
    },
    {
      id: "alerts",
      title: t("command_dashboard.alerts"),
      content: <AlertsPanel data={commandAlerts} scope="command" />,
    },
    {
      id: "approvals",
      title: t("command_dashboard.approvals"),
      content: (
        <PendingApprovalsWidget
          pendingEnrollments={pendingEnrollments}
          pendingSwaps={pendingSwaps}
          pendingConstraints={pendingConstraints}
          pendingExemptions={pendingExemptions}
          pendingFieldUpdates={pendingFieldUpdates}
          pendingTransfers={pendingTransfers}
          scope="command"
        />
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
      content: commandCalendarNodeIds.length > 0 ? (
        <UnitCalendar nodeIds={commandCalendarNodeIds} scope="command" highlightSoldierId={user?.id} />
      ) : null,
    },
    {
      id: "potential",
      title: t("command_dashboard.potential"),
      content: <DutyPotentialPanel data={commandPotential} scope="command" />,
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
                  <td className="border p-2">{result ? result.modifiers.reduce((sum, modifier) => sum + modifier.delta, 0) : "-"}</td>
                  <td className="border p-2">{result?.final_potential ?? "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ),
    },
  ];

  function handleOpenDuty(duty: EffectiveDuty) {
    setSelectedDuty(duty);
  }

  function handleRequestSwap(duty: EffectiveDuty) {
    setSelectedDuty(null);
    navigate(`/swaps?new=${duty.assignment_id}`);
  }

  const myRow = useMemo(
    () => transparencyRows.find((r) => r.soldier_id === user?.id) ?? null,
    [transparencyRows, user],
  );

  const today = new Date().toISOString().split("T")[0];

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

  const unitAvgDays = useMemo(() => {
    if (transparencyRows.length === 0) return 0;
    return Math.round(transparencyRows.reduce((s, r) => s + Number(r.active_days), 0) / transparencyRows.length);
  }, [transparencyRows]);

  const unitAvgShifts = useMemo(() => {
    if (transparencyRows.length === 0) return 0;
    return Math.round(transparencyRows.reduce((s, r) => s + Number(r.shift_count), 0) / transparencyRows.length);
  }, [transparencyRows]);

  const currentMonthStart = useMemo(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
  }, []);

  const currentMonthEnd = useMemo(() => {
    const d = new Date();
    const last = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    return last.toISOString().split("T")[0];
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

        {hasScoreLoadError && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {t("home.score_load_error")}
          </p>
        )}

        <ActiveDeputyBanner grants={user?.active_deputy_grants ?? []} />

        <AlertBanners
          lastMitvahimDate={user?.last_mitvahim_date ?? null}
          lastAlalDate={user?.last_alal_date ?? null}
          settings={settings}
        />

        {commandScopeAvailable && (
          <CommandDashboardSection
            scopeLabel={
              commandScopeLabel ??
              t("command_dashboard.management_section_scope", {
                defaultValue: "היחידה שבאחריותך",
              })
            }
          >
            <div className="space-y-3">
              {commandPanels.map((panel) => (
                <details
                  key={panel.id}
                  open={panel.id !== "ineligible-soldiers"}
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

        {!commandScopeAvailable && user && (
          <UnitCalendar nodeId={user.hierarchy_node_id ?? undefined} soldierId={user.id} scope="personal" />
        )}

        <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-4" aria-labelledby="personal-data-heading" data-testid="personal-data-panel">
          <h2 id="personal-data-heading" className="text-xl font-semibold">הנתונים שלי</h2>

          <UpcomingDutiesWidget
            duties={duties}
            typeNames={typeNames}
            locationNames={locationNames}
            onOpenDuty={handleOpenDuty}
            title="תורנויות קרובות שלי"
          />

        {publicSettings?.["mitvachim.enabled"] === true && (
          <UpcomingRangesWidget
            ranges={ranges}
            onOpenRange={(range) => setOpenRangeId(range.id)}
            title="מטווחים קרובים שלי"
          />
        )}

        {openRangeId && (
          <RangeDetailModal rangeId={openRangeId} onClose={() => setOpenRangeId(null)} />
        )}

        <SwapStatusWidget swaps={mySwaps} />
        <DutyHistoryWidget
          duties={duties}
          typeNames={typeNames}
          locationNames={locationNames}
          myRow={myRow}
          allRows={transparencyRows}
          canViewTransparency={user?.can_view_transparency !== false}
          burdenShare={burdenShareQuery.data}
          burdenShareBreakdown={burdenShareBreakdownQuery.data}
          soldierName={user?.full_name}
        />

        {/* Reserve days this month */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 flex items-center justify-between">
          <div>
            <p className="text-xs text-gray-500 dark:text-gray-400">ימי רזרבה החודש</p>
            <p className="text-2xl font-bold text-amber-600 dark:text-amber-400">{monthReserveDays}</p>
            <p className="text-xs text-gray-400 mt-0.5">{"סה\"כ"} השנה: {yearReserveDays}</p>
          </div>
        </div>

        {/* היומן שלי — stat cards */}
        <div className="grid grid-cols-2 gap-3">
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
        <DutyTypeBreakdownChart perType={breakdown?.per_type ?? []} mirrored />

        {/* Manual score adjustments */}
        {breakdown && breakdown.adjustments.length > 0 && (
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
