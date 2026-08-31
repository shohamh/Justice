import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueries } from "@tanstack/react-query";

import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import SummaryCards from "../components/SummaryCards";
import UpcomingSnapshot from "../components/UpcomingSnapshot";
import AlertsPanel from "../components/AlertsPanel";
import DutyPotentialPanel from "../components/DutyPotentialPanel";
import PendingApprovalsWidget from "../components/dashboard/PendingApprovalsWidget";
import IneligibleSoldiersPanel from "../components/dashboard/IneligibleSoldiersPanel";
import UnitCalendar from "../components/UnitCalendar";
import { useAuth } from "../auth/AuthContext";
import { fetchFullTree } from "../api/hierarchy";
import {
  getSummary, getPotential, getUpcoming,
  getAlerts,
} from "../api/commanderDashboard";
import { getPotential as getNodePotential, type PotentialResult } from "../api/potential";
import { listPendingEnrollments } from "../api/enrollment";
import { listPendingSwaps } from "../api/swaps";
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";
import { listPendingTransferRequests } from "../api/hierarchyTransfers";

export default function CommandDashboardPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const summaryQuery = useQuery({ queryKey: queryKeys.commandDashboardSummary(), queryFn: getSummary });
  const summaryData = summaryQuery.data ?? null;

  const nodesQuery = useQuery({ queryKey: queryKeys.hierarchyTree(), queryFn: fetchFullTree });
  const nodes = useMemo(() => nodesQuery.data ?? [], [nodesQuery.data]);

  // getSummary/getFairnessInternal are required-object endpoints (see
  // api/commanderDashboard.ts) — a malformed shape throws instead of
  // silently rendering wrong counters, so surface that explicitly.
  const hasSummaryLoadError = summaryQuery.isError;
  const potentialQuery = useQuery({ queryKey: queryKeys.commandDashboardPotential(), queryFn: getPotential });
  const potentialData = potentialQuery.data ?? null;

  const upcomingQuery = useQuery({ queryKey: queryKeys.commandDashboardUpcoming(), queryFn: getUpcoming });
  const upcomingData = upcomingQuery.data ?? null;

  const alertsQuery = useQuery({ queryKey: queryKeys.commandDashboardAlerts(), queryFn: getAlerts });
  const alertsData = alertsQuery.data ?? null;

  const pendingEnrollmentsQuery = useQuery({ queryKey: queryKeys.pendingEnrollments(), queryFn: listPendingEnrollments });
  const pendingEnrollments = pendingEnrollmentsQuery.data ?? [];

  const pendingSwapsQuery = useQuery({ queryKey: queryKeys.pendingSwaps(), queryFn: listPendingSwaps });
  const pendingSwaps = pendingSwapsQuery.data ?? [];

  const pendingConstraintsQuery = useQuery({ queryKey: queryKeys.pendingConstraintsCount(), queryFn: getPendingCount });
  const pendingConstraints = pendingConstraintsQuery.data ?? 0;

  const pendingExemptionsQuery = useQuery({ queryKey: queryKeys.pendingExemptionsCount(), queryFn: getPendingExemptionCount });
  const pendingExemptions = pendingExemptionsQuery.data ?? 0;

  const pendingFieldUpdatesQuery = useQuery({ queryKey: queryKeys.pendingFieldUpdatesCount(), queryFn: getPendingFieldUpdateCount });
  const pendingFieldUpdates = pendingFieldUpdatesQuery.data ?? 0;

  const pendingTransfersQuery = useQuery({ queryKey: queryKeys.pendingHierarchyTransfers(), queryFn: listPendingTransferRequests });
  const pendingTransfers = pendingTransfersQuery.data ?? [];

  // Passed down to children (HierarchyTree, EntriesExitsPanel) that trigger a
  // broad refresh after a mutation whose exact blast radius on this page's
  // ~14 independent widgets isn't worth tracking precisely — invalidate
  // everything the dashboard reads.
  // The nodes this commander directly commands — same scope-resolution used
  // elsewhere in the app (e.g. TeamHierarchyPage) to find "my" node(s).
  const myNodes = useMemo(
    () => nodes.filter((n) => n.commander_id === user?.id),
    [nodes, user],
  );

  const ownPotentialQueries = useQueries({
    queries: myNodes.map((n) => ({
      queryKey: queryKeys.commandDashboardOwnPotential(n.id),
      queryFn: () => getNodePotential(n.id),
    })),
  });

  const ownPotential = useMemo(() => {
    const byId: Record<string, PotentialResult> = {};
    myNodes.forEach((n, i) => {
      const result = ownPotentialQueries[i];
      if (result?.data) {
        byId[n.id] = result.data;
      } else if (result?.isError) {
        console.error(`Failed to fetch potential for node ${n.id}:`, result.error);
      }
    });
    return byId;
  }, [myNodes, ownPotentialQueries]);

  const panels: { id: string; title: string; content: React.ReactNode }[] = [
    {
      id: "ineligible-soldiers",
      title: t("range_qualification.dashboard.title"),
      content: <IneligibleSoldiersPanel />,
    },
    {
      id: "alerts",
      title: t("command_dashboard.alerts"),
      content: <AlertsPanel data={alertsData} />,
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
        />
      ),
    },
    {
      id: "upcoming",
      title: t("command_dashboard.upcoming"),
      content: <UpcomingSnapshot data={upcomingData} />,
    },
    {
      id: "calendar",
      title: t("command_dashboard.calendar"),
      content: myNodes.length > 0 ? <UnitCalendar nodeIds={myNodes.map((n) => n.id)} /> : null,
    },
    {
      id: "potential",
      title: t("command_dashboard.potential"),
      content: <DutyPotentialPanel data={potentialData} />,
    },
    {
      id: "own_potential",
      title: t("command_dashboard.own_potential"),
      content: myNodes.length === 0 ? (
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
            {myNodes.map((n) => {
              const r = ownPotential[n.id];
              return (
                <tr key={n.id}>
                  <td className="border p-2">{n.name}</td>
                  <td className="border p-2">{r?.raw_eligible_count ?? "-"}</td>
                  <td className="border p-2">{r ? r.modifiers.reduce((s, m) => s + m.delta, 0) : "-"}</td>
                  <td className="border p-2">{r?.final_potential ?? "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ),
    },
  ];

  return (
    <Layout>
      <section className="space-y-4" data-testid="command-dashboard-page">
        <h2 className="text-xl font-semibold">{t("command_dashboard.title")}</h2>
        {hasSummaryLoadError && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {t("command_dashboard.summary_load_error")}
          </p>
        )}
        <SummaryCards data={summaryData} />
        {panels.map((panel) => (
          <details key={panel.id} open className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" data-testid={`panel-${panel.id}`}>
            <summary className="cursor-pointer font-medium text-lg mb-2 dark:text-gray-100">{panel.title}</summary>
            {panel.content}
          </details>
        ))}
      </section>
    </Layout>
  );
}
