import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { DataTable, type ColDef } from "../DataTable";
import SoldierLink from "../SoldierLink";
import type { DutyEligibilityFact, IneligibleHierarchyNode, IneligibleSoldier, IneligibleSoldiersResponse } from "../../api/ineligibleSoldiers";
import { formatRangeEligibilityExplanation } from "../../utils/rangeEligibilityExplanation";
import { RANGE_TYPE_LABELS } from "../../utils/rangeLabels";
import { useLevelTypes } from "../../hooks/useLevelTypes";

interface Props {
  data?: IneligibleSoldiersResponse;
  loading?: boolean;
  error?: boolean;
}

interface HierarchyRow extends IneligibleHierarchyNode {
  depth: number;
  soldierCount: number;
}

function hierarchyRows(data: IneligibleSoldiersResponse): HierarchyRow[] {
  const byParent = new Map<string | null, IneligibleHierarchyNode[]>();
  for (const node of data.nodes) byParent.set(node.parent_id, [...(byParent.get(node.parent_id) ?? []), node]);

  const result: HierarchyRow[] = [];
  const visited = new Set<string>();
  function visit(node: IneligibleHierarchyNode, depth: number) {
    if (visited.has(node.id)) return;
    visited.add(node.id);
    result.push({
      ...node,
      depth,
      soldierCount: new Set(data.soldiers.filter((soldier) => soldier.hierarchy_path_ids.includes(node.id)).map((soldier) => soldier.soldier_id)).size,
    });
    for (const child of byParent.get(node.id) ?? []) visit(child, depth + 1);
  }

  for (const root of byParent.get(null) ?? []) visit(root, 0);
  for (const node of data.nodes) visit(node, 0);
  return result;
}

function soldiersForNode(data: IneligibleSoldiersResponse, nodeId: string): IneligibleSoldier[] {
  const byId = new Map<string, IneligibleSoldier>();
  for (const soldier of data.soldiers) if (soldier.hierarchy_path_ids.includes(nodeId)) byId.set(soldier.soldier_id, soldier);
  return [...byId.values()];
}

const noWeaponDutyFact: DutyEligibilityFact = {
  eligible: true,
  required_range_type: null,
  qualification_source: "not_required",
  covered_by_range_date: null,
  projected_valid_until: null,
  reason: null,
  duty_type_name: "",
  start_date: "",
};

function formatDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${day}.${month}.${year}`;
}

export function IneligibleSoldiersTable({ data, loading, error }: Props) {
  const { t } = useTranslation();
  const { levelTypes } = useLevelTypes();
  const [expandedNodeId, setExpandedNodeId] = useState<string | null>(null);
  const rows = useMemo(() => (data ? hierarchyRows(data) : []), [data]);
  const levelLabelByKey = useMemo(() => new Map(levelTypes.map((levelType) => [levelType.key, levelType.label])), [levelTypes]);
  const qualificationText = (soldier: IneligibleSoldier): string => {
    if (soldier.valid_qualifications.length === 0) return t("range_qualification.warning.normal");
    return soldier.valid_qualifications
      .map((qualification) => `${RANGE_TYPE_LABELS[qualification.range_type] ?? qualification.range_type} ${t("range_qualification.qualificationExpiry", { date: formatDate(qualification.valid_until) })}`)
      .join(", ");
  };
  const futureContextText = (soldier: IneligibleSoldier): string => {
    if (soldier.upcoming_weapon_duties.length === 0) {
      return formatRangeEligibilityExplanation(noWeaponDutyFact, t);
    }
    return soldier.upcoming_weapon_duties
      .map((duty) => formatRangeEligibilityExplanation(duty, t))
      .join(" · ");
  };
  const warningContent = (soldier: IneligibleSoldier) => {
    const urgent = soldier.upcoming_weapon_duties.some((duty) => !duty.eligible);
    return <span data-testid={`ineligible-warning-${soldier.soldier_id}`} className={`inline-block rounded px-2 py-1 ${urgent
      ? "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300"
      : "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"}`}>
      {futureContextText(soldier)}
    </span>;
  };

  const nodeColumns: ColDef<HierarchyRow>[] = [
    {
      id: "node",
      header: t("range_qualification.columns.unit"),
      cell: (node) => <span className="flex items-center gap-2" style={{ paddingRight: node.depth * 16 }}><span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600 dark:bg-gray-700 dark:text-gray-300">{levelLabelByKey.get(node.level) ?? node.level}</span><span>{node.name}</span></span>,
      sortValue: (node) => node.name,
      filterValue: (node) => node.name,
    },
    { id: "count", header: t("range_qualification.columns.count"), cell: (node) => node.soldierCount, sortValue: (node) => node.soldierCount },
  ];
  const soldierColumns: ColDef<IneligibleSoldier>[] = [
    { id: "soldier", header: t("range_qualification.columns.soldier"), cell: (soldier) => <SoldierLink id={soldier.soldier_id} name={soldier.soldier_name} />, sortValue: (soldier) => soldier.soldier_name, filterValue: (soldier) => `${soldier.soldier_name} ${soldier.personal_number}` },
    { id: "qualification", header: t("range_qualification.columns.qualification"), cell: qualificationText, sortValue: qualificationText, filterValue: qualificationText },
    { id: "context", header: t("range_qualification.columns.context"), cell: warningContent, sortValue: futureContextText, filterValue: futureContextText },
  ];

  if (loading) return <div data-testid="ineligible-soldiers-view" role="status" className="rounded-lg border border-dashed p-6 text-center text-sm text-gray-600 dark:border-gray-600 dark:text-gray-300">{t("range_qualification.soldiersLoading")}</div>;
  if (error) return <div data-testid="ineligible-soldiers-view" role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-300">{t("range_qualification.soldiersError")}</div>;
  if (!data || data.count === 0) return <div data-testid="ineligible-soldiers-view" role="status" className="rounded-lg border border-dashed p-6 text-center text-sm text-gray-600 dark:border-gray-600 dark:text-gray-300">{t("range_qualification.soldiersEmpty")}</div>;

  return <div data-testid="ineligible-soldiers-view" className="space-y-3" dir="rtl">
    <p className="text-sm text-gray-700 dark:text-gray-200">{t("range_qualification.soldiersCount", { count: data.count })}</p>
    <DataTable
      columns={nodeColumns}
      data={rows}
      filterPlaceholder={t("range_qualification.filterUnits")}
      emptyMessage={t("range_qualification.emptyUnits")}
      testId="ineligible-soldiers-table"
      rowTestId={(node) => `ineligible-node-${node.id}`}
      rowClassName={(node) => (node.id === expandedNodeId ? "bg-indigo-50 dark:bg-indigo-950" : "")}
      expandable={{
        isExpanded: (node) => node.id === expandedNodeId,
        onToggle: (node) => setExpandedNodeId((current) => current === node.id ? null : node.id),
        content: (node) => <div className="p-2"><DataTable columns={soldierColumns} data={soldiersForNode(data, node.id)} filterPlaceholder={t("range_qualification.filterSoldiers")} emptyMessage={t("range_qualification.emptySoldiersInUnit")} testId={`ineligible-soldiers-node-${node.id}`} /></div>,
      }}
    />
  </div>;
}
