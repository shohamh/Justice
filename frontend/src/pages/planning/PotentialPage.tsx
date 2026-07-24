import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueries, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import Layout from "../../components/Layout";
import { queryKeys } from "../../queryKeys";
import { DataTable, type ColDef } from "../../components/DataTable";
import { ExcelExportButton } from "../../components/ExcelExportButton";
import SoldierLink from "../../components/SoldierLink";
import {
  getPotential,
  listModifiers,
  createModifier,
  deleteModifier,
  getEffortGap,
  PotentialResult,
  SoldierPotentialDetail,
} from "../../api/potential";
import { fetchFullTree, NodeDTO } from "../../api/hierarchy";
import { listDutyTypes } from "../../api/dutyConfig";
import { useLevelTypes } from "../../hooks/useLevelTypes";
import { sortNodesByTree } from "../../utils/sortNodesByTree";
import { WHOLE_ORG_ID } from "../../utils/wholeOrg";
import ExemptionsCell from "../../components/ExemptionsCell";
import DateInput from "../../components/DateInput";

export default function PotentialPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { levelTypes } = useLevelTypes();
  const levelLabelByKey = useMemo(
    () => new Map(levelTypes.map((lt) => [lt.key, lt.label])),
    [levelTypes],
  );
  const [referenceDate, setReferenceDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [expandedNodeId, setExpandedNodeId] = useState<string | null>(null);
  const [newReason, setNewReason] = useState("");
  const [newDelta, setNewDelta] = useState(0);
  const [exportRows, setExportRows] = useState<NodeDTO[]>([]);
  const [selectedDutyTypeIds, setSelectedDutyTypeIds] = useState<string[]>([]);

  const dutyTypesQuery = useQuery({ queryKey: queryKeys.dutyTypes(), queryFn: listDutyTypes });
  const dutyTypes = useMemo(() => dutyTypesQuery.data ?? [], [dutyTypesQuery.data]);

  function toggleDutyTypePill(id: string) {
    setSelectedDutyTypeIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  const treeQuery = useQuery({ queryKey: queryKeys.hierarchyTree(), queryFn: fetchFullTree });
  const treeNodes = useMemo(() => treeQuery.data ?? [], [treeQuery.data]);

  const nodes = useMemo(() => sortNodesByTree(treeNodes).map((n) => n.node), [treeNodes]);

  const topLevelRoots = useMemo(() => nodes.filter((n) => n.parent_id === null), [nodes]);

  const potentialQueries = useQueries({
    queries: nodes.map((n) => ({
      queryKey: queryKeys.potentialByNode(n.id, referenceDate),
      queryFn: () => getPotential(n.id, referenceDate),
    })),
  });

  const results = useMemo(() => {
    const byId: Record<string, PotentialResult> = {};
    nodes.forEach((n, i) => {
      const result = potentialQueries[i];
      if (result?.data) {
        byId[n.id] = result.data;
      } else if (result?.isError) {
        console.error(`Failed to fetch potential for node ${n.id}:`, result.error);
      }
    });
    return byId;
  }, [nodes, potentialQueries]);

  // Synthetic aggregate row representing the whole organization. Skipped when
  // there's exactly one real root node, since that node's own row already IS
  // the whole-org total — only needed as a fallback for 0 or 2+ real roots.
  const wholeOrgResult = useMemo((): PotentialResult | null => {
    if (topLevelRoots.length <= 1) return null;
    const rootResults = topLevelRoots.map((n) => results[n.id]).filter((r): r is PotentialResult => !!r);
    if (rootResults.length !== topLevelRoots.length) return null; // not all roots loaded yet
    return {
      node_id: WHOLE_ORG_ID,
      as_of: rootResults[0].as_of,
      raw_eligible_count: rootResults.reduce((s, r) => s + r.raw_eligible_count, 0),
      total_soldiers: rootResults.reduce((s, r) => s + r.total_soldiers, 0),
      modifiers: rootResults.flatMap((r) => r.modifiers),
      final_potential: rootResults.reduce((s, r) => s + r.final_potential, 0),
      soldiers: rootResults.flatMap((r) => r.soldiers),
      partial_exemption_count: rootResults.reduce((s, r) => s + r.partial_exemption_count, 0),
    };
  }, [topLevelRoots, results]);

  const displayResults = useMemo(
    () => (wholeOrgResult ? { ...results, [WHOLE_ORG_ID]: wholeOrgResult } : results),
    [results, wholeOrgResult],
  );

  const wholeOrgNode: NodeDTO = useMemo(() => ({
    id: WHOLE_ORG_ID,
    level: "corps",
    name: t("common.whole_org"),
    parent_id: null,
    commander_id: null,
    commander_name: null,
    path_ids: [WHOLE_ORG_ID],
    duty_managers: [],
    dm_manageable: false,
    can_edit: false,
  }), [t]);

  const tableRows = useMemo(
    () => (wholeOrgResult ? [wholeOrgNode, ...nodes] : nodes),
    [wholeOrgResult, wholeOrgNode, nodes],
  );

  const modifiersQuery = useQuery({
    queryKey: queryKeys.potentialModifiers(expandedNodeId ?? "none"),
    queryFn: () => listModifiers(expandedNodeId!),
    enabled: !!expandedNodeId && expandedNodeId !== WHOLE_ORG_ID,
  });
  const modifiers = useMemo(() => modifiersQuery.data ?? [], [modifiersQuery.data]);

  const effortGapQuery = useQuery({
    queryKey: queryKeys.effortGapNodes(referenceDate),
    queryFn: () => getEffortGap(referenceDate),
  });
  const effortGapByNode = useMemo(
    () => new Map((effortGapQuery.data ?? []).map((r) => [r.node_id, r])),
    [effortGapQuery.data],
  );

  async function handleAddModifier() {
    if (!expandedNodeId || expandedNodeId === WHOLE_ORG_ID || !newReason.trim()) return;
    await createModifier({ hierarchy_node_id: expandedNodeId, delta: newDelta, reason: newReason, start_date: referenceDate });
    await queryClient.invalidateQueries({ queryKey: queryKeys.potentialModifiers(expandedNodeId) });
    await queryClient.invalidateQueries({ queryKey: queryKeys.potentialByNode(expandedNodeId, referenceDate) });
    setNewReason("");
    setNewDelta(0);
  }

  async function handleDeleteModifier(modifierId: string) {
    if (!expandedNodeId) return;
    await deleteModifier(modifierId);
    await queryClient.invalidateQueries({ queryKey: queryKeys.potentialModifiers(expandedNodeId) });
    await queryClient.invalidateQueries({ queryKey: queryKeys.potentialByNode(expandedNodeId, referenceDate) });
  }

  function modifierSum(r: PotentialResult | undefined): number {
    return r ? r.modifiers.reduce((s, m) => s + m.delta, 0) : 0;
  }

  function pctOfParentValue(n: NodeDTO): number | null {
    if (n.id === WHOLE_ORG_ID) return null;
    const parentId = n.parent_id ?? WHOLE_ORG_ID;
    const parentFinal = displayResults[parentId]?.final_potential;
    const ownFinal = displayResults[n.id]?.final_potential;
    if (parentFinal === undefined || ownFinal === undefined || parentFinal === 0) return null;
    return (ownFinal / parentFinal) * 100;
  }

  function pctOfParentText(n: NodeDTO): string {
    const pct = pctOfParentValue(n);
    return pct === null ? "—" : `${pct.toFixed(0)}%`;
  }

  function pctEligibleValue(n: NodeDTO): number | null {
    const r = displayResults[n.id];
    if (!r || r.total_soldiers === 0) return null;
    return (r.raw_eligible_count / r.total_soldiers) * 100;
  }

  function pctEligibleText(n: NodeDTO): string {
    const pct = pctEligibleValue(n);
    return pct === null ? "—" : `${pct.toFixed(0)}%`;
  }

  function filterSoldiersByDutyType(soldiers: SoldierPotentialDetail[]): SoldierPotentialDetail[] {
    if (selectedDutyTypeIds.length === 0) return soldiers;
    return soldiers.filter((s) =>
      selectedDutyTypeIds.every((dtId) => s.eligible_duty_type_ids.includes(dtId)),
    );
  }

  function toggleExpanded(nodeId: string) {
    setExpandedNodeId((prev) => (prev === nodeId ? null : nodeId));
  }

  function reasonLabel(reason: string | null): string {
    if (!reason) return "";
    return t(`potential.reason_${reason}`, { defaultValue: reason });
  }

  function reasonText(s: SoldierPotentialDetail): string {
    if (s.counted) {
      return s.partial_exemption_names && s.partial_exemption_names.length > 0
        ? s.partial_exemption_names.join(", ")
        : "";
    }
    if (s.reason === "exempted") {
      return s.exemption_names && s.exemption_names.length > 0
        ? s.exemption_names.join(", ")
        : t("potential.reason_exempted_restricted");
    }
    return reasonLabel(s.reason);
  }

  function gapColor(gap: number | null): string {
    if (gap === null) return "text-gray-400";
    if (gap > 1.3) return "text-red-600 dark:text-red-400 font-semibold";
    if (gap < 0.7) return "text-blue-600 dark:text-blue-400 font-semibold";
    return "text-gray-700 dark:text-gray-300";
  }

  function formatGap(gap: number | null): string {
    return gap === null ? "—" : gap.toFixed(3);
  }

  const cols: ColDef<NodeDTO>[] = [
    {
      id: "name",
      header: t("potential.node"),
      cell: (n) =>
        n.id === WHOLE_ORG_ID ? (
          <span className="font-semibold">{n.name}</span>
        ) : (
          <span className="flex items-center gap-2" style={{ paddingRight: (n.path_ids.length - 1) * 16 }}>
            <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300 shrink-0">
              {levelLabelByKey.get(n.level) ?? n.level}
            </span>
            <span>{n.name}</span>
          </span>
        ),
      sortValue: (n) => n.name,
      filterValue: (n) => n.name,
    },
    {
      id: "sadach",
      header: t("potential.sadach"),
      headerTooltip: t("potential.sadach_tooltip"),
      cell: (n) => displayResults[n.id]?.total_soldiers ?? "-",
      sortValue: (n) => displayResults[n.id]?.total_soldiers ?? -1,
    },
    {
      id: "eligible",
      header: t("potential.eligible"),
      headerTooltip: t("potential.eligible_tooltip"),
      cell: (n) => displayResults[n.id]?.raw_eligible_count ?? "-",
      sortValue: (n) => displayResults[n.id]?.raw_eligible_count ?? -1,
    },
    {
      id: "partial_exemptions",
      header: t("potential.partial_exemptions"),
      headerTooltip: t("potential.partial_exemptions_tooltip"),
      cell: (n) => displayResults[n.id]?.partial_exemption_count ?? "-",
      sortValue: (n) => displayResults[n.id]?.partial_exemption_count ?? -1,
    },
    {
      id: "pct_eligible",
      header: t("potential.pct_eligible"),
      headerTooltip: t("potential.pct_eligible_tooltip"),
      cell: (n) => pctEligibleText(n),
      sortValue: (n) => pctEligibleValue(n) ?? -Infinity,
      exportValue: (n) => {
        const pct = pctEligibleValue(n);
        return pct === null ? "" : Math.round(pct);
      },
    },
    {
      id: "modifiers",
      header: t("potential.modifiers"),
      headerTooltip: t("potential.modifiers_tooltip"),
      cell: (n) => (displayResults[n.id] ? modifierSum(displayResults[n.id]) : "-"),
      sortValue: (n) => (displayResults[n.id] ? modifierSum(displayResults[n.id]) : -Infinity),
    },
    {
      id: "final_potential",
      header: t("potential.final_potential"),
      headerTooltip: t("potential.final_potential_tooltip"),
      cell: (n) => displayResults[n.id]?.final_potential ?? "-",
      sortValue: (n) => displayResults[n.id]?.final_potential ?? -1,
    },
    {
      id: "sibling_gap",
      header: t("potential.sibling_gap"),
      cell: (n) => <span className={gapColor(effortGapByNode.get(n.id)?.sibling_gap ?? null)}>{formatGap(effortGapByNode.get(n.id)?.sibling_gap ?? null)}</span>,
      sortValue: (n) => effortGapByNode.get(n.id)?.sibling_gap ?? -1,
      exportValue: (n) => formatGap(effortGapByNode.get(n.id)?.sibling_gap ?? null),
    },
    {
      id: "global_gap",
      header: t("potential.global_gap"),
      cell: (n) => <span className={gapColor(effortGapByNode.get(n.id)?.global_gap ?? null)}>{formatGap(effortGapByNode.get(n.id)?.global_gap ?? null)}</span>,
      sortValue: (n) => effortGapByNode.get(n.id)?.global_gap ?? -1,
      exportValue: (n) => formatGap(effortGapByNode.get(n.id)?.global_gap ?? null),
    },
    {
      id: "pct_of_parent",
      header: t("potential.pct_of_parent"),
      headerTooltip: t("potential.pct_of_parent_tooltip"),
      cell: (n) => pctOfParentText(n),
      sortValue: (n) => pctOfParentValue(n) ?? -Infinity,
      exportValue: (n) => {
        const pct = pctOfParentValue(n);
        return pct === null ? "" : Math.round(pct);
      },
    },
  ];

  const soldierCols: ColDef<SoldierPotentialDetail>[] = [
    {
      id: "name",
      header: t("potential.soldier_name"),
      cell: (s) => <SoldierLink id={s.soldier_id} name={s.full_name} />,
      sortValue: (s) => s.full_name,
      filterValue: (s) => s.full_name,
    },
    {
      id: "rank",
      header: t("potential.rank_col"),
      cell: (s) => s.rank ?? "—",
      sortValue: (s) => s.rank ?? "",
      filterValue: (s) => s.rank ?? "",
    },
    {
      id: "counted",
      header: t("potential.counted_col"),
      cell: (s) =>
        s.counted ? (
          <span
            className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400"
            title={t("potential.counted")}
          >
            <Check size={14} aria-label={t("potential.counted")} />
          </span>
        ) : (
          <span
            className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400"
            title={t("potential.not_counted_short")}
          >
            <X size={14} aria-label={t("potential.not_counted_short")} />
          </span>
        ),
      sortValue: (s) => (s.counted ? 1 : 0),
      columnFilter: true,
      filterValue: (s) => (s.counted ? t("potential.counted") : t("potential.not_counted_short")),
    },
    {
      id: "reason",
      header: t("potential.reason_col"),
      cell: (s) => {
        if (s.counted && (!s.partial_exemption_names || s.partial_exemption_names.length === 0)) {
          return "—";
        }
        if (s.counted || s.reason === "exempted") {
          return (
            <ExemptionsCell
              exemptions={s.exemptions ?? []}
              visible={s.exemption_names !== null}
              placeholder={t("potential.reason_exempted_restricted")}
              soldierId={s.soldier_id}
            />
          );
        }
        return reasonText(s);
      },
      filterValue: (s) => reasonText(s),
    },
  ];

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl">
        <h2 className="text-xl font-semibold">{t("potential.title")}</h2>
        <div className="flex gap-2 items-center">
          <label>{t("potential.reference_date")}:</label>
          <DateInput value={referenceDate} onChange={(isoValue) => setReferenceDate(isoValue)} className="border rounded p-1" />
        </div>

        {dutyTypes.length > 0 && (
          <div className="flex flex-wrap gap-2" dir="rtl">
            {dutyTypes.map((dt) => (
              <button
                key={dt.id}
                type="button"
                onClick={() => toggleDutyTypePill(dt.id)}
                aria-pressed={selectedDutyTypeIds.includes(dt.id)}
                className={`px-3 py-1 rounded-full text-xs border transition-colors ${
                  selectedDutyTypeIds.includes(dt.id)
                    ? "bg-indigo-600 text-white border-indigo-600"
                    : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 border-gray-300 dark:border-gray-600"
                }`}
              >
                {dt.name}
              </button>
            ))}
          </div>
        )}

        <div className="flex justify-start" dir="ltr">
          <ExcelExportButton columns={cols} rows={exportRows} filename="potential.xlsx" />
        </div>
        <DataTable
          columns={cols}
          data={tableRows}
          filterPlaceholder={t("table.filter_placeholder")}
          rowClassName={(n) => (n.id === expandedNodeId ? "bg-indigo-50 dark:bg-indigo-950" : "")}
          testId="potential-table"
          onVisibleRowsChange={setExportRows}
          expandable={{
            isExpanded: (n) => n.id === expandedNodeId,
            onToggle: (n) => toggleExpanded(n.id),
            content: (n) => (
              <div className="p-2">
                <DataTable
                  columns={soldierCols}
                  data={filterSoldiersByDutyType(displayResults[n.id]?.soldiers ?? [])}
                  filterPlaceholder={t("table.filter_placeholder")}
                  emptyMessage={t("potential.no_soldiers")}
                  testId={`potential-soldiers-table-${n.id}`}
                />
              </div>
            ),
          }}
        />

        {expandedNodeId && expandedNodeId !== WHOLE_ORG_ID && (
          <div className="border dark:border-gray-700 rounded p-3 space-y-2">
            <h3 className="font-semibold">{t("potential.manual_modifiers_title")}</h3>
            <ul>
              {modifiers.map((m) => (
                <li key={m.id}>
                  {m.delta > 0 ? "+" : ""}{m.delta} — {m.reason} ({m.start_date}
                  {m.end_date ? ` ${t("potential.modifier_until")} ${m.end_date}` : ""})
                  <button
                    className="text-red-600 mr-2"
                    onClick={() => void handleDeleteModifier(m.id)}
                  >
                    {t("potential.modifier_delete")}
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex gap-2">
              <input type="number" value={newDelta} onChange={(e) => setNewDelta(Number(e.target.value))} className="border rounded p-1 w-20" />
              <input
                type="text"
                value={newReason}
                onChange={(e) => setNewReason(e.target.value)}
                placeholder={t("potential.modifier_reason_placeholder")}
                className="border rounded p-1 flex-1"
              />
              <button onClick={handleAddModifier} className="bg-blue-600 text-white rounded px-3 py-1">
                {t("potential.modifier_add")}
              </button>
            </div>
          </div>
        )}
      </section>
    </Layout>
  );
}
