import Fuse from "fuse.js";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Combobox, { type ComboboxItem } from "../components/Combobox";
import DateInput from "../components/DateInput";
import { isDateRangeValid } from "../utils/formatDate";
import Layout from "../components/Layout";
import DutyTypeFormModal from "../components/DutyTypeFormModal";
import AddRootNodeDialog from "../components/AddRootNodeDialog";
import ImportRowFieldsModal from "../components/ImportRowFieldsModal";
import ImportRowDetailModal, { type DetailField } from "../components/ImportRowDetailModal";
import { queryKeys } from "../queryKeys";
import {
  type ConfirmSessionResult,
  type RowBase,
  type Selections,
  type ShiftTemplateRow,
  type AssignmentRow,
  type DutyLocationRow,
  type HierarchyImportRow,
  type DutyTypeImportRow,
  type ExemptionTypeImportRow,
  type SystemSettingImportRow,
  type BugReportImportRow,
  type PersonalConstraintImportRow,
  type SoldierFieldUpdateImportRow,
  type SoldierEnrollmentRequestImportRow,
  type SoldierExemptionImportRow,
  type ExemptionRequestImportRow,
  type SwapRequestImportRow,
  type RangeLocationImportRow,
  type RangeEventImportRow,
  type RangeAssignmentImportRow,
  type SoldierRangeQualificationImportRow,
  type RangeExcusalRequestImportRow,
  getSession,
  reparseSession,
  saveSelections,
  confirmSession,
  listDutyTypesForImport,
  listNodesForImport,
} from "../api/importSessions";
import { translateApiError } from "../utils/translateApiError";

// Range sheet row types used in content blocks (tasks 3-7)
// @ts-ignore TS6196: type is intentionally defined but unused here; will be used in tasks 3-7
type RangeSheetRow =
  | RangeLocationImportRow
  | RangeEventImportRow
  | RangeAssignmentImportRow
  | SoldierRangeQualificationImportRow
  | RangeExcusalRequestImportRow;

type ActionValue = RowBase["action"];

const ACTION_LABEL: Record<ActionValue, string> = {
  new: "חדש",
  update: "עדכון",
  error: "שגיאה",
  out_of_scope: "מחוץ לטווח",
  skip: "דלג",
};

const ACTION_CHIP: Record<ActionValue, string> = {
  new: "bg-green-100 text-green-700",
  update: "bg-blue-100 text-blue-700",
  error: "bg-red-100 text-red-700",
  out_of_scope: "bg-orange-100 text-orange-700",
  skip: "bg-gray-100 text-gray-500",
};

type TabKey =
  | "soldiers"
  | "duty_shifts"
  | "shift_templates"
  | "assignments"
  | "duty_locations"
  | "hierarchy"
  | "duty_types"
  | "exemption_types"
  | "system_settings"
  | "bug_reports"
  | "personal_constraints"
  | "soldier_field_updates"
  | "soldier_enrollment_requests"
  | "soldier_exemptions"
  | "exemption_requests"
  | "swap_requests"
  | "range_locations"
  | "range_events"
  | "range_assignments"
  | "soldier_range_qualifications"
  | "range_excusal_requests";

type GroupKey =
  | "soldiers"
  | "duty_shifts"
  | "shift_templates"
  | "assignments"
  | "duty_locations"
  | "hierarchy"
  | "duty_types"
  | "exemption_types"
  | "system_settings"
  | "bug_reports"
  | "personal_constraints"
  | "soldier_field_updates"
  | "soldier_enrollment_requests"
  | "soldier_exemptions"
  | "exemption_requests"
  | "swap_requests"
  | "range_locations"
  | "range_events"
  | "range_assignments"
  | "soldier_range_qualifications"
  | "range_excusal_requests";

function StatusChip({
  action,
  errors,
  warnings,
}: {
  action: ActionValue;
  errors?: string[];
  warnings?: string[];
}) {
  return (
    <div className="space-y-0.5">
      <span
        className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_CHIP[action]}`}
      >
        {ACTION_LABEL[action]}
      </span>
      {errors && errors.length > 0 && (
        <ul className="text-red-600 text-xs list-none">
          {errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
      {warnings && warnings.length > 0 && (
        <ul className="text-yellow-600 text-xs list-none">
          {warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface LookupItem {
  id: string;
  name: string;
}

interface LookupNode {
  id: string;
  name: string;
  parent_id: string | null;
}

function buildPickerItems(
  unresolvedName: string,
  candidates: { id: string; name: string }[],
  sortedItems: ComboboxItem[],
): ComboboxItem[] {
  const fuse = new Fuse(candidates, { keys: ["name"], threshold: 0.6, includeScore: true });
  const top5 = fuse.search(unresolvedName).slice(0, 5).map((r) => r.item);
  const top5Ids = new Set(top5.map((c) => c.id));
  return [
    ...top5.map((c) => ({ id: c.id, name: c.name, group: "הצעות קרובות" })),
    ...sortedItems.filter((c) => !top5Ids.has(c.id)),
  ];
}

const EMPTY_DUTY_TYPES: LookupItem[] = [];
const EMPTY_NODES: LookupNode[] = [];

interface PendingPick {
  pickedId: string;
  kind: "duty_type" | "hierarchy_node";
  excelName: string;
  rowKey: string;
  sameNameCount: number;
}

function PendingPickBanner({
  pick,
  onApplyAll,
  onApplyRow,
  onCancel,
}: {
  pick: PendingPick;
  onApplyAll: () => void;
  onApplyRow: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="mt-1 p-2 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-700 rounded text-xs space-y-1">
      <p>
        יש עוד {pick.sameNameCount - 1} שורות עם השם &ldquo;{pick.excelName}&rdquo;. להחיל על כולן?
      </p>
      <div className="flex gap-3">
        <button className="text-indigo-600 hover:underline" onClick={onApplyAll}>
          החל על כולן
        </button>
        <button className="text-indigo-600 hover:underline" onClick={onApplyRow}>
          רק שורה זו
        </button>
        <button className="text-gray-500 hover:underline" onClick={onCancel}>
          ביטול
        </button>
      </div>
    </div>
  );
}

export default function ImportSessionReviewPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("soldiers");
  const [selections, setSelections] = useState<Selections>({});
  const [confirming, setConfirming] = useState(false);
  const [confirmResult, setConfirmResult] = useState<ConfirmSessionResult | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  // dialog state
  const [dutyTypeContext, setDutyTypeContext] = useState<{
    unresolvedName: string;
  } | null>(null);
  const [nodeCreateContext, setNodeCreateContext] = useState<{
    unresolvedName: string;
  } | null>(null);
  const [dutyTypeFieldsRow, setDutyTypeFieldsRow] = useState<DutyTypeImportRow | null>(null);
  const [exemptionTypeFieldsRow, setExemptionTypeFieldsRow] = useState<ExemptionTypeImportRow | null>(null);
  const [shiftTemplateFieldsRow, setShiftTemplateFieldsRow] = useState<ShiftTemplateRow | null>(null);
  const [detailModal, setDetailModal] = useState<{ title: string; fields: DetailField[] } | null>(null);

  // lookup data
  const dutyTypesQuery = useQuery({
    queryKey: queryKeys.importDutyTypesForImport(),
    queryFn: listDutyTypesForImport,
  });
  const nodesQuery = useQuery({
    queryKey: queryKeys.importNodesForImport(),
    queryFn: listNodesForImport,
  });
  const allDutyTypes: LookupItem[] = dutyTypesQuery.data ?? EMPTY_DUTY_TYPES;
  const allNodes: LookupNode[] = nodesQuery.data ?? EMPTY_NODES;
  const [pendingPick, setPendingPick] = useState<PendingPick | null>(null);

  const sortedNodeItems = useMemo<ComboboxItem[]>(() => {
    const byParent = new Map<string | null, LookupNode[]>();
    for (const n of allNodes) {
      const key = n.parent_id ?? null;
      byParent.set(key, [...(byParent.get(key) ?? []), n]);
    }
    const result: ComboboxItem[] = [];
    function walk(parentId: string | null, depth: number) {
      for (const n of byParent.get(parentId) ?? []) {
        result.push({ id: n.id, name: n.name, depth });
        walk(n.id, depth + 1);
      }
    }
    walk(null, 0);
    return result;
  }, [allNodes]);

  const sortedDutyTypeItems = useMemo<ComboboxItem[]>(
    () => allDutyTypes.map((dt) => ({ id: dt.id, name: dt.name })),
    [allDutyTypes],
  );

  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const sessionQuery = useQuery({
    queryKey: queryKeys.importSessionDetail(id ?? ""),
    queryFn: () => getSession(id as string),
    enabled: !!id,
  });
  const detail = sessionQuery.data ?? null;
  const loading = sessionQuery.isLoading;

  // selections mirrors the query result but is then edited locally (row
  // actions / field overrides) before the debounced save round-trip, so it
  // stays a useState fed by an effect rather than reading straight from the
  // query on every render (same pattern as SystemSettingsPage's draft).
  useEffect(() => {
    if (detail) setSelections(detail.user_selections ?? {});
  }, [detail]);

  const error = sessionQuery.isError
    ? "שגיאה בטעינת פרטי הייבוא"
    : dutyTypesQuery.isError || nodesQuery.isError
      ? "שגיאה בטעינת נתוני בחירה"
      : actionError;

  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, []);

  // Resync any open field-edit modal's captured row snapshot to the live
  // parsed_state after a background reparse (e.g. triggered by an inline
  // field edit on the same row while the modal is open), so the modal
  // doesn't keep showing stale data. Matched by `row` (stable row identity).
  const dutyTypesForSync = detail?.parsed_state.duty_types;
  const prevDutyTypesForSyncRef = useRef(dutyTypesForSync);
  useEffect(() => {
    // Only resync when the live array itself has genuinely changed (a real
    // background reparse), not merely because dutyTypeFieldsRow changed for
    // its own reasons (e.g. the modal's own optimistic local edit echo) —
    // otherwise this effect would revert the user's own in-progress edit
    // before the debounced save/reparse round-trip completes.
    if (prevDutyTypesForSyncRef.current === dutyTypesForSync) return;
    prevDutyTypesForSyncRef.current = dutyTypesForSync;
    if (!dutyTypeFieldsRow || !dutyTypesForSync) return;
    const fresh = dutyTypesForSync.find((r) => r.row === dutyTypeFieldsRow.row);
    if (fresh) {
      setDutyTypeFieldsRow(fresh);
    }
  }, [dutyTypesForSync, dutyTypeFieldsRow]);

  const exemptionTypesForSync = detail?.parsed_state.exemption_types;
  const prevExemptionTypesForSyncRef = useRef(exemptionTypesForSync);
  useEffect(() => {
    // See comment above the duty_types resync effect for why this guards
    // on the ref rather than resyncing on every dependency-array change.
    if (prevExemptionTypesForSyncRef.current === exemptionTypesForSync) return;
    prevExemptionTypesForSyncRef.current = exemptionTypesForSync;
    if (!exemptionTypeFieldsRow || !exemptionTypesForSync) return;
    const fresh = exemptionTypesForSync.find((r) => r.row === exemptionTypeFieldsRow.row);
    if (fresh) {
      setExemptionTypeFieldsRow(fresh);
    }
  }, [exemptionTypesForSync, exemptionTypeFieldsRow]);

  const shiftTemplatesForSync = detail?.parsed_state.shift_templates;
  const prevShiftTemplatesForSyncRef = useRef(shiftTemplatesForSync);
  useEffect(() => {
    // See comment above the duty_types resync effect for why this guards
    // on the ref rather than resyncing on every dependency-array change.
    if (prevShiftTemplatesForSyncRef.current === shiftTemplatesForSync) return;
    prevShiftTemplatesForSyncRef.current = shiftTemplatesForSync;
    if (!shiftTemplateFieldsRow || !shiftTemplatesForSync) return;
    const fresh = shiftTemplatesForSync.find((r) => r.row === shiftTemplateFieldsRow.row);
    if (fresh) {
      setShiftTemplateFieldsRow(fresh);
    }
  }, [shiftTemplatesForSync, shiftTemplateFieldsRow]);

  const readOnly = detail ? detail.status !== "draft" : true;

  function setRowAction(group: GroupKey, row: number, value: string) {
    if (!id) return;
    setSelections((prev) => {
      const next = {
        ...prev,
        [group]: { ...(prev[group] ?? {}), [String(row)]: value },
      };
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        void saveSelections(id, next);
      }, 500);
      return next;
    });
  }

  function setFieldOverride(
    group: string,
    row: number,
    field: string,
    value: unknown,
  ) {
    if (!id) return;
    setSelections((prev) => {
      const fo = prev._field_overrides ?? {};
      const groupOverrides = (fo as Record<string, Record<string, Record<string, unknown>>>)[group] ?? {};
      const rowOverrides = groupOverrides[String(row)] ?? {};
      const next = {
        ...prev,
        _field_overrides: {
          ...fo,
          [group]: {
            ...groupOverrides,
            [String(row)]: { ...rowOverrides, [field]: value },
          },
        },
      };
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        void saveSelections(id, next).then(() => handleReparse());
      }, 500);
      return next;
    });
  }

  async function handleReparse() {
    if (!id) return;
    try {
      const result = await reparseSession(id);
      queryClient.setQueryData(queryKeys.importSessionDetail(id), result);
      setSelections(result.user_selections ?? {});
    } catch {
      setActionError("שגיאה ברענון הנתונים");
    }
  }

  async function applyMapping(scope: "all" | "row", pick: PendingPick) {
    setPendingPick(null);
    if (!id) return;
    const nm = selections._name_mappings ?? {};
    const kindKey = pick.kind === "duty_type" ? "duty_type" : "hierarchy_node";
    const kindEntry = nm[kindKey] ?? {};
    let next: Selections;
    if (scope === "all") {
      next = {
        ...selections,
        _name_mappings: {
          ...nm,
          [kindKey]: {
            ...kindEntry,
            by_name: { ...(kindEntry.by_name ?? {}), [pick.excelName]: pick.pickedId },
          },
        },
      };
    } else {
      next = {
        ...selections,
        _name_mappings: {
          ...nm,
          [kindKey]: {
            ...kindEntry,
            by_row: { ...(kindEntry.by_row ?? {}), [pick.rowKey]: pick.pickedId },
          },
        },
      };
    }
    setSelections(next);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    await saveSelections(id, next);
    await handleReparse();
  }

  function handlePick(
    kind: "duty_type" | "hierarchy_node",
    excelName: string,
    rowKey: string,
    pickedId: string,
  ) {
    if (!detail) return;
    const { soldiers, duty_shifts, shift_templates } = detail.parsed_state;
    let sameNameCount = 0;
    if (kind === "hierarchy_node") {
      sameNameCount += soldiers.filter(
        (r) => !r.hierarchy_node_id && r.hierarchy_node_name === excelName,
      ).length;
      sameNameCount += duty_shifts.reduce(
        (acc, r) =>
          acc + r.node_quotas.filter((q) => !q.resolved && q.node_name === excelName).length,
        0,
      );
    } else {
      sameNameCount += duty_shifts.filter(
        (r) => !r.resolved_duty_type_id && r.duty_type_name === excelName,
      ).length;
      sameNameCount += shift_templates.filter(
        (r) => !r.resolved_duty_type_id && r.duty_type_name === excelName,
      ).length;
    }
    if (sameNameCount <= 1) {
      void applyMapping("row", { pickedId, kind, excelName, rowKey, sameNameCount });
    } else {
      setPendingPick({ pickedId, kind, excelName, rowKey, sameNameCount });
    }
  }

  async function handleConfirm() {
    if (!id) return;
    setConfirming(true);
    setConfirmError(null);
    try {
      const result = await confirmSession(id);
      setConfirmResult(result);
      await queryClient.invalidateQueries({ queryKey: queryKeys.importSessionDetail(id) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.importSessionsList() });
    } catch (err: unknown) {
      setConfirmError(translateApiError(err, t, "שגיאה באישור הייבוא"));
    } finally {
      setConfirming(false);
    }
  }

  function currentSelection(group: GroupKey, row: RowBase): string {
    return (selections[group] as Record<string, string> | undefined)?.[String(row.row)] ?? row.action;
  }

  if (loading || !detail) {
    return (
      <Layout>
        <div className="max-w-5xl mx-auto p-4" dir="rtl">
          {error && (
            <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
              {error}
            </div>
          )}
          {loading && <p className="text-gray-400 text-sm">טוען...</p>}
        </div>
      </Layout>
    );
  }

  const {
    soldiers,
    duty_shifts,
    shift_templates,
    assignments,
    duty_locations,
    hierarchy,
    duty_types,
    exemption_types,
    system_settings,
    bug_reports,
    personal_constraints,
    soldier_field_updates,
    soldier_enrollment_requests,
    soldier_exemptions,
    exemption_requests,
    swap_requests,
    range_locations,
    range_events,
    range_assignments,
    soldier_range_qualifications,
    range_excusal_requests,
  } = detail.parsed_state;

  return (
    <Layout>
      <div className="max-w-5xl mx-auto space-y-4 p-4" dir="rtl">
        <h1 className="text-xl font-semibold">{detail.filename}</h1>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="flex gap-2 border-b dark:border-gray-700">
          {(
            [
              ["soldiers", `חיילים (${soldiers.length})`],
              ["duty_shifts", `משמרות (${duty_shifts.length})`],
              ["shift_templates", `תבניות (${shift_templates.length})`],
              ["assignments", `שיבוצים (${assignments.length})`],
              ["duty_locations", `מיקומי תורנות (${duty_locations.length})`],
              ["hierarchy", `היררכיה (${hierarchy.length})`],
              ["duty_types", `סוגי תורנות (${duty_types.length})`],
              ["exemption_types", `פטורים (${exemption_types.length})`],
              ["system_settings", `הגדרות מערכת (${system_settings.length})`],
              ["bug_reports", `דוחות תקלות (${bug_reports.length})`],
              ["personal_constraints", `אילוצים אישיים (${personal_constraints.length})`],
              ["soldier_field_updates", `עדכוני שדות (${soldier_field_updates.length})`],
              ["soldier_enrollment_requests", `בקשות שיבוץ (${soldier_enrollment_requests.length})`],
              ["soldier_exemptions", `פטורי חיילים (${soldier_exemptions.length})`],
              ["exemption_requests", `בקשות פטור (${exemption_requests.length})`],
              ["swap_requests", `בקשות החלפה (${swap_requests.length})`],
              ["range_locations", `מיקומי מטווח (${range_locations.length})`],
              ["range_events", `מטווחים (${range_events.length})`],
              ["range_assignments", `שיבוצי מטווח (${range_assignments.length})`],
              ["soldier_range_qualifications", `כשירויות מטווח (${soldier_range_qualifications.length})`],
              ["range_excusal_requests", `בקשות פטור ממטווח (${range_excusal_requests.length})`],
            ] as [TabKey, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              className={`px-3 py-2 text-sm font-medium ${
                tab === key
                  ? "border-b-2 border-indigo-600 text-indigo-600"
                  : "text-gray-500"
              }`}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "soldiers" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">מ&quot;א</th>
                  <th className="text-right p-3">דרגה</th>
                  <th className="text-right p-3">מגדר</th>
                  <th className="text-right p-3">קצין</th>
                  <th className="text-right p-3">טלפון</th>
                  <th className="text-right p-3">אימייל</th>
                  <th className="text-right p-3">תאריך גיוס</th>
                  <th className="text-right p-3">יחידה</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {soldiers.map((row) => {
                  const canToggle =
                    row.action !== "error" && row.action !== "out_of_scope";
                  const unresolvedNode =
                    !row.hierarchy_node_id && row.hierarchy_node_name;
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        {readOnly ? row.full_name : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.full_name}
                            onBlur={(e) => setFieldOverride("soldiers", row.row, "full_name", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">{row.personal_number}</td>
                      <td className="p-3">
                        {readOnly ? row.rank ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-20 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.rank ?? ""}
                            onBlur={(e) => setFieldOverride("soldiers", row.row, "rank", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.gender ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.gender ?? ""}
                            onBlur={(e) => setFieldOverride("soldiers", row.row, "gender", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.is_officer === null ? "—" : row.is_officer ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.is_officer ?? false}
                            onChange={(e) => setFieldOverride("soldiers", row.row, "is_officer", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.phone ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.phone ?? ""}
                            onBlur={(e) => setFieldOverride("soldiers", row.row, "phone", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.email ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.email ?? ""}
                            onBlur={(e) => setFieldOverride("soldiers", row.row, "email", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.enlistment_date ?? "—" : (
                          <DateInput
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.enlistment_date ?? ""}
                            onBlur={(iso) => setFieldOverride("soldiers", row.row, "enlistment_date", iso || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {unresolvedNode ? (
                          <div className="flex flex-col gap-1">
                            <span className="text-red-600 text-xs font-medium">
                              {row.hierarchy_node_name}
                            </span>
                            {!readOnly && (
                              <>
                                <Combobox
                                  items={buildPickerItems(
                                    row.hierarchy_node_name ?? "",
                                    allNodes,
                                    sortedNodeItems,
                                  )}
                                  value=""
                                  onChange={(pickedId) => {
                                    if (pickedId)
                                      handlePick(
                                        "hierarchy_node",
                                        row.hierarchy_node_name ?? "",
                                        `soldiers:${row.row}`,
                                        pickedId,
                                      );
                                  }}
                                />
                                <button
                                  className="text-indigo-600 hover:underline text-xs self-start"
                                  onClick={() =>
                                    setNodeCreateContext({
                                      unresolvedName: row.hierarchy_node_name ?? "",
                                    })
                                  }
                                >
                                  צור יחידה
                                </button>
                              </>
                            )}
                            {pendingPick?.rowKey === `soldiers:${row.row}` &&
                              pendingPick.kind === "hierarchy_node" && (
                                <PendingPickBanner
                                  pick={pendingPick}
                                  onApplyAll={() => void applyMapping("all", pendingPick)}
                                  onApplyRow={() => void applyMapping("row", pendingPick)}
                                  onCancel={() => setPendingPick(null)}
                                />
                              )}
                          </div>
                        ) : (
                          row.hierarchy_node_name
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "personal_number", label: "מספר אישי", value: row.personal_number },
                                { key: "full_name", label: "שם מלא", value: row.full_name, editable: { type: "text", onChange: (v) => setFieldOverride("soldiers", row.row, "full_name", v) } },
                                { key: "rank", label: "דרגה", value: row.rank, editable: { type: "text", onChange: (v) => setFieldOverride("soldiers", row.row, "rank", v) } },
                                { key: "gender", label: "מגדר", value: row.gender, editable: { type: "text", onChange: (v) => setFieldOverride("soldiers", row.row, "gender", v) } },
                                { key: "is_officer", label: "קצין", value: row.is_officer, editable: { type: "checkbox", onChange: (v) => setFieldOverride("soldiers", row.row, "is_officer", v) } },
                                { key: "phone", label: "טלפון", value: row.phone, editable: { type: "text", onChange: (v) => setFieldOverride("soldiers", row.row, "phone", v) } },
                                { key: "email", label: "אימייל", value: row.email, editable: { type: "text", onChange: (v) => setFieldOverride("soldiers", row.row, "email", v) } },
                                { key: "hierarchy_node_name", label: "יחידה", value: row.hierarchy_node_name },
                                { key: "enrolled_at", label: "תאריך שיבוץ", value: row.enrolled_at, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "enrolled_at", v) } },
                                { key: "enlistment_date", label: "תאריך גיוס", value: row.enlistment_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "enlistment_date", v) } },
                                { key: "is_career", label: "קבע", value: row.is_career, editable: { type: "checkbox", onChange: (v) => setFieldOverride("soldiers", row.row, "is_career", v) } },
                                { key: "next_rank_date", label: "תאריך דרגה הבאה", value: row.next_rank_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "next_rank_date", v) } },
                                { key: "bahad1_graduate", label: "בוגר בה\"ד 1", value: row.bahad1_graduate, editable: { type: "checkbox", onChange: (v) => setFieldOverride("soldiers", row.row, "bahad1_graduate", v) } },
                                { key: "has_military_driving_license", label: "רישיון נהיגה צבאי", value: row.has_military_driving_license, editable: { type: "checkbox", onChange: (v) => setFieldOverride("soldiers", row.row, "has_military_driving_license", v) } },
                                { key: "military_driving_license_expiry", label: "תוקף רישיון נהיגה", value: row.military_driving_license_expiry, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "military_driving_license_expiry", v) } },
                                { key: "mandatory_end_date", label: "תאריך סיום חובה", value: row.mandatory_end_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "mandatory_end_date", v) } },
                                { key: "discharge_date", label: "תאריך שחרור", value: row.discharge_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "discharge_date", v) } },
                                { key: "last_mitvahim_date", label: "תאריך מתו\"ם אחרון", value: row.last_mitvahim_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "last_mitvahim_date", v) } },
                                { key: "last_alal_date", label: "תאריך אל\"ל אחרון", value: row.last_alal_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "last_alal_date", v) } },
                                { key: "left_at", label: "תאריך עזיבה", value: row.left_at, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "left_at", v) } },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                                { key: "warnings", label: "אזהרות", value: row.warnings },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} warnings={row.warnings} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("soldiers", row)}
                              onChange={(e) =>
                                setRowAction("soldiers", row.row, e.target.value)
                              }
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && (
                                <option value="skip">דלג</option>
                              )}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "duty_shifts" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">סוג תורנות</th>
                  <th className="text-right p-3">מיקום</th>
                  <th className="text-right p-3">תאריך התחלה</th>
                  <th className="text-right p-3">תאריך סיום</th>
                  <th className="text-right p-3">שעת התחלה</th>
                  <th className="text-right p-3">שעת סיום</th>
                  <th className="text-right p-3">נדרש</th>
                  <th className="text-right p-3">הערות</th>
                  <th className="text-right p-3">מכסות יחידה</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {duty_shifts.map((row) => {
                  const canToggle =
                    row.action !== "error" && row.action !== "out_of_scope";
                  const unresolvedType = !row.resolved_duty_type_id;
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        {unresolvedType ? (
                          <div className="flex flex-col gap-1">
                            <span className="text-red-600 text-xs font-medium">
                              {row.duty_type_name}
                            </span>
                            {!readOnly && (
                              <>
                                <Combobox
                                  items={buildPickerItems(
                                    row.duty_type_name,
                                    allDutyTypes,
                                    sortedDutyTypeItems,
                                  )}
                                  value=""
                                  onChange={(pickedId) => {
                                    if (pickedId)
                                      handlePick(
                                        "duty_type",
                                        row.duty_type_name,
                                        `duty_shifts:${row.row}`,
                                        pickedId,
                                      );
                                  }}
                                />
                                <button
                                  className="text-indigo-600 hover:underline text-xs self-start"
                                  onClick={() =>
                                    setDutyTypeContext({ unresolvedName: row.duty_type_name })
                                  }
                                >
                                  צור סוג תורנות
                                </button>
                              </>
                            )}
                            {pendingPick?.rowKey === `duty_shifts:${row.row}` &&
                              pendingPick.kind === "duty_type" && (
                                <PendingPickBanner
                                  pick={pendingPick}
                                  onApplyAll={() => void applyMapping("all", pendingPick)}
                                  onApplyRow={() => void applyMapping("row", pendingPick)}
                                  onCancel={() => setPendingPick(null)}
                                />
                              )}
                          </div>
                        ) : (
                          row.duty_type_name
                        )}
                      </td>
                      <td className="p-3">{row.duty_location_name}</td>
                      <td className="p-3">
                        {readOnly ? row.start_date : (
                          <DateInput
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_date}
                            max={row.end_date || undefined}
                            onBlur={(iso) => {
                              if (!isDateRangeValid(iso, row.end_date)) { alert(t("errors.date_range_invalid")); return; }
                              setFieldOverride("duty_shifts", row.row, "start_date", iso);
                            }}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_date : (
                          <DateInput
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_date}
                            min={row.start_date || undefined}
                            onBlur={(iso) => {
                              if (!isDateRangeValid(row.start_date, iso)) { alert(t("errors.date_range_invalid")); return; }
                              setFieldOverride("duty_shifts", row.row, "end_date", iso);
                            }}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.start_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_time ?? ""}
                            onBlur={(e) => setFieldOverride("duty_shifts", row.row, "start_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_time ?? ""}
                            onBlur={(e) => setFieldOverride("duty_shifts", row.row, "end_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.required_count : (
                          <input
                            type="number"
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.required_count}
                            onBlur={(e) => setFieldOverride("duty_shifts", row.row, "required_count", Number(e.target.value))}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.notes ?? "—" : (
                          <textarea
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.notes ?? ""}
                            onBlur={(e) => setFieldOverride("duty_shifts", row.row, "notes", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <div className="flex flex-col gap-1">
                          {row.node_quotas.map((q, i) => {
                            const quotaRowKey = `duty_shifts:${row.row}:${q.node_name}`;
                            return (
                              <div key={i} className="flex flex-col gap-1">
                                <div className="flex items-center gap-2">
                                  <span className={q.resolved ? "" : "text-red-600"}>
                                    {q.node_name}:{q.count}
                                  </span>
                                  {!q.resolved && !readOnly && (
                                    <>
                                      <Combobox
                                        items={buildPickerItems(
                                          q.node_name,
                                          allNodes,
                                          sortedNodeItems,
                                        )}
                                        value=""
                                        onChange={(pickedId) => {
                                          if (pickedId)
                                            handlePick(
                                              "hierarchy_node",
                                              q.node_name,
                                              quotaRowKey,
                                              pickedId,
                                            );
                                        }}
                                      />
                                      <button
                                        className="text-indigo-600 hover:underline text-xs"
                                        onClick={() =>
                                          setNodeCreateContext({ unresolvedName: q.node_name })
                                        }
                                      >
                                        צור
                                      </button>
                                    </>
                                  )}
                                </div>
                                {pendingPick?.rowKey === quotaRowKey &&
                                  pendingPick.kind === "hierarchy_node" && (
                                    <PendingPickBanner
                                      pick={pendingPick}
                                      onApplyAll={() => void applyMapping("all", pendingPick)}
                                      onApplyRow={() => void applyMapping("row", pendingPick)}
                                      onCancel={() => setPendingPick(null)}
                                    />
                                  )}
                              </div>
                            );
                          })}
                        </div>
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "duty_type_name", label: "סוג תורנות", value: row.duty_type_name },
                                { key: "resolved_duty_type_id", label: "מזהה סוג תורנות", value: row.resolved_duty_type_id },
                                { key: "duty_location_name", label: "מיקום", value: row.duty_location_name },
                                { key: "resolved_duty_location_id", label: "מזהה מיקום", value: row.resolved_duty_location_id },
                                { key: "start_date", label: "תאריך התחלה", value: row.start_date, editable: { type: "date", onChange: (v) => setFieldOverride("duty_shifts", row.row, "start_date", v) } },
                                { key: "end_date", label: "תאריך סיום", value: row.end_date, editable: { type: "date", onChange: (v) => setFieldOverride("duty_shifts", row.row, "end_date", v) } },
                                { key: "start_time", label: "שעת התחלה", value: row.start_time, editable: { type: "text", onChange: (v) => setFieldOverride("duty_shifts", row.row, "start_time", v) } },
                                { key: "end_time", label: "שעת סיום", value: row.end_time, editable: { type: "text", onChange: (v) => setFieldOverride("duty_shifts", row.row, "end_time", v) } },
                                { key: "required_count", label: "נדרש", value: row.required_count, editable: { type: "number", onChange: (v) => setFieldOverride("duty_shifts", row.row, "required_count", v) } },
                                { key: "notes", label: "הערות", value: row.notes, editable: { type: "textarea", onChange: (v) => setFieldOverride("duty_shifts", row.row, "notes", v) } },
                                { key: "node_quotas", label: "מכסות יחידה", value: row.node_quotas.map((q) => `${q.node_name}:${q.count}`) },
                                { key: "errors", label: "שגיאות", value: row.errors },
                                { key: "warnings", label: "אזהרות", value: row.warnings },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("duty_shifts", row)}
                              onChange={(e) =>
                                setRowAction(
                                  "duty_shifts",
                                  row.row,
                                  e.target.value,
                                )
                              }
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && (
                                <option value="skip">דלג</option>
                              )}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "shift_templates" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">סוג תורנות</th>
                  <th className="text-right p-3">מיקום</th>
                  <th className="text-right p-3">חזרתיות</th>
                  <th className="text-right p-3">ימים</th>
                  <th className="text-right p-3">שעת התחלה</th>
                  <th className="text-right p-3">שעת סיום</th>
                  <th className="text-right p-3">נדרש</th>
                  <th className="text-right p-3">גלגול אוטומטי</th>
                  <th className="text-right p-3">עד תאריך</th>
                  <th className="text-right p-3">משך (ימים)</th>
                  <th className="text-right p-3">הערות</th>
                  <th className="text-right p-3">יחידות זכאיות</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {shift_templates.map((row: ShiftTemplateRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  const unresolvedType = !row.resolved_duty_type_id;
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        {readOnly ? row.name : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.name}
                            onBlur={(e) => setFieldOverride("shift_templates", row.row, "name", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {unresolvedType ? (
                          <div className="flex flex-col gap-1">
                            <span className="text-red-600 text-xs font-medium">{row.duty_type_name}</span>
                            {!readOnly && (
                              <Combobox
                                items={buildPickerItems(row.duty_type_name, allDutyTypes, sortedDutyTypeItems)}
                                value=""
                                onChange={(pickedId) => {
                                  if (pickedId)
                                    handlePick("duty_type", row.duty_type_name, `shift_templates:${row.row}`, pickedId);
                                }}
                              />
                            )}
                            {pendingPick?.rowKey === `shift_templates:${row.row}` && pendingPick.kind === "duty_type" && (
                              <PendingPickBanner
                                pick={pendingPick}
                                onApplyAll={() => void applyMapping("all", pendingPick)}
                                onApplyRow={() => void applyMapping("row", pendingPick)}
                                onCancel={() => setPendingPick(null)}
                              />
                            )}
                          </div>
                        ) : (
                          row.duty_type_name
                        )}
                      </td>
                      <td className="p-3">{row.duty_location_name}</td>
                      <td className="p-3">
                        {readOnly ? row.recurrence_type : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.recurrence_type}
                            onChange={(e) => setFieldOverride("shift_templates", row.row, "recurrence_type", e.target.value)}
                          >
                            <option value="weekdays">א׳-ה׳</option>
                            <option value="daily">יומי</option>
                            <option value="weekly">שבועי (ימים נבחרים)</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        {row.recurrence_type !== "weekly" ? "—" : readOnly ? row.weekdays.join(",") : (
                          <div className="flex gap-1">
                            {[1, 2, 3, 4, 5, 6, 7].map((iso) => (
                              <button
                                key={iso}
                                type="button"
                                className={`w-6 h-6 rounded text-xs border ${
                                  row.weekdays.includes(iso)
                                    ? "bg-indigo-600 text-white border-indigo-600"
                                    : "bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 border-gray-300 dark:border-gray-600"
                                }`}
                                onClick={() => {
                                  const next = row.weekdays.includes(iso)
                                    ? row.weekdays.filter((d) => d !== iso)
                                    : [...row.weekdays, iso].sort((a, b) => a - b);
                                  setFieldOverride("shift_templates", row.row, "weekdays", next);
                                }}
                              >
                                {iso}
                              </button>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.start_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_time ?? ""}
                            onBlur={(e) => setFieldOverride("shift_templates", row.row, "start_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_time ?? ""}
                            onBlur={(e) => setFieldOverride("shift_templates", row.row, "end_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.required_count : (
                          <input
                            type="number"
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.required_count}
                            onBlur={(e) => setFieldOverride("shift_templates", row.row, "required_count", Number(e.target.value))}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.auto_roll ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.auto_roll}
                            onChange={(e) => setFieldOverride("shift_templates", row.row, "auto_roll", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {!row.auto_roll ? "—" : readOnly ? row.auto_roll_until ?? "—" : (
                          <DateInput
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.auto_roll_until ?? ""}
                            onBlur={(iso) => setFieldOverride("shift_templates", row.row, "auto_roll_until", iso || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.duration_days : (
                          <input
                            type="number"
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.duration_days}
                            onBlur={(e) => setFieldOverride("shift_templates", row.row, "duration_days", Number(e.target.value))}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.notes ?? "—" : (
                          <textarea
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.notes ?? ""}
                            onBlur={(e) => setFieldOverride("shift_templates", row.row, "notes", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {!readOnly && (
                          <button
                            type="button"
                            className="text-indigo-600 hover:underline text-xs"
                            onClick={() => setShiftTemplateFieldsRow(row)}
                          >
                            ערוך יחידות
                          </button>
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "name", label: "שם", value: row.name, editable: { type: "text", onChange: (v) => setFieldOverride("shift_templates", row.row, "name", v) } },
                                { key: "duty_type_name", label: "סוג תורנות", value: row.duty_type_name },
                                { key: "resolved_duty_type_id", label: "מזהה סוג תורנות", value: row.resolved_duty_type_id },
                                { key: "duty_location_name", label: "מיקום", value: row.duty_location_name },
                                { key: "resolved_duty_location_id", label: "מזהה מיקום", value: row.resolved_duty_location_id },
                                { key: "recurrence_type", label: "חזרתיות", value: row.recurrence_type, editable: { type: "text", onChange: (v) => setFieldOverride("shift_templates", row.row, "recurrence_type", v) } },
                                { key: "weekdays", label: "ימים", value: row.weekdays },
                                { key: "start_time", label: "שעת התחלה", value: row.start_time, editable: { type: "text", onChange: (v) => setFieldOverride("shift_templates", row.row, "start_time", v) } },
                                { key: "end_time", label: "שעת סיום", value: row.end_time, editable: { type: "text", onChange: (v) => setFieldOverride("shift_templates", row.row, "end_time", v) } },
                                { key: "required_count", label: "נדרש", value: row.required_count, editable: { type: "number", onChange: (v) => setFieldOverride("shift_templates", row.row, "required_count", v) } },
                                { key: "auto_roll", label: "גלגול אוטומטי", value: row.auto_roll, editable: { type: "checkbox", onChange: (v) => setFieldOverride("shift_templates", row.row, "auto_roll", v) } },
                                { key: "auto_roll_until", label: "עד תאריך", value: row.auto_roll_until, editable: { type: "date", onChange: (v) => setFieldOverride("shift_templates", row.row, "auto_roll_until", v) } },
                                { key: "duration_days", label: "משך (ימים)", value: row.duration_days, editable: { type: "number", onChange: (v) => setFieldOverride("shift_templates", row.row, "duration_days", v) } },
                                { key: "notes", label: "הערות", value: row.notes, editable: { type: "textarea", onChange: (v) => setFieldOverride("shift_templates", row.row, "notes", v) } },
                                { key: "resolved_eligible_node_ids", label: "יחידות זכאיות", value: row.resolved_eligible_node_ids },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                                { key: "warnings", label: "אזהרות", value: row.warnings },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("shift_templates", row)}
                              onChange={(e) => setRowAction("shift_templates", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "assignments" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">מ&quot;א</th>
                  <th className="text-right p-3">סוג תורנות</th>
                  <th className="text-right p-3">מיקום</th>
                  <th className="text-right p-3">תאריך התחלה</th>
                  <th className="text-right p-3">תאריך סיום</th>
                  <th className="text-right p-3">שעת התחלה</th>
                  <th className="text-right p-3">שעת סיום</th>
                  <th className="text-right p-3">רזרבה</th>
                  <th className="text-right p-3">הערות</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {assignments.map((row: AssignmentRow) => {
                  const canToggle =
                    row.action !== "error" && row.action !== "out_of_scope";
                  const unresolvedType = row.action === "error" && !!row.duty_type_name;
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.full_name}</td>
                      <td className="p-3">{row.personal_number}</td>
                      <td className="p-3">
                        {unresolvedType ? (
                          <div className="flex flex-col gap-1">
                            <span className="text-red-600 text-xs font-medium">{row.duty_type_name}</span>
                            {!readOnly && (
                              <Combobox
                                items={buildPickerItems(row.duty_type_name, allDutyTypes, sortedDutyTypeItems)}
                                value=""
                                onChange={(pickedId) => {
                                  if (pickedId)
                                    handlePick("duty_type", row.duty_type_name, `assignments:${row.row}`, pickedId);
                                }}
                              />
                            )}
                            {pendingPick?.rowKey === `assignments:${row.row}` && pendingPick.kind === "duty_type" && (
                              <PendingPickBanner
                                pick={pendingPick}
                                onApplyAll={() => void applyMapping("all", pendingPick)}
                                onApplyRow={() => void applyMapping("row", pendingPick)}
                                onCancel={() => setPendingPick(null)}
                              />
                            )}
                          </div>
                        ) : (
                          row.duty_type_name
                        )}
                      </td>
                      <td className="p-3">{row.duty_location_name}</td>
                      <td className="p-3">
                        {readOnly ? row.start_date : (
                          <DateInput
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_date}
                            max={row.end_date || undefined}
                            onBlur={(iso) => {
                              if (!isDateRangeValid(iso, row.end_date)) { alert(t("errors.date_range_invalid")); return; }
                              setFieldOverride("assignments", row.row, "start_date", iso);
                            }}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_date : (
                          <DateInput
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_date}
                            min={row.start_date || undefined}
                            onBlur={(iso) => {
                              if (!isDateRangeValid(row.start_date, iso)) { alert(t("errors.date_range_invalid")); return; }
                              setFieldOverride("assignments", row.row, "end_date", iso);
                            }}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.start_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_time ?? ""}
                            onBlur={(e) => setFieldOverride("assignments", row.row, "start_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_time ?? ""}
                            onBlur={(e) => setFieldOverride("assignments", row.row, "end_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.is_reserve ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.is_reserve}
                            onChange={(e) => setFieldOverride("assignments", row.row, "is_reserve", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.notes ?? "—" : (
                          <textarea
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.notes ?? ""}
                            onBlur={(e) => setFieldOverride("assignments", row.row, "notes", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "personal_number", label: "מ\"א", value: row.personal_number },
                                { key: "full_name", label: "שם", value: row.full_name },
                                { key: "duty_type_name", label: "סוג תורנות", value: row.duty_type_name },
                                { key: "duty_location_name", label: "מיקום", value: row.duty_location_name },
                                { key: "start_date", label: "תאריך התחלה", value: row.start_date, editable: { type: "date", onChange: (v) => setFieldOverride("assignments", row.row, "start_date", v) } },
                                { key: "end_date", label: "תאריך סיום", value: row.end_date, editable: { type: "date", onChange: (v) => setFieldOverride("assignments", row.row, "end_date", v) } },
                                { key: "start_time", label: "שעת התחלה", value: row.start_time, editable: { type: "text", onChange: (v) => setFieldOverride("assignments", row.row, "start_time", v) } },
                                { key: "end_time", label: "שעת סיום", value: row.end_time, editable: { type: "text", onChange: (v) => setFieldOverride("assignments", row.row, "end_time", v) } },
                                { key: "is_reserve", label: "רזרבה", value: row.is_reserve, editable: { type: "checkbox", onChange: (v) => setFieldOverride("assignments", row.row, "is_reserve", v) } },
                                { key: "notes", label: "הערות", value: row.notes, editable: { type: "textarea", onChange: (v) => setFieldOverride("assignments", row.row, "notes", v) } },
                                { key: "resolved_soldier_id", label: "מזהה חייל", value: row.resolved_soldier_id },
                                { key: "resolved_duty_shift_id", label: "מזהה משמרת", value: row.resolved_duty_shift_id },
                                { key: "matched_session_row", label: "שורה תואמת", value: row.matched_session_row },
                                { key: "errors", label: "שגיאות", value: row.errors },
                                { key: "warnings", label: "אזהרות", value: row.warnings },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} warnings={row.warnings} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("assignments", row)}
                              onChange={(e) =>
                                setRowAction("assignments", row.row, e.target.value)
                              }
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && (
                                <option value="skip">דלג</option>
                              )}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "duty_locations" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">בסיס</th>
                  <th className="text-right p-3">פעיל</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {duty_locations.map((row: DutyLocationRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        {readOnly ? row.name : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.name}
                            onBlur={(e) => setFieldOverride("duty_locations", row.row, "name", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.base ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.base ?? ""}
                            onBlur={(e) => setFieldOverride("duty_locations", row.row, "base", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.active === null ? "—" : row.active ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.active ?? false}
                            onChange={(e) => setFieldOverride("duty_locations", row.row, "active", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "name", label: "שם", value: row.name, editable: { type: "text", onChange: (v) => setFieldOverride("duty_locations", row.row, "name", v) } },
                                { key: "base", label: "בסיס", value: row.base, editable: { type: "text", onChange: (v) => setFieldOverride("duty_locations", row.row, "base", v) } },
                                { key: "active", label: "פעיל", value: row.active, editable: { type: "checkbox", onChange: (v) => setFieldOverride("duty_locations", row.row, "active", v) } },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("duty_locations", row)}
                              onChange={(e) => setRowAction("duty_locations", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "range_locations" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">פעיל</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {range_locations.map((row: RangeLocationImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        {readOnly ? row.name : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.name}
                            onBlur={(e) => setFieldOverride("range_locations", row.row, "name", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.active === null ? "—" : row.active ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.active ?? false}
                            onChange={(e) => setFieldOverride("range_locations", row.row, "active", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "name", label: "שם", value: row.name, editable: { type: "text", onChange: (v) => setFieldOverride("range_locations", row.row, "name", v) } },
                                { key: "active", label: "פעיל", value: row.active, editable: { type: "checkbox", onChange: (v) => setFieldOverride("range_locations", row.row, "active", v) } },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("range_locations", row)}
                              onChange={(e) => setRowAction("range_locations", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "range_events" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">יחידה</th>
                  <th className="text-right p-3">סוג</th>
                  <th className="text-right p-3">תאריך</th>
                  <th className="text-right p-3">מיקום</th>
                  <th className="text-right p-3">נדרש</th>
                  <th className="text-right p-3">רזרבה</th>
                  <th className="text-right p-3">שעת התחלה</th>
                  <th className="text-right p-3">שעת סיום</th>
                  <th className="text-right p-3">הערות</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {range_events.map((row: RangeEventImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  const unresolvedNode = !row.resolved_hierarchy_node_id;
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        <span className={unresolvedNode ? "text-red-600" : ""}>{row.hierarchy_node_name}</span>
                      </td>
                      <td className="p-3">
                        {readOnly ? row.range_type : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.range_type}
                            onChange={(e) => setFieldOverride("range_events", row.row, "range_type", e.target.value)}
                          >
                            <option value="laser">לייזר</option>
                            <option value="live">חי</option>
                            <option value="alal">אלל</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.date : (
                          <DateInput
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.date}
                            onBlur={(iso) => setFieldOverride("range_events", row.row, "date", iso)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <span className={row.resolved_range_location_id ? "" : "text-red-600"}>{row.range_location_name}</span>
                      </td>
                      <td className="p-3">
                        {readOnly ? row.required_count : (
                          <input
                            type="number"
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.required_count}
                            onBlur={(e) => setFieldOverride("range_events", row.row, "required_count", Number(e.target.value))}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.reserve_count : (
                          <input
                            type="number"
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.reserve_count}
                            onBlur={(e) => setFieldOverride("range_events", row.row, "reserve_count", Number(e.target.value))}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.start_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_time ?? ""}
                            onBlur={(e) => setFieldOverride("range_events", row.row, "start_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_time ?? ""}
                            onBlur={(e) => setFieldOverride("range_events", row.row, "end_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.notes ?? "—" : (
                          <textarea
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.notes ?? ""}
                            onBlur={(e) => setFieldOverride("range_events", row.row, "notes", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "hierarchy_node_name", label: "יחידה", value: row.hierarchy_node_name },
                                { key: "resolved_hierarchy_node_id", label: "מזהה יחידה", value: row.resolved_hierarchy_node_id },
                                { key: "range_type", label: "סוג", value: row.range_type },
                                { key: "date", label: "תאריך", value: row.date, editable: { type: "date", onChange: (v) => setFieldOverride("range_events", row.row, "date", v) } },
                                { key: "range_location_name", label: "מיקום", value: row.range_location_name },
                                { key: "resolved_range_location_id", label: "מזהה מיקום", value: row.resolved_range_location_id },
                                { key: "required_count", label: "נדרש", value: row.required_count, editable: { type: "number", onChange: (v) => setFieldOverride("range_events", row.row, "required_count", v) } },
                                { key: "reserve_count", label: "רזרבה", value: row.reserve_count, editable: { type: "number", onChange: (v) => setFieldOverride("range_events", row.row, "reserve_count", v) } },
                                { key: "start_time", label: "שעת התחלה", value: row.start_time, editable: { type: "text", onChange: (v) => setFieldOverride("range_events", row.row, "start_time", v) } },
                                { key: "end_time", label: "שעת סיום", value: row.end_time, editable: { type: "text", onChange: (v) => setFieldOverride("range_events", row.row, "end_time", v) } },
                                { key: "arrival_instructions", label: "הנחיות הגעה", value: row.arrival_instructions, editable: { type: "text", onChange: (v) => setFieldOverride("range_events", row.row, "arrival_instructions", v) } },
                                { key: "contact_name", label: "איש קשר", value: row.contact_name, editable: { type: "text", onChange: (v) => setFieldOverride("range_events", row.row, "contact_name", v) } },
                                { key: "contact_phone", label: "טלפון איש קשר", value: row.contact_phone, editable: { type: "text", onChange: (v) => setFieldOverride("range_events", row.row, "contact_phone", v) } },
                                { key: "notes", label: "הערות", value: row.notes, editable: { type: "textarea", onChange: (v) => setFieldOverride("range_events", row.row, "notes", v) } },
                                { key: "status", label: "סטטוס מטווח", value: row.status },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("range_events", row)}
                              onChange={(e) => setRowAction("range_events", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "range_assignments" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">מ&quot;א</th>
                  <th className="text-right p-3">סוג</th>
                  <th className="text-right p-3">תאריך</th>
                  <th className="text-right p-3">מיקום</th>
                  <th className="text-right p-3">רזרבה</th>
                  <th className="text-right p-3">נוכחות</th>
                  <th className="text-right p-3">הערה</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {range_assignments.map((row: RangeAssignmentImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        <span className={row.resolved_soldier_id ? "" : "text-red-600"}>{row.full_name}</span>
                      </td>
                      <td className="p-3">{row.personal_number}</td>
                      <td className="p-3">{row.range_type}</td>
                      <td className="p-3">{row.date}</td>
                      <td className="p-3">
                        <span className={row.resolved_range_event_id || row.matched_session_row !== null ? "" : "text-red-600"}>
                          {row.range_location_name}
                        </span>
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.is_reserve ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.is_reserve}
                            onChange={(e) => setFieldOverride("range_assignments", row.row, "is_reserve", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.attendance_status : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.attendance_status}
                            onChange={(e) => setFieldOverride("range_assignments", row.row, "attendance_status", e.target.value)}
                          >
                            <option value="pending">ממתין</option>
                            <option value="present">נוכח</option>
                            <option value="no_show">לא הגיע</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.note ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.note ?? ""}
                            onBlur={(e) => setFieldOverride("range_assignments", row.row, "note", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "personal_number", label: "מ\"א", value: row.personal_number },
                                { key: "full_name", label: "שם", value: row.full_name },
                                { key: "range_type", label: "סוג", value: row.range_type },
                                { key: "date", label: "תאריך", value: row.date },
                                { key: "range_location_name", label: "מיקום", value: row.range_location_name },
                                { key: "is_reserve", label: "רזרבה", value: row.is_reserve, editable: { type: "checkbox", onChange: (v) => setFieldOverride("range_assignments", row.row, "is_reserve", v) } },
                                { key: "is_draft", label: "טיוטה", value: row.is_draft, editable: { type: "checkbox", onChange: (v) => setFieldOverride("range_assignments", row.row, "is_draft", v) } },
                                { key: "attendance_status", label: "נוכחות", value: row.attendance_status },
                                { key: "note", label: "הערה", value: row.note, editable: { type: "text", onChange: (v) => setFieldOverride("range_assignments", row.row, "note", v) } },
                                { key: "resolved_soldier_id", label: "מזהה חייל", value: row.resolved_soldier_id },
                                { key: "resolved_range_event_id", label: "מזהה מטווח", value: row.resolved_range_event_id },
                                { key: "matched_session_row", label: "שורה תואמת", value: row.matched_session_row },
                                { key: "errors", label: "שגיאות", value: row.errors },
                                { key: "warnings", label: "אזהרות", value: row.warnings },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} warnings={row.warnings} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("range_assignments", row)}
                              onChange={(e) => setRowAction("range_assignments", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "hierarchy" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">סוג</th>
                  <th className="text-right p-3">יחידת אב</th>
                  <th className="text-right p-3">מפקד</th>
                  <th className="text-right p-3">אחראי תורנות</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {hierarchy.map((row: HierarchyImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        {readOnly ? row.name : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.name}
                            onBlur={(e) => setFieldOverride("hierarchy", row.row, "name", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.level : (
                          <input
                            className="border rounded p-1 text-sm w-24 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.level}
                            onBlur={(e) => setFieldOverride("hierarchy", row.row, "level", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">{row.parent_name ?? "—"}</td>
                      <td className="p-3">
                        {row.commander_personal_number || row.commander_name ? (
                          <span className={row.resolved_commander_id ? "" : "text-red-600"}>
                            {row.commander_name ?? row.commander_personal_number}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-3">
                        {row.duty_manager_refs.length === 0 ? (
                          "—"
                        ) : (
                          <div className="flex flex-col gap-0.5">
                            {row.duty_manager_refs.map((dm, i) => (
                              <span key={i} className={dm.resolved_soldier_id ? "" : "text-red-600"}>
                                {dm.ref}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "name", label: "שם", value: row.name, editable: { type: "text", onChange: (v) => setFieldOverride("hierarchy", row.row, "name", v) } },
                                { key: "level", label: "סוג", value: row.level, editable: { type: "text", onChange: (v) => setFieldOverride("hierarchy", row.row, "level", v) } },
                                { key: "parent_name", label: "יחידת אב", value: row.parent_name },
                                { key: "resolved_parent_id", label: "מזהה יחידת אב", value: row.resolved_parent_id },
                                { key: "commander_personal_number", label: "מ\"א מפקד", value: row.commander_personal_number },
                                { key: "commander_name", label: "שם מפקד", value: row.commander_name },
                                { key: "resolved_commander_id", label: "מזהה מפקד", value: row.resolved_commander_id },
                                { key: "duty_manager_refs", label: "אחראי תורנות", value: row.duty_manager_refs.map((d) => d.ref) },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("hierarchy", row)}
                              onChange={(e) => setRowAction("hierarchy", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "duty_types" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">ניקוד ליום</th>
                  <th className="text-right p-3">תיאור</th>
                  <th className="text-right p-3">פעיל</th>
                  <th className="text-right p-3">יחס רזרבה</th>
                  <th className="text-right p-3">מינימום רזרבה</th>
                  <th className="text-right p-3">חיצוני</th>
                  <th className="text-right p-3">איש קשר</th>
                  <th className="text-right p-3">טלפון</th>
                  <th className="text-right p-3">שעת התחלה</th>
                  <th className="text-right p-3">שעת סיום</th>
                  <th className="text-right p-3">הוראות</th>
                  <th className="text-right p-3">יחידות/דרישות</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {duty_types.map((row: DutyTypeImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        {readOnly ? row.name : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.name}
                            onBlur={(e) => setFieldOverride("duty_types", row.row, "name", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.score_per_day : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.score_per_day ?? ""}
                            onBlur={(e) => setFieldOverride("duty_types", row.row, "score_per_day", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.description ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-40 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.description ?? ""}
                            onBlur={(e) => setFieldOverride("duty_types", row.row, "description", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.active === null ? "—" : row.active ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.active ?? false}
                            onChange={(e) => setFieldOverride("duty_types", row.row, "active", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.reserve_ratio ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-20 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.reserve_ratio ?? ""}
                            onBlur={(e) => setFieldOverride("duty_types", row.row, "reserve_ratio", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.reserve_minimum ?? "—" : (
                          <input
                            type="number"
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.reserve_minimum ?? ""}
                            onBlur={(e) => setFieldOverride("duty_types", row.row, "reserve_minimum", e.target.value ? Number(e.target.value) : null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.is_external === null ? "—" : row.is_external ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.is_external ?? false}
                            onChange={(e) => setFieldOverride("duty_types", row.row, "is_external", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.contact_name ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.contact_name ?? ""}
                            onBlur={(e) => setFieldOverride("duty_types", row.row, "contact_name", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.contact_phone ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.contact_phone ?? ""}
                            onBlur={(e) => setFieldOverride("duty_types", row.row, "contact_phone", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.start_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_time ?? ""}
                            onBlur={(e) => setFieldOverride("duty_types", row.row, "start_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_time ?? ""}
                            onBlur={(e) => setFieldOverride("duty_types", row.row, "end_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.instructions ?? "—" : (
                          <textarea
                            className="border rounded p-1 text-sm w-40 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.instructions ?? ""}
                            onBlur={(e) => setFieldOverride("duty_types", row.row, "instructions", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {!readOnly && (
                          <button
                            type="button"
                            className="text-indigo-600 hover:underline text-xs"
                            onClick={() => setDutyTypeFieldsRow(row)}
                          >
                            ערוך יחידות/דרישות
                          </button>
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "name", label: "שם", value: row.name, editable: { type: "text", onChange: (v) => setFieldOverride("duty_types", row.row, "name", v) } },
                                { key: "score_per_day", label: "ניקוד ליום", value: row.score_per_day, editable: { type: "text", onChange: (v) => setFieldOverride("duty_types", row.row, "score_per_day", v) } },
                                { key: "description", label: "תיאור", value: row.description, editable: { type: "text", onChange: (v) => setFieldOverride("duty_types", row.row, "description", v) } },
                                { key: "active", label: "פעיל", value: row.active, editable: { type: "checkbox", onChange: (v) => setFieldOverride("duty_types", row.row, "active", v) } },
                                { key: "reserve_ratio", label: "יחס רזרבה", value: row.reserve_ratio, editable: { type: "text", onChange: (v) => setFieldOverride("duty_types", row.row, "reserve_ratio", v) } },
                                { key: "reserve_minimum", label: "מינימום רזרבה", value: row.reserve_minimum, editable: { type: "number", onChange: (v) => setFieldOverride("duty_types", row.row, "reserve_minimum", v) } },
                                { key: "is_external", label: "חיצוני", value: row.is_external, editable: { type: "checkbox", onChange: (v) => setFieldOverride("duty_types", row.row, "is_external", v) } },
                                { key: "contact_name", label: "איש קשר", value: row.contact_name, editable: { type: "text", onChange: (v) => setFieldOverride("duty_types", row.row, "contact_name", v) } },
                                { key: "contact_phone", label: "טלפון", value: row.contact_phone, editable: { type: "text", onChange: (v) => setFieldOverride("duty_types", row.row, "contact_phone", v) } },
                                { key: "start_time", label: "שעת התחלה", value: row.start_time, editable: { type: "text", onChange: (v) => setFieldOverride("duty_types", row.row, "start_time", v) } },
                                { key: "end_time", label: "שעת סיום", value: row.end_time, editable: { type: "text", onChange: (v) => setFieldOverride("duty_types", row.row, "end_time", v) } },
                                { key: "instructions", label: "הוראות", value: row.instructions, editable: { type: "textarea", onChange: (v) => setFieldOverride("duty_types", row.row, "instructions", v) } },
                                { key: "resolved_eligible_node_ids", label: "יחידות זכאיות", value: row.resolved_eligible_node_ids },
                                { key: "requirements", label: "דרישות", value: row.requirements },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("duty_types", row)}
                              onChange={(e) => setRowAction("duty_types", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "exemption_types" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">תיאור</th>
                  <th className="text-right p-3">גלובלי</th>
                  <th className="text-right p-3">רפואי</th>
                  <th className="text-right p-3">פטור פיקודי</th>
                  <th className="text-right p-3">חל על</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {exemption_types.map((row: ExemptionTypeImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        {readOnly ? row.name : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.name}
                            onBlur={(e) => setFieldOverride("exemption_types", row.row, "name", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.description ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-40 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.description ?? ""}
                            onBlur={(e) => setFieldOverride("exemption_types", row.row, "description", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.is_global ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.is_global}
                            onChange={(e) => setFieldOverride("exemption_types", row.row, "is_global", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.is_medical ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.is_medical}
                            onChange={(e) => setFieldOverride("exemption_types", row.row, "is_medical", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.is_commander_exemption ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.is_commander_exemption}
                            onChange={(e) => setFieldOverride("exemption_types", row.row, "is_commander_exemption", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {!readOnly && (
                          <button
                            type="button"
                            className="text-indigo-600 hover:underline text-xs"
                            onClick={() => setExemptionTypeFieldsRow(row)}
                          >
                            ערוך חל-על
                          </button>
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "name", label: "שם", value: row.name, editable: { type: "text", onChange: (v) => setFieldOverride("exemption_types", row.row, "name", v) } },
                                { key: "description", label: "תיאור", value: row.description, editable: { type: "text", onChange: (v) => setFieldOverride("exemption_types", row.row, "description", v) } },
                                { key: "is_global", label: "גלובלי", value: row.is_global, editable: { type: "checkbox", onChange: (v) => setFieldOverride("exemption_types", row.row, "is_global", v) } },
                                { key: "is_medical", label: "רפואי", value: row.is_medical, editable: { type: "checkbox", onChange: (v) => setFieldOverride("exemption_types", row.row, "is_medical", v) } },
                                { key: "is_commander_exemption", label: "פטור פיקודי", value: row.is_commander_exemption, editable: { type: "checkbox", onChange: (v) => setFieldOverride("exemption_types", row.row, "is_commander_exemption", v) } },
                                { key: "resolved_duty_type_ids", label: "חל על", value: row.resolved_duty_type_ids },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("exemption_types", row)}
                              onChange={(e) => setRowAction("exemption_types", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "system_settings" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">מפתח</th>
                  <th className="text-right p-3">ערך (JSON)</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {system_settings.map((row: SystemSettingImportRow) => {
                  const canToggle = row.action !== "error";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.key}</td>
                      <td className="p-3">
                        {readOnly ? row.value_json : (
                          <input
                            className="border rounded p-1 text-sm w-40 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.value_json}
                            onBlur={(e) => setFieldOverride("system_settings", row.row, "value_json", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("system_settings", row)}
                              onChange={(e) => setRowAction("system_settings", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "bug_reports" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">מדווח</th>
                  <th className="text-right p-3">תיאור</th>
                  <th className="text-right p-3">חומרה</th>
                  <th className="text-right p-3">route</th>
                  <th className="text-right p-3">סטטוס תקלה</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {bug_reports.map((row: BugReportImportRow) => {
                  const canToggle = row.action !== "error";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.reporter_personal_number}</td>
                      <td className="p-3">
                        {readOnly ? row.description : (
                          <input
                            className="border rounded p-1 text-sm w-48 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.description}
                            onBlur={(e) => setFieldOverride("bug_reports", row.row, "description", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.severity : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.severity}
                            onChange={(e) => setFieldOverride("bug_reports", row.row, "severity", e.target.value)}
                          >
                            <option value="low">low</option>
                            <option value="medium">medium</option>
                            <option value="high">high</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">{row.route}</td>
                      <td className="p-3">
                        {readOnly ? row.status : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.status}
                            onChange={(e) => setFieldOverride("bug_reports", row.row, "status", e.target.value)}
                          >
                            <option value="open">open</option>
                            <option value="in_progress">in_progress</option>
                            <option value="resolved">resolved</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} warnings={row.warnings} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("bug_reports", row)}
                              onChange={(e) => setRowAction("bug_reports", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "personal_constraints" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">חייל</th>
                  <th className="text-right p-3">תאריך התחלה</th>
                  <th className="text-right p-3">תאריך סיום</th>
                  <th className="text-right p-3">סיבה</th>
                  <th className="text-right p-3">סטטוס אישור</th>
                  <th className="text-right p-3">מחליט</th>
                  <th className="text-right p-3">הערת החלטה</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {personal_constraints.map((row: PersonalConstraintImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        <span className={row.resolved_soldier_id ? "" : "text-red-600"}>
                          {row.soldier_personal_number}
                        </span>
                      </td>
                      <td className="p-3">
                        {readOnly ? row.start_date : (
                          <input
                            type="date"
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_date}
                            onBlur={(e) => setFieldOverride("personal_constraints", row.row, "start_date", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_date : (
                          <input
                            type="date"
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_date}
                            onBlur={(e) => setFieldOverride("personal_constraints", row.row, "end_date", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.reason : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.reason}
                            onBlur={(e) => setFieldOverride("personal_constraints", row.row, "reason", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.status : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.status}
                            onChange={(e) => setFieldOverride("personal_constraints", row.row, "status", e.target.value)}
                          >
                            <option value="pending_commander">ממתין למפקד</option>
                            <option value="pending_duty_manager">ממתין לקצין תורן</option>
                            <option value="approved">מאושר</option>
                            <option value="rejected">נדחה</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        {row.decided_by_personal_number ? (
                          <span className={row.resolved_decided_by_id ? "" : "text-red-600"}>
                            {row.decided_by_personal_number}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.decision_note ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.decision_note ?? ""}
                            onBlur={(e) => setFieldOverride("personal_constraints", row.row, "decision_note", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "soldier_personal_number", label: "מ\"א חייל", value: row.soldier_personal_number },
                                { key: "resolved_soldier_id", label: "מזהה חייל", value: row.resolved_soldier_id },
                                { key: "start_date", label: "תאריך התחלה", value: row.start_date, editable: { type: "date", onChange: (v) => setFieldOverride("personal_constraints", row.row, "start_date", v) } },
                                { key: "end_date", label: "תאריך סיום", value: row.end_date, editable: { type: "date", onChange: (v) => setFieldOverride("personal_constraints", row.row, "end_date", v) } },
                                { key: "reason", label: "סיבה", value: row.reason, editable: { type: "text", onChange: (v) => setFieldOverride("personal_constraints", row.row, "reason", v) } },
                                { key: "status", label: "סטטוס אישור", value: row.status, editable: { type: "text", onChange: (v) => setFieldOverride("personal_constraints", row.row, "status", v) } },
                                { key: "decided_by_personal_number", label: "מ\"א מחליט", value: row.decided_by_personal_number },
                                { key: "resolved_decided_by_id", label: "מזהה מחליט", value: row.resolved_decided_by_id },
                                { key: "decision_note", label: "הערת החלטה", value: row.decision_note, editable: { type: "text", onChange: (v) => setFieldOverride("personal_constraints", row.row, "decision_note", v) } },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("personal_constraints", row)}
                              onChange={(e) => setRowAction("personal_constraints", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "soldier_field_updates" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">חייל</th>
                  <th className="text-right p-3">שם שדה</th>
                  <th className="text-right p-3">ערך חדש</th>
                  <th className="text-right p-3">ערך קודם</th>
                  <th className="text-right p-3">סטטוס אישור</th>
                  <th className="text-right p-3">מחליט</th>
                  <th className="text-right p-3">הערת החלטה</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {soldier_field_updates.map((row: SoldierFieldUpdateImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        <span className={row.resolved_soldier_id ? "" : "text-red-600"}>
                          {row.soldier_personal_number}
                        </span>
                      </td>
                      <td className="p-3">
                        {readOnly ? row.field_name : (
                          <input
                            className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.field_name}
                            onBlur={(e) => setFieldOverride("soldier_field_updates", row.row, "field_name", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.new_value : (
                          <input
                            className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.new_value}
                            onBlur={(e) => setFieldOverride("soldier_field_updates", row.row, "new_value", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.previous_value ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.previous_value ?? ""}
                            onBlur={(e) => setFieldOverride("soldier_field_updates", row.row, "previous_value", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.status : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.status}
                            onChange={(e) => setFieldOverride("soldier_field_updates", row.row, "status", e.target.value)}
                          >
                            <option value="pending">ממתין</option>
                            <option value="approved">מאושר</option>
                            <option value="rejected">נדחה</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        {row.decided_by_personal_number ? (
                          <span className={row.resolved_decided_by_id ? "" : "text-red-600"}>
                            {row.decided_by_personal_number}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.decision_note ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.decision_note ?? ""}
                            onBlur={(e) => setFieldOverride("soldier_field_updates", row.row, "decision_note", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "soldier_personal_number", label: "מ\"א חייל", value: row.soldier_personal_number },
                                { key: "resolved_soldier_id", label: "מזהה חייל", value: row.resolved_soldier_id },
                                { key: "field_name", label: "שם שדה", value: row.field_name, editable: { type: "text", onChange: (v) => setFieldOverride("soldier_field_updates", row.row, "field_name", v) } },
                                { key: "new_value", label: "ערך חדש", value: row.new_value, editable: { type: "text", onChange: (v) => setFieldOverride("soldier_field_updates", row.row, "new_value", v) } },
                                { key: "previous_value", label: "ערך קודם", value: row.previous_value, editable: { type: "text", onChange: (v) => setFieldOverride("soldier_field_updates", row.row, "previous_value", v) } },
                                { key: "status", label: "סטטוס אישור", value: row.status, editable: { type: "text", onChange: (v) => setFieldOverride("soldier_field_updates", row.row, "status", v) } },
                                { key: "decided_by_personal_number", label: "מ\"א מחליט", value: row.decided_by_personal_number },
                                { key: "resolved_decided_by_id", label: "מזהה מחליט", value: row.resolved_decided_by_id },
                                { key: "decision_note", label: "הערת החלטה", value: row.decision_note, editable: { type: "text", onChange: (v) => setFieldOverride("soldier_field_updates", row.row, "decision_note", v) } },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("soldier_field_updates", row)}
                              onChange={(e) => setRowAction("soldier_field_updates", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "soldier_enrollment_requests" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">חייל</th>
                  <th className="text-right p-3">יחידה מבוקשת</th>
                  <th className="text-right p-3">סטטוס אישור</th>
                  <th className="text-right p-3">מחליט</th>
                  <th className="text-right p-3">הערת החלטה</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {soldier_enrollment_requests.map((row: SoldierEnrollmentRequestImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        <span className={row.resolved_soldier_id ? "" : "text-red-600"}>
                          {row.soldier_personal_number}
                        </span>
                      </td>
                      <td className="p-3">
                        <span className={row.resolved_node_id ? "" : "text-red-600"}>
                          {row.requested_node_name}
                        </span>
                      </td>
                      <td className="p-3">
                        {readOnly ? row.status : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.status}
                            onChange={(e) => setFieldOverride("soldier_enrollment_requests", row.row, "status", e.target.value)}
                          >
                            <option value="pending">ממתין</option>
                            <option value="commander_approved">אישור מפקד</option>
                            <option value="approved">מאושר</option>
                            <option value="rejected">נדחה</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        {row.decided_by_personal_number ? (
                          <span className={row.resolved_decided_by_id ? "" : "text-red-600"}>
                            {row.decided_by_personal_number}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.decision_note ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.decision_note ?? ""}
                            onBlur={(e) => setFieldOverride("soldier_enrollment_requests", row.row, "decision_note", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "soldier_personal_number", label: "מ\"א חייל", value: row.soldier_personal_number },
                                { key: "resolved_soldier_id", label: "מזהה חייל", value: row.resolved_soldier_id },
                                { key: "requested_node_name", label: "יחידה מבוקשת", value: row.requested_node_name },
                                { key: "resolved_node_id", label: "מזהה יחידה", value: row.resolved_node_id },
                                { key: "status", label: "סטטוס אישור", value: row.status, editable: { type: "text", onChange: (v) => setFieldOverride("soldier_enrollment_requests", row.row, "status", v) } },
                                { key: "decided_by_personal_number", label: "מ\"א מחליט", value: row.decided_by_personal_number },
                                { key: "resolved_decided_by_id", label: "מזהה מחליט", value: row.resolved_decided_by_id },
                                { key: "decision_note", label: "הערת החלטה", value: row.decision_note, editable: { type: "text", onChange: (v) => setFieldOverride("soldier_enrollment_requests", row.row, "decision_note", v) } },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("soldier_enrollment_requests", row)}
                              onChange={(e) => setRowAction("soldier_enrollment_requests", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "soldier_exemptions" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">חייל</th>
                  <th className="text-right p-3">סוג פטור</th>
                  <th className="text-right p-3">תאריך התחלה</th>
                  <th className="text-right p-3">תאריך סיום</th>
                  <th className="text-right p-3">סיבה</th>
                  <th className="text-right p-3">מעניק</th>
                  <th className="text-right p-3">בוטל</th>
                  <th className="text-right p-3">סיבת ביטול</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {soldier_exemptions.map((row: SoldierExemptionImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        <span className={row.resolved_soldier_id ? "" : "text-red-600"}>
                          {row.soldier_personal_number}
                        </span>
                      </td>
                      <td className="p-3">
                        <span className={row.resolved_exemption_type_id ? "" : "text-red-600"}>
                          {row.exemption_type_name}
                        </span>
                      </td>
                      <td className="p-3">
                        {readOnly ? row.start_date : (
                          <input
                            type="date"
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_date}
                            onBlur={(e) => setFieldOverride("soldier_exemptions", row.row, "start_date", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_date ?? "—" : (
                          <input
                            type="date"
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_date ?? ""}
                            onBlur={(e) => setFieldOverride("soldier_exemptions", row.row, "end_date", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.reason ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.reason ?? ""}
                            onBlur={(e) => setFieldOverride("soldier_exemptions", row.row, "reason", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {row.granted_by_personal_number ? (
                          <span className={row.resolved_granted_by_id ? "" : "text-red-600"}>
                            {row.granted_by_personal_number}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.revoked ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.revoked}
                            onChange={(e) => setFieldOverride("soldier_exemptions", row.row, "revoked", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.revoke_reason ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.revoke_reason ?? ""}
                            onBlur={(e) => setFieldOverride("soldier_exemptions", row.row, "revoke_reason", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "soldier_personal_number", label: "מ\"א חייל", value: row.soldier_personal_number },
                                { key: "resolved_soldier_id", label: "מזהה חייל", value: row.resolved_soldier_id },
                                { key: "exemption_type_name", label: "סוג פטור", value: row.exemption_type_name },
                                { key: "resolved_exemption_type_id", label: "מזהה סוג פטור", value: row.resolved_exemption_type_id },
                                { key: "start_date", label: "תאריך התחלה", value: row.start_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldier_exemptions", row.row, "start_date", v) } },
                                { key: "end_date", label: "תאריך סיום", value: row.end_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldier_exemptions", row.row, "end_date", v) } },
                                { key: "reason", label: "סיבה", value: row.reason, editable: { type: "text", onChange: (v) => setFieldOverride("soldier_exemptions", row.row, "reason", v) } },
                                { key: "granted_by_personal_number", label: "מ\"א מעניק", value: row.granted_by_personal_number },
                                { key: "resolved_granted_by_id", label: "מזהה מעניק", value: row.resolved_granted_by_id },
                                { key: "revoked", label: "בוטל", value: row.revoked, editable: { type: "checkbox", onChange: (v) => setFieldOverride("soldier_exemptions", row.row, "revoked", v) } },
                                { key: "revoke_reason", label: "סיבת ביטול", value: row.revoke_reason, editable: { type: "text", onChange: (v) => setFieldOverride("soldier_exemptions", row.row, "revoke_reason", v) } },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("soldier_exemptions", row)}
                              onChange={(e) => setRowAction("soldier_exemptions", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "exemption_requests" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">חייל</th>
                  <th className="text-right p-3">סוג פטור</th>
                  <th className="text-right p-3">תאריך התחלה</th>
                  <th className="text-right p-3">תאריך סיום</th>
                  <th className="text-right p-3">סיבה</th>
                  <th className="text-right p-3">סטטוס אישור</th>
                  <th className="text-right p-3">מפקד מאשר</th>
                  <th className="text-right p-3">מחליט</th>
                  <th className="text-right p-3">הערת החלטה</th>
                  <th className="text-right p-3">קבצים</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {exemption_requests.map((row: ExemptionRequestImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        <span className={row.resolved_soldier_id ? "" : "text-red-600"}>
                          {row.soldier_personal_number}
                        </span>
                      </td>
                      <td className="p-3">
                        <span className={row.resolved_exemption_type_id ? "" : "text-red-600"}>
                          {row.exemption_type_name}
                        </span>
                      </td>
                      <td className="p-3">
                        {readOnly ? row.start_date : (
                          <input
                            type="date"
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_date}
                            onBlur={(e) => setFieldOverride("exemption_requests", row.row, "start_date", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_date ?? "—" : (
                          <input
                            type="date"
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_date ?? ""}
                            onBlur={(e) => setFieldOverride("exemption_requests", row.row, "end_date", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.reason ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.reason ?? ""}
                            onBlur={(e) => setFieldOverride("exemption_requests", row.row, "reason", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.status : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.status}
                            onChange={(e) => setFieldOverride("exemption_requests", row.row, "status", e.target.value)}
                          >
                            <option value="pending_commander">ממתין למפקד</option>
                            <option value="pending_duty_manager">ממתין לקצין תורן</option>
                            <option value="approved">מאושר</option>
                            <option value="rejected">נדחה</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        {row.commander_approved_by_personal_number ? (
                          <span className={row.resolved_commander_approved_by_id ? "" : "text-red-600"}>
                            {row.commander_approved_by_personal_number}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-3">
                        {row.decided_by_personal_number ? (
                          <span className={row.resolved_decided_by_id ? "" : "text-red-600"}>
                            {row.decided_by_personal_number}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.decision_note ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.decision_note ?? ""}
                            onBlur={(e) => setFieldOverride("exemption_requests", row.row, "decision_note", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">{row.files ?? "—"}</td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "soldier_personal_number", label: "מ\"א חייל", value: row.soldier_personal_number },
                                { key: "resolved_soldier_id", label: "מזהה חייל", value: row.resolved_soldier_id },
                                { key: "exemption_type_name", label: "סוג פטור", value: row.exemption_type_name },
                                { key: "resolved_exemption_type_id", label: "מזהה סוג פטור", value: row.resolved_exemption_type_id },
                                { key: "start_date", label: "תאריך התחלה", value: row.start_date, editable: { type: "date", onChange: (v) => setFieldOverride("exemption_requests", row.row, "start_date", v) } },
                                { key: "end_date", label: "תאריך סיום", value: row.end_date, editable: { type: "date", onChange: (v) => setFieldOverride("exemption_requests", row.row, "end_date", v) } },
                                { key: "reason", label: "סיבה", value: row.reason, editable: { type: "text", onChange: (v) => setFieldOverride("exemption_requests", row.row, "reason", v) } },
                                { key: "status", label: "סטטוס אישור", value: row.status, editable: { type: "text", onChange: (v) => setFieldOverride("exemption_requests", row.row, "status", v) } },
                                { key: "commander_approved_by_personal_number", label: "מ\"א מפקד מאשר", value: row.commander_approved_by_personal_number },
                                { key: "resolved_commander_approved_by_id", label: "מזהה מפקד מאשר", value: row.resolved_commander_approved_by_id },
                                { key: "decided_by_personal_number", label: "מ\"א מחליט", value: row.decided_by_personal_number },
                                { key: "resolved_decided_by_id", label: "מזהה מחליט", value: row.resolved_decided_by_id },
                                { key: "decision_note", label: "הערת החלטה", value: row.decision_note, editable: { type: "text", onChange: (v) => setFieldOverride("exemption_requests", row.row, "decision_note", v) } },
                                { key: "files", label: "קבצים", value: row.files },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("exemption_requests", row)}
                              onChange={(e) => setRowAction("exemption_requests", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "swap_requests" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">מבקש</th>
                  <th className="text-right p-3">חייל יעד</th>
                  <th className="text-right p-3">מחליף</th>
                  <th className="text-right p-3">תאריך תורנות</th>
                  <th className="text-right p-3">סטטוס</th>
                  <th className="text-right p-3">סיבה</th>
                  <th className="text-right p-3">אישור מבקש</th>
                  <th className="text-right p-3">אישור מחליף</th>
                  <th className="text-right p-3">נדחה ע&quot;י</th>
                  <th className="text-right p-3">הערת החלטה</th>
                  <th className="text-right p-3">לוג אישורים</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">מצב</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {swap_requests.map((row: SwapRequestImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  const approvalLogSummary = row.approval_log.length > 0
                    ? row.approval_log
                        .map((e) => `${e.side === "requester" ? "מבקש" : "מחליף"}/${e.kind === "commander" ? "מפקד" : "קצין תורן"}: ${e.person_pn} - ${e.outcome === "approved" ? "אישר" : "דחה"} (${e.at})`)
                        .join("; ")
                    : null;
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        <span className={row.resolved_requesting_soldier_id ? "" : "text-red-600"}>
                          {row.requesting_personal_number}
                        </span>
                      </td>
                      <td className="p-3">
                        {row.target_personal_number ? (
                          <span className={row.resolved_target_soldier_id ? "" : "text-red-600"}>
                            {row.target_personal_number}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-3">
                        {row.covering_personal_number ? (
                          <span className={row.resolved_covering_soldier_id ? "" : "text-red-600"}>
                            {row.covering_personal_number}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.duty_date : (
                          <input
                            type="date"
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.duty_date}
                            onBlur={(e) => setFieldOverride("swap_requests", row.row, "duty_date", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.status : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.status}
                            onChange={(e) => setFieldOverride("swap_requests", row.row, "status", e.target.value)}
                          >
                            {/* "pending_approval" is deliberately absent: it was
                                removed as a SwapRequest.status value by the unified
                                swap-requests schema change (that in-progress state
                                lives on SwapCandidate.status now), and the backend's
                                resolve_swap_requests rejects it as invalid. Only the
                                four statuses it accepts are offered here. */}
                            <option value="open">פתוח</option>
                            <option value="applied">בוצע</option>
                            <option value="rejected">נדחה</option>
                            <option value="cancelled">בוטל</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.reason ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.reason ?? ""}
                            onBlur={(e) => setFieldOverride("swap_requests", row.row, "reason", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.requester_side_approved === null ? "—" : row.requester_side_approved ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.requester_side_approved ?? false}
                            onChange={(e) => setFieldOverride("swap_requests", row.row, "requester_side_approved", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.covering_side_approved === null ? "—" : row.covering_side_approved ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.covering_side_approved ?? false}
                            onChange={(e) => setFieldOverride("swap_requests", row.row, "covering_side_approved", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {row.rejected_by_personal_number ? (
                          <span className={row.resolved_rejected_by_id ? "" : "text-red-600"}>
                            {row.rejected_by_personal_number}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.decision_note ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.decision_note ?? ""}
                            onBlur={(e) => setFieldOverride("swap_requests", row.row, "decision_note", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3 text-xs text-gray-500">
                        {row.approval_log.length > 0 ? `${row.approval_log.length} רשומות` : "—"}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "requesting_personal_number", label: "מ\"א מבקש", value: row.requesting_personal_number },
                                { key: "resolved_requesting_soldier_id", label: "מזהה מבקש", value: row.resolved_requesting_soldier_id },
                                { key: "target_personal_number", label: "מ\"א חייל יעד", value: row.target_personal_number },
                                { key: "resolved_target_soldier_id", label: "מזהה חייל יעד", value: row.resolved_target_soldier_id },
                                { key: "covering_personal_number", label: "מ\"א מחליף", value: row.covering_personal_number },
                                { key: "resolved_covering_soldier_id", label: "מזהה מחליף", value: row.resolved_covering_soldier_id },
                                { key: "duty_date", label: "תאריך תורנות", value: row.duty_date, editable: { type: "date", onChange: (v) => setFieldOverride("swap_requests", row.row, "duty_date", v) } },
                                { key: "status", label: "סטטוס", value: row.status, editable: { type: "text", onChange: (v) => setFieldOverride("swap_requests", row.row, "status", v) } },
                                { key: "reason", label: "סיבה", value: row.reason, editable: { type: "text", onChange: (v) => setFieldOverride("swap_requests", row.row, "reason", v) } },
                                { key: "requester_side_approved", label: "אישור מבקש", value: row.requester_side_approved, editable: { type: "checkbox", onChange: (v) => setFieldOverride("swap_requests", row.row, "requester_side_approved", v) } },
                                { key: "covering_side_approved", label: "אישור מחליף", value: row.covering_side_approved, editable: { type: "checkbox", onChange: (v) => setFieldOverride("swap_requests", row.row, "covering_side_approved", v) } },
                                { key: "rejected_by_personal_number", label: "נדחה ע\"י (מ\"א)", value: row.rejected_by_personal_number },
                                { key: "resolved_rejected_by_id", label: "מזהה דוחה", value: row.resolved_rejected_by_id },
                                { key: "decision_note", label: "הערת החלטה", value: row.decision_note, editable: { type: "text", onChange: (v) => setFieldOverride("swap_requests", row.row, "decision_note", v) } },
                                { key: "approval_log", label: "לוג אישורים", value: approvalLogSummary },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("swap_requests", row)}
                              onChange={(e) => setRowAction("swap_requests", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {confirmError && (
          <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
            {confirmError}
          </div>
        )}

        {confirmResult && (
          <div className="bg-green-50 border border-green-200 rounded p-3 text-sm text-green-700 space-y-1">
            <p>
              נוצרו: {confirmResult.created} / עודכנו: {confirmResult.updated} /
              דולגו: {confirmResult.skipped}
            </p>
            {confirmResult.errors.length > 0 && (
              <ul className="list-disc pr-4 text-red-700">
                {confirmResult.errors.map((e, i) => (
                  <li key={i}>
                    שורה {e.row} ({e.type}): {e.error}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {!readOnly && (
          <div className="flex justify-end">
            <button
              className="bg-indigo-600 text-white px-6 py-2 rounded font-medium hover:bg-indigo-700 disabled:opacity-50"
              disabled={confirming}
              onClick={() => void handleConfirm()}
            >
              {confirming ? "מאשר..." : "אשר וייבא"}
            </button>
          </div>
        )}
      </div>

      {dutyTypeContext && (
        <DutyTypeFormModal
          initialName={dutyTypeContext.unresolvedName}
          onSaved={() => {
            setDutyTypeContext(null);
            void handleReparse();
          }}
          onClose={() => setDutyTypeContext(null)}
        />
      )}

      {nodeCreateContext && (
        <AddRootNodeDialog
          initialName={nodeCreateContext.unresolvedName}
          parentItems={sortedNodeItems}
          parentNodes={allNodes}
          onCreated={() => {
            void handleReparse();
          }}
          onClose={() => setNodeCreateContext(null)}
        />
      )}

      {dutyTypeFieldsRow && (
        <ImportRowFieldsModal
          onClose={() => setDutyTypeFieldsRow(null)}
          eligibleUnits={{
            value: dutyTypeFieldsRow.resolved_eligible_node_ids,
            onChange: (next) => {
              setFieldOverride("duty_types", dutyTypeFieldsRow.row, "resolved_eligible_node_ids", next);
              setDutyTypeFieldsRow({ ...dutyTypeFieldsRow, resolved_eligible_node_ids: next });
            },
          }}
          requirements={{
            value: dutyTypeFieldsRow.requirements ?? {},
            onChange: (next) => {
              setFieldOverride("duty_types", dutyTypeFieldsRow.row, "requirements", next);
              setDutyTypeFieldsRow({ ...dutyTypeFieldsRow, requirements: next });
            },
          }}
        />
      )}

      {exemptionTypeFieldsRow && (
        <ImportRowFieldsModal
          onClose={() => setExemptionTypeFieldsRow(null)}
          dutyTypeMultiSelect={{
            label: "חל על סוגי תורנות",
            options: allDutyTypes,
            value: exemptionTypeFieldsRow.resolved_duty_type_ids,
            onChange: (next) => {
              setFieldOverride("exemption_types", exemptionTypeFieldsRow.row, "resolved_duty_type_ids", next);
              setExemptionTypeFieldsRow({ ...exemptionTypeFieldsRow, resolved_duty_type_ids: next });
            },
          }}
        />
      )}

      {shiftTemplateFieldsRow && (
        <ImportRowFieldsModal
          onClose={() => setShiftTemplateFieldsRow(null)}
          eligibleUnits={{
            value: shiftTemplateFieldsRow.resolved_eligible_node_ids,
            onChange: (next) => {
              setFieldOverride("shift_templates", shiftTemplateFieldsRow.row, "resolved_eligible_node_ids", next);
              setShiftTemplateFieldsRow({ ...shiftTemplateFieldsRow, resolved_eligible_node_ids: next });
            },
          }}
        />
      )}

      {detailModal && (
        <ImportRowDetailModal
          title={detailModal.title}
          fields={detailModal.fields}
          onClose={() => setDetailModal(null)}
        />
      )}
    </Layout>
  );
}
