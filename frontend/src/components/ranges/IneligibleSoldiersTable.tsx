import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { DataTable, type ColDef } from "../DataTable";
import SoldierLink from "../SoldierLink";
import type { IneligibleHierarchyNode, IneligibleSoldier, IneligibleSoldiersResponse } from "../../api/ineligibleSoldiers";
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

export function IneligibleSoldiersTable({ data, loading, error }: Props) {
  const { t } = useTranslation();
  const { levelTypes } = useLevelTypes();
  const [expandedNodeId, setExpandedNodeId] = useState<string | null>(null);
  const rows = useMemo(() => (data ? hierarchyRows(data) : []), [data]);
  const levelLabelByKey = useMemo(() => new Map(levelTypes.map((levelType) => [levelType.key, levelType.label])), [levelTypes]);
  const qualificationText = (soldier: IneligibleSoldier): string => {
    if (soldier.valid_qualifications.length === 0) return t("range_qualification.warning.normal");
    return soldier.valid_qualifications
      .map((qualification) => `${RANGE_TYPE_LABELS[qualification.range_type] ?? qualification.range_type} ${t("range_qualification.qualificationExpiry", { date: qualification.valid_until })}`)
      .join(", ");
  };
  const warningContent = (soldier: IneligibleSoldier) => {
    const urgent = soldier.has_upcoming_weapon_duty && !soldier.has_upcoming_matching_range;
    const dutyText = soldier.upcoming_weapon_duties.map((duty) => `${duty.duty_type_name} ${duty.start_date}`).join(", ");
    const rangeText = soldier.upcoming_matching_ranges
      .map((range) => `מטווח מתוכנן ${RANGE_TYPE_LABELS[range.range_type] ?? range.range_type} ${range.date}`)
      .join(", ");
    return <span data-testid={`ineligible-warning-${soldier.soldier_id}`} className={`inline-block rounded px-2 py-1 ${urgent
      ? "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300"
      : "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"}`}>
      {[t(urgent ? "range_qualification.warning.urgent" : "range_qualification.warning.normal"), dutyText, rangeText].filter(Boolean).join(" · ")}
    </span>;
  };

  const nodeColumns: ColDef<HierarchyRow>[] = [
    {
      id: "node",
      header: "יחידה",
      cell: (node) => <span className="flex items-center gap-2" style={{ paddingRight: node.depth * 16 }}><span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600 dark:bg-gray-700 dark:text-gray-300">{levelLabelByKey.get(node.level) ?? node.level}</span><span>{node.name}</span></span>,
      sortValue: (node) => node.name,
      filterValue: (node) => node.name,
    },
    { id: "count", header: "חיילים ללא הסמכה", cell: (node) => node.soldierCount, sortValue: (node) => node.soldierCount },
  ];
  const soldierColumns: ColDef<IneligibleSoldier>[] = [
    { id: "soldier", header: "חייל", cell: (soldier) => <SoldierLink id={soldier.soldier_id} name={soldier.soldier_name} />, sortValue: (soldier) => soldier.soldier_name, filterValue: (soldier) => `${soldier.soldier_name} ${soldier.personal_number}` },
    { id: "qualification", header: "הסמכות בתוקף", cell: qualificationText, filterValue: qualificationText },
    { id: "context", header: "הקשר עתידי", cell: warningContent },
  ];

  if (loading) return <div data-testid="ineligible-soldiers-view" role="status" className="rounded-lg border border-dashed p-6 text-center text-sm text-gray-600 dark:border-gray-600 dark:text-gray-300">טוען חיילים ללא הסמכה…</div>;
  if (error) return <div data-testid="ineligible-soldiers-view" role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-300">טעינת החיילים ללא הסמכה נכשלה</div>;
  if (!data || data.count === 0) return <div data-testid="ineligible-soldiers-view" role="status" className="rounded-lg border border-dashed p-6 text-center text-sm text-gray-600 dark:border-gray-600 dark:text-gray-300">אין חיילים ללא הסמכת מטווח</div>;

  return <div data-testid="ineligible-soldiers-view" className="space-y-3" dir="rtl">
    <p className="text-sm text-gray-700 dark:text-gray-200">{data.count} חיילים ללא הסמכת מטווח</p>
    <DataTable
      columns={nodeColumns}
      data={rows}
      filterPlaceholder="סינון יחידות..."
      emptyMessage="אין יחידות להצגה"
      testId="ineligible-soldiers-table"
      rowTestId={(node) => `ineligible-node-${node.id}`}
      rowClassName={(node) => (node.id === expandedNodeId ? "bg-indigo-50 dark:bg-indigo-950" : "")}
      expandable={{
        isExpanded: (node) => node.id === expandedNodeId,
        onToggle: (node) => setExpandedNodeId((current) => current === node.id ? null : node.id),
        content: (node) => <div className="p-2"><DataTable columns={soldierColumns} data={soldiersForNode(data, node.id)} filterPlaceholder="סינון חיילים..." emptyMessage="אין חיילים ללא הסמכה ביחידה זו" testId={`ineligible-soldiers-node-${node.id}`} /></div>,
      }}
    />
  </div>;
}
