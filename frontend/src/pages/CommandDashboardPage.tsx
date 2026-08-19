import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueries, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import SummaryCards from "../components/SummaryCards";
import UpcomingSnapshot from "../components/UpcomingSnapshot";
import AlertsPanel from "../components/AlertsPanel";
import { InternalFairness, ExternalFairness } from "../components/FairnessChart";
import DutyPotentialPanel from "../components/DutyPotentialPanel";
import PendingApprovalsWidget from "../components/dashboard/PendingApprovalsWidget";
import IneligibleSoldiersPanel from "../components/dashboard/IneligibleSoldiersPanel";
import EntriesExitsPanel from "../components/EntriesExitsPanel";
import UnitCalendar from "../components/UnitCalendar";
import { useAuth } from "../auth/AuthContext";
import { fetchFullTree } from "../api/hierarchy";
import {
  getSummary, getDashboardSoldiers, getFairnessInternal,
  getFairnessExternal, getPotential, getUpcoming,
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
  const queryClient = useQueryClient();

  const summaryQuery = useQuery({ queryKey: queryKeys.commandDashboardSummary(), queryFn: getSummary });
  const summaryData = summaryQuery.data ?? null;

  const soldiersQuery = useQuery({ queryKey: queryKeys.commandDashboardSoldiers(), queryFn: getDashboardSoldiers });
  const soldiers = useMemo(() => soldiersQuery.data ?? [], [soldiersQuery.data]);

  const nodesQuery = useQuery({ queryKey: queryKeys.hierarchyTree(), queryFn: fetchFullTree });
  const nodes = useMemo(() => nodesQuery.data ?? [], [nodesQuery.data]);

  const fairnessInternalQuery = useQuery({ queryKey: queryKeys.commandDashboardFairnessInternal(), queryFn: getFairnessInternal });
  const fairnessInternal = fairnessInternalQuery.data ?? null;

  const fairnessExternalQuery = useQuery({ queryKey: queryKeys.commandDashboardFairnessExternal(), queryFn: getFairnessExternal });
  const fairnessExternal = fairnessExternalQuery.data ?? null;

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
  const refresh = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.commandDashboardSummary() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.commandDashboardSoldiers() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.hierarchyTree() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.soldiers() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.commandDashboardFairnessInternal() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.commandDashboardFairnessExternal() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.commandDashboardPotential() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.commandDashboardUpcoming() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.commandDashboardAlerts() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.pendingEnrollments() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.pendingSwaps() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.pendingConstraintsCount() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.pendingExemptionsCount() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.pendingFieldUpdatesCount() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.pendingHierarchyTransfers() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.commandDashboardOwnPotentialAll() }),
    ]);
  }, [queryClient]);

  // The nodes this commander directly commands — same scope-resolution used
  // elsewhere in the app (e.g. TeamHierarchyPage) to find "my" node(s).
  const myNodes = useMemo(
    () => nodes.filter((n) => n.commander_id === user?.id),
    [nodes, user],
  );

  const soldiersByNode = useMemo(() => {
    const nodeNameById = new Map(nodes.map((n) => [n.id, n.name]));
    const counts = new Map<string, number>();
    for (const s of soldiers) {
      const label = s.hierarchy_node_id ? (nodeNameById.get(s.hierarchy_node_id) ?? t("command_dashboard.node")) : t("command_dashboard.node");
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
    return Array.from(counts.entries()).map(([nodeName, count]) => ({ nodeName, count }));
  }, [nodes, soldiers, t]);

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
      content: myNodes.length > 0 ? <UnitCalendar nodeId={myNodes[0].id} /> : null,
    },
    {
      id: "soldiers",
      title: t("command_dashboard.soldiers_panel_title"),
      content: (
        <div data-testid="soldiers-summary">
          <p className="text-sm text-gray-600 dark:text-gray-300">
            {t("command_dashboard.soldiers_count", { count: soldiers.length })}
          </p>
          <ul className="mt-2 space-y-1 text-sm">
            {soldiersByNode.map(({ nodeName, count }) => (
              <li key={nodeName} className="flex justify-between border-b border-gray-100 dark:border-gray-700 py-1">
                <span>{nodeName}</span>
                <span className="text-gray-500 dark:text-gray-400">{count}</span>
              </li>
            ))}
          </ul>
          <Link
            to="/team"
            className="inline-block mt-3 text-indigo-600 dark:text-indigo-300 hover:underline"
            data-testid="soldiers-panel-team-link"
          >
            {t("command_dashboard.go_to_team")}
          </Link>
        </div>
      ),
    },
    {
      id: "entries_exits",
      title: t("command_dashboard.entries_exits"),
      content: <EntriesExitsPanel soldiers={soldiers} onRefresh={refresh} />,
    },
    {
      id: "fairness_internal",
      title: t("command_dashboard.internal_fairness"),
      content: <InternalFairness data={fairnessInternal} />,
    },
    {
      id: "fairness_external",
      title: t("command_dashboard.external_fairness"),
      content: <ExternalFairness data={fairnessExternal} />,
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
