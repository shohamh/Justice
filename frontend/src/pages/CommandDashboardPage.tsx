import { useEffect, useState, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import SummaryCards from "../components/SummaryCards";
import UpcomingSnapshot from "../components/UpcomingSnapshot";
import AlertsPanel from "../components/AlertsPanel";
import { InternalFairness, ExternalFairness } from "../components/FairnessChart";
import DutyPotentialPanel from "../components/DutyPotentialPanel";
import PendingApprovalsWidget from "../components/dashboard/PendingApprovalsWidget";
import EntriesExitsPanel from "../components/EntriesExitsPanel";
import UnitCalendar from "../components/UnitCalendar";
import HierarchyTree from "../components/HierarchyTree";
import { useAuth } from "../auth/AuthContext";
import { fetchFullTree, NodeDTO } from "../api/hierarchy";
import { listSoldiers } from "../api/soldiers";
import type { SoldierDTO } from "../api/soldiers";
import {
  getSummary, getDashboardSoldiers, getFairnessInternal,
  getFairnessExternal, getPotential, getUpcoming,
  getAlerts,
  type SummaryCards as SummaryCardsData,
  type SoldierWithStatus, type FairnessStats,
  type NodeFairness, type PotentialCount,
  type UpcomingDay, type Alert,
} from "../api/commanderDashboard";
import { getPotential as getNodePotential, type PotentialResult } from "../api/potential";
import { listPendingEnrollments, type EnrollmentRequestDTO } from "../api/enrollment";
import { listPendingSwaps, type SwapRequest } from "../api/swaps";
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";

export default function CommandDashboardPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [summaryData, setSummaryData] = useState<SummaryCardsData | null>(null);
  const [soldiers, setSoldiers] = useState<SoldierWithStatus[]>([]);
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [soldierDTOs, setSoldierDTOs] = useState<SoldierDTO[]>([]);
  const [fairnessInternal, setFairnessInternal] = useState<FairnessStats | null>(null);
  const [fairnessExternal, setFairnessExternal] = useState<NodeFairness[] | null>(null);
  const [potentialData, setPotentialData] = useState<PotentialCount[] | null>(null);
  const [upcomingData, setUpcomingData] = useState<UpcomingDay[] | null>(null);
  const [alertsData, setAlertsData] = useState<Alert[] | null>(null);
  const [pendingEnrollments, setPendingEnrollments] = useState<EnrollmentRequestDTO[]>([]);
  const [pendingSwaps, setPendingSwaps] = useState<SwapRequest[]>([]);
  const [pendingConstraints, setPendingConstraints] = useState(0);
  const [pendingExemptions, setPendingExemptions] = useState(0);
  const [pendingFieldUpdates, setPendingFieldUpdates] = useState(0);
  const [_activePanel, setActivePanel] = useState<string>("summary");
  const [ownPotential, setOwnPotential] = useState<Record<string, PotentialResult>>({});

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      getSummary(), getDashboardSoldiers(), getFairnessInternal(),
      getFairnessExternal(), getPotential(), getUpcoming(),
      getAlerts(), fetchFullTree(), listSoldiers(),
      listPendingEnrollments(), listPendingSwaps(),
      getPendingCount(), getPendingExemptionCount(), getPendingFieldUpdateCount(),
    ]);
    if (results[0].status === "fulfilled") setSummaryData(results[0].value);
    if (results[1].status === "fulfilled") setSoldiers(results[1].value);
    if (results[2].status === "fulfilled") setFairnessInternal(results[2].value);
    if (results[3].status === "fulfilled") setFairnessExternal(results[3].value);
    if (results[4].status === "fulfilled") setPotentialData(results[4].value);
    if (results[5].status === "fulfilled") setUpcomingData(results[5].value);
    if (results[6].status === "fulfilled") setAlertsData(results[6].value);
    if (results[7].status === "fulfilled") setNodes(results[7].value);
    if (results[8].status === "fulfilled") setSoldierDTOs(results[8].value);
    if (results[9].status === "fulfilled") setPendingEnrollments(results[9].value as EnrollmentRequestDTO[]);
    if (results[10].status === "fulfilled") setPendingSwaps(results[10].value as SwapRequest[]);
    if (results[11].status === "fulfilled") setPendingConstraints(results[11].value as number);
    if (results[12].status === "fulfilled") setPendingExemptions(results[12].value as number);
    if (results[13].status === "fulfilled") setPendingFieldUpdates(results[13].value as number);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  // The nodes this commander directly commands — same scope-resolution used
  // elsewhere in the app (e.g. TeamHierarchyPage) to find "my" node(s).
  const myNodes = useMemo(
    () => nodes.filter((n) => n.commander_id === user?.id),
    [nodes, user],
  );

  useEffect(() => {
    if (myNodes.length === 0) {
      setOwnPotential({});
      return;
    }
    let cancelled = false;
    Promise.allSettled(myNodes.map((n) => getNodePotential(n.id))).then((results) => {
      if (cancelled) return;
      const byId: Record<string, PotentialResult> = {};
      results.forEach((r, i) => {
        if (r.status === "fulfilled") {
          byId[myNodes[i].id] = r.value;
        } else {
          console.error(`Failed to fetch potential for node ${myNodes[i].id}:`, r.reason);
        }
      });
      setOwnPotential(byId);
    });
    return () => { cancelled = true; };
  }, [myNodes]);

  const handleCardClick = (panel: string) => setActivePanel(panel);

  const panels: { id: string; title: string; content: React.ReactNode }[] = [
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
      content: nodes.length > 0 ? <UnitCalendar nodeId={nodes[0]?.id || ""} /> : null,
    },
    {
      id: "soldiers",
      title: t("command_dashboard.soldiers"),
      content: (
        <div>
          <div className="mb-4">
            <HierarchyTree nodes={nodes} soldiers={soldierDTOs} isAdmin={false} canManageLevelTypes={false} onChanged={refresh} />
          </div>
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
        <SummaryCards data={summaryData} onCardClick={handleCardClick} />
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
