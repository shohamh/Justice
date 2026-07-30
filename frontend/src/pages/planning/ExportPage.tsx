import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import * as XLSX from "xlsx";
import Layout from "../../components/Layout";
import { queryKeys } from "../../queryKeys";
import { TransparencyRow, getTransparency } from "../../api/scoring";
import { fetchFullTree, NodeDTO } from "../../api/hierarchy";
import { getAccessToken } from "../../api/client";
import { exportValueOf } from "../../components/ExcelExportButton";
import type { ColDef } from "../../components/DataTable";

export function flattenTree(nodes: NodeDTO[]): NodeDTO[] {
  const result: NodeDTO[] = [];
  function traverse(node: NodeDTO) {
    result.push(node);
    node.children?.forEach(traverse);
  }
  nodes.forEach(traverse);
  return result;
}

export function dfsOrder(nodes: NodeDTO[]): string[] {
  const childrenByParent = new Map<string | null, NodeDTO[]>();
  for (const n of nodes) {
    const key = n.parent_id ?? null;
    if (!childrenByParent.has(key)) childrenByParent.set(key, []);
    childrenByParent.get(key)!.push(n);
  }
  for (const list of childrenByParent.values()) {
    list.sort((a, b) => a.name.localeCompare(b.name, "he"));
  }
  const order: string[] = [];
  function traverse(parentId: string | null) {
    for (const n of childrenByParent.get(parentId) ?? []) {
      order.push(n.id);
      traverse(n.id);
    }
  }
  traverse(null);
  return order;
}

export function nodePath(nodeId: string | null, nodesById: Map<string, NodeDTO>): string {
  const parts: string[] = [];
  let id = nodeId;
  while (id) {
    const node = nodesById.get(id);
    if (!node) break;
    parts.push(node.name);
    id = node.parent_id;
  }
  return parts.reverse().join(" / ");
}

interface SubRow {
  node_id: string;
  node_name: string;
  count: number;
  active_pct: number;
  avg_active_days: number;
  avg_cumulative: number;
  avg_cumulative_active: number;
  total_score_per_day: number;
  avg_normalised: number;
}

const CONFIG_SHEET_OPTIONS = [
  { key: "duty_types", label: "סוגי תורנות" },
  { key: "duty_locations", label: "מיקומי תורנות" },
  { key: "hierarchy", label: "היררכיה" },
  { key: "exemption_types", label: "פטורים" },
  { key: "system_settings", label: "הגדרות מערכת" },
  { key: "bug_reports", label: "דוחות תקלות" },
] as const;

const DATA_SHEET_OPTIONS = [
  { key: "soldiers", label: "חיילים" },
  { key: "duty_shifts", label: "משמרות" },
  { key: "assignments", label: "שיבוצים" },
  { key: "shift_templates", label: "תבניות תורנות" },
] as const;

const ALL_KEYS = [
  "transparency",
  "sub_units",
  ...CONFIG_SHEET_OPTIONS.map((o) => o.key),
  ...DATA_SHEET_OPTIONS.map((o) => o.key),
] as const;

export default function ExportPage() {
  const { t } = useTranslation();
  const [checked, setChecked] = useState<Record<string, boolean>>({});

  const transparencyQuery = useQuery({ queryKey: queryKeys.transparency(), queryFn: getTransparency });
  const rows = useMemo<TransparencyRow[]>(() => transparencyQuery.data?.rows ?? [], [transparencyQuery.data]);

  const treeQuery = useQuery({ queryKey: queryKeys.hierarchyTree(), queryFn: fetchFullTree });
  const treeNodes = useMemo<NodeDTO[]>(() => treeQuery.data ?? [], [treeQuery.data]);

  const flatNodes = useMemo(() => flattenTree(treeNodes), [treeNodes]);
  const nodesById = useMemo(() => new Map(flatNodes.map((n) => [n.id, n])), [flatNodes]);
  const nodeOrder = useMemo(() => {
    const order = dfsOrder(treeNodes);
    return new Map(order.map((id, i) => [id, i]));
  }, [treeNodes]);

  const soldierRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const oa = a.node_id ? nodeOrder.get(a.node_id) ?? 9999 : 9999;
      const ob = b.node_id ? nodeOrder.get(b.node_id) ?? 9999 : 9999;
      if (oa !== ob) return oa - ob;
      return a.full_name.localeCompare(b.full_name, "he");
    });
  }, [rows, nodeOrder]);

  const subRows = useMemo((): SubRow[] => {
    const result: SubRow[] = [];
    const sortedNodes = [...flatNodes].sort(
      (a, b) => a.path_ids.length - b.path_ids.length || a.name.localeCompare(b.name, "he"),
    );
    const avg = (vals: number[]) => vals.reduce((a, b) => a + b, 0) / vals.length;
    for (const node of sortedNodes) {
      const nodeRows = rows.filter((r) => r.node_id != null && nodesById.get(r.node_id)?.path_ids.includes(node.id));
      if (nodeRows.length === 0) continue;
      const activeRows = nodeRows.filter((r) => !r.is_globally_exempted);
      result.push({
        node_id: node.id,
        node_name: node.name,
        count: nodeRows.length,
        active_pct: Math.round((activeRows.length / nodeRows.length) * 100),
        avg_active_days: Math.round(avg(nodeRows.map((r) => r.active_days))),
        avg_cumulative: avg(nodeRows.map((r) => Number(r.cumulative_score))),
        avg_cumulative_active: activeRows.length > 0 ? avg(activeRows.map((r) => Number(r.cumulative_score))) : 0,
        total_score_per_day: nodeRows.reduce((s, r) => s + Number(r.score_per_day), 0),
        avg_normalised: avg(nodeRows.map((r) => Number(r.normalised_score))),
      });
    }
    return result;
  }, [flatNodes, nodesById, rows]);

  const soldierCols: ColDef<TransparencyRow>[] = [
    {
      id: "unit_path", header: "יחידה / תת-יחידה",
      cell: (r) => r.node_id ? nodePath(r.node_id, nodesById) : "—",
      sortValue: (r) => r.node_id ? nodePath(r.node_id, nodesById) : "",
    },
    { id: "name", header: "שם", cell: (r) => r.full_name, sortValue: (r) => r.full_name, filterValue: (r) => r.full_name },
    { id: "unit", header: "יחידה", cell: (r) => r.node_name ?? "—", sortValue: (r) => r.node_name ?? "" },
    { id: "enrolled_at", header: "תאריך הצטרפות", cell: (r) => r.enrolled_at, sortValue: (r) => r.enrolled_at },
    { id: "active_days", header: "ימים פעילים", cell: (r) => r.active_days, sortValue: (r) => r.active_days },
    { id: "rank", header: "דרגה", cell: (r) => r.rank ?? "—", sortValue: (r) => r.rank ?? "" },
    { id: "shift_count", header: "כמות משמרות", cell: (r) => r.shift_count, sortValue: (r) => r.shift_count },
    {
      id: "cumulative", header: "ניקוד מצטבר",
      cell: (r) => { const n = Number(r.cumulative_score); return isNaN(n) ? r.cumulative_score : n.toFixed(3); },
      sortValue: (r) => Number(r.cumulative_score),
    },
    {
      id: "score_per_day", header: "ניקוד ליום",
      cell: (r) => { const n = Number(r.score_per_day); return isNaN(n) ? r.score_per_day : n.toFixed(3); },
      sortValue: (r) => Number(r.score_per_day),
    },
    {
      id: "normalised", header: "ניקוד מנורמל",
      cell: (r) => { const n = Number(r.normalised_score); return isNaN(n) ? r.normalised_score : n.toFixed(3); },
      sortValue: (r) => Number(r.normalised_score),
    },
  ];

  const subCols: ColDef<SubRow>[] = [
    { id: "name", header: "יחידה", cell: (r) => r.node_name, sortValue: (r) => r.node_name },
    { id: "count", header: "כמות חיילים", cell: (r) => r.count, sortValue: (r) => r.count },
    { id: "active_pct", header: "חיילים פעילים (%)", cell: (r) => r.active_pct, sortValue: (r) => r.active_pct },
    { id: "avg_active_days", header: "ממוצע ימים פעילים", cell: (r) => r.avg_active_days, sortValue: (r) => r.avg_active_days },
    { id: "avg_cumulative", header: "ממוצע ניקוד לחייל", cell: (r) => r.avg_cumulative.toFixed(3), exportValue: (r) => r.avg_cumulative, sortValue: (r) => r.avg_cumulative },
    { id: "avg_cumulative_active", header: "ממוצע ניקוד לחייל פעיל", cell: (r) => r.avg_cumulative_active.toFixed(3), exportValue: (r) => r.avg_cumulative_active, sortValue: (r) => r.avg_cumulative_active },
    { id: "total_score_per_day", header: "ניקוד ליום (מסגרת)", cell: (r) => r.total_score_per_day.toFixed(3), exportValue: (r) => r.total_score_per_day, sortValue: (r) => r.total_score_per_day },
    { id: "avg_normalised", header: "ניקוד מנורמל ממוצע", cell: (r) => r.avg_normalised.toFixed(3), exportValue: (r) => r.avg_normalised, sortValue: (r) => r.avg_normalised },
  ];

  function toggle(key: string) {
    setChecked((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  const allChecked = ALL_KEYS.every((key) => checked[key]);

  function toggleAll() {
    const next = !allChecked;
    setChecked(Object.fromEntries(ALL_KEYS.map((key) => [key, next])));
  }

  async function handleExport() {
    const wb = XLSX.utils.book_new();

    if (checked.transparency) {
      const header = soldierCols.map((c) => c.header);
      const body = soldierRows.map((row) => soldierCols.map((c) => exportValueOf(c, row)));
      XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([header, ...body]), "transparency");
    }
    if (checked.sub_units) {
      const header = subCols.map((c) => c.header);
      const body = subRows.map((row) => subCols.map((c) => exportValueOf(c, row)));
      XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([header, ...body]), "sub_units");
    }

    const configSheets = CONFIG_SHEET_OPTIONS.filter((o) => checked[o.key]).map((o) => o.key);
    if (configSheets.length > 0) {
      const resp = await fetch(`/api/config/export?sheets=${configSheets.join(",")}`, {
        headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
      });
      const buf = await resp.arrayBuffer();
      const configWb = XLSX.read(buf, { type: "array" });
      for (const name of configWb.SheetNames) {
        XLSX.utils.book_append_sheet(wb, configWb.Sheets[name], name);
      }
    }

    const dataSheets = DATA_SHEET_OPTIONS.filter((o) => checked[o.key]).map((o) => o.key);
    if (dataSheets.length > 0) {
      const resp = await fetch(`/api/import/export?sheets=${dataSheets.join(",")}`, {
        headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
      });
      const buf = await resp.arrayBuffer();
      const dataWb = XLSX.read(buf, { type: "array" });
      for (const name of dataWb.SheetNames) {
        XLSX.utils.book_append_sheet(wb, dataWb.Sheets[name], name);
      }
    }

    if (wb.SheetNames.length > 0) {
      XLSX.writeFile(wb, "export.xlsx");
    }
  }

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4">
        <h2 className="text-xl font-semibold">{t("nav.planning_export")}</h2>
        <div className="space-y-2">
          <label className="flex items-center gap-2 font-medium border-b pb-2 dark:border-gray-700">
            <input type="checkbox" checked={allChecked} onChange={toggleAll} />
            בחר הכל
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={!!checked.transparency} onChange={() => toggle("transparency")} />
            {t("export.transparency_title")}
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={!!checked.sub_units} onChange={() => toggle("sub_units")} />
            {t("export.sub_units_title")}
          </label>
          {CONFIG_SHEET_OPTIONS.map((o) => (
            <label key={o.key} className="flex items-center gap-2">
              <input type="checkbox" checked={!!checked[o.key]} onChange={() => toggle(o.key)} />
              {o.label}
            </label>
          ))}
          {DATA_SHEET_OPTIONS.map((o) => (
            <label key={o.key} className="flex items-center gap-2">
              <input type="checkbox" checked={!!checked[o.key]} onChange={() => toggle(o.key)} />
              {o.label}
            </label>
          ))}
        </div>
        <button
          type="button"
          className="bg-indigo-600 text-white px-6 py-2 rounded font-medium hover:bg-indigo-700"
          onClick={() => void handleExport()}
        >
          ייצוא
        </button>
      </section>
    </Layout>
  );
}
