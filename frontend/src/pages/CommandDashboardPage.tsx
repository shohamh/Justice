import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import SummaryCards from "../components/SummaryCards";
import UpcomingSnapshot from "../components/UpcomingSnapshot";
import AlertsPanel from "../components/AlertsPanel";
import { InternalFairness, ExternalFairness } from "../components/FairnessChart";
import DutyPotentialPanel from "../components/DutyPotentialPanel";
import ApprovalsFeed from "../components/ApprovalsFeed";
import EntriesExitsPanel from "../components/EntriesExitsPanel";
import UnitCalendar from "../components/UnitCalendar";
import HierarchyTree from "../components/HierarchyTree";
import { useAuth } from "../auth/AuthContext";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import { listSoldiers } from "../api/soldiers";
import type { SoldierDTO } from "../api/soldiers";
import {
  getSummary, getDashboardSoldiers, getFairnessInternal,
  getFairnessExternal, getPotential, getUpcoming,
  getAlerts, getApprovals,
  type SummaryCards as SummaryCardsData,
  type SoldierWithStatus, type FairnessStats,
  type NodeFairness, type PotentialCount,
  type UpcomingDay, type Alert, type ApprovalItem,
} from "../api/commanderDashboard";

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
  const [approvalsData, setApprovalsData] = useState<ApprovalItem[] | null>(null);
  const [activePanel, setActivePanel] = useState<string>("summary");

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      getSummary(), getDashboardSoldiers(), getFairnessInternal(),
      getFairnessExternal(), getPotential(), getUpcoming(),
      getAlerts(), getApprovals(), fetchTree(), listSoldiers(),
    ]);
    if (results[0].status === "fulfilled") setSummaryData(results[0].value);
    if (results[1].status === "fulfilled") setSoldiers(results[1].value);
    if (results[2].status === "fulfilled") setFairnessInternal(results[2].value);
    if (results[3].status === "fulfilled") setFairnessExternal(results[3].value);
    if (results[4].status === "fulfilled") setPotentialData(results[4].value);
    if (results[5].status === "fulfilled") setUpcomingData(results[5].value);
    if (results[6].status === "fulfilled") setAlertsData(results[6].value);
    if (results[7].status === "fulfilled") setApprovalsData(results[7].value);
    if (results[8].status === "fulfilled") setNodes(results[8].value);
    if (results[9].status === "fulfilled") setSoldierDTOs(results[9].value);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const handleCardClick = (panel: string) => setActivePanel(panel);

  const panels: { id: string; title: string; content: React.ReactNode }[] = [
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
            <HierarchyTree nodes={nodes} soldiers={soldierDTOs} isAdmin={false} onChanged={refresh} user={user} />
          </div>
        </div>
      ),
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
      id: "entries_exits",
      title: t("command_dashboard.entries_exits"),
          content: <EntriesExitsPanel soldiers={soldiers} onRefresh={refresh} />,
    },
    {
      id: "potential",
      title: t("command_dashboard.potential"),
      content: <DutyPotentialPanel data={potentialData} />,
    },
    {
      id: "approvals",
      title: t("command_dashboard.approvals"),
       content: <ApprovalsFeed data={approvalsData} onRefresh={refresh} />,
    },
    {
      id: "upcoming",
      title: t("command_dashboard.upcoming"),
      content: <UpcomingSnapshot data={upcomingData} />,
    },
    {
      id: "alerts",
      title: t("command_dashboard.alerts"),
      content: <AlertsPanel data={alertsData} />,
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
