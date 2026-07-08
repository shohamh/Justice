import Fuse from "fuse.js";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import Combobox, { type ComboboxItem } from "../components/Combobox";
import Layout from "../components/Layout";
import DutyTypeFormModal from "../components/DutyTypeFormModal";
import AddRootNodeDialog from "../components/AddRootNodeDialog";
import ImportRowFieldsModal from "../components/ImportRowFieldsModal";
import {
  type SessionDetail,
  type ConfirmSessionResult,
  type RowBase,
  type Selections,
  type ShiftTemplateRow,
  type AssignmentRow,
  type DutyLocationRow,
  type HierarchyImportRow,
  type DutyTypeImportRow,
  type ExemptionTypeImportRow,
  getSession,
  reparseSession,
  saveSelections,
  confirmSession,
  listDutyTypesForImport,
  listNodesForImport,
} from "../api/importSessions";

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
  | "exemption_types";

type GroupKey =
  | "soldiers"
  | "duty_shifts"
  | "shift_templates"
  | "assignments"
  | "duty_locations"
  | "hierarchy"
  | "duty_types"
  | "exemption_types";

function extractDetail(err: unknown): string | undefined {
  return (err as { response?: { data?: { detail?: string } } })?.response?.data
    ?.detail;
}

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
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  // lookup data
  const [allDutyTypes, setAllDutyTypes] = useState<LookupItem[]>([]);
  const [allNodes, setAllNodes] = useState<LookupNode[]>([]);
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

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getSession(id);
      setDetail(result);
      setSelections(result.user_selections ?? {});
    } catch {
      setError("שגיאה בטעינת פרטי הייבוא");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void (async () => {
      try {
        const [dts, nodes] = await Promise.all([
          listDutyTypesForImport(),
          listNodesForImport(),
        ]);
        setAllDutyTypes(dts);
        setAllNodes(nodes);
      } catch {
        setError("שגיאה בטעינת נתוני בחירה");
      }
    })();
  }, []);

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
    group: "duty_types" | "exemption_types" | "shift_templates",
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
      setDetail(result);
      setSelections(result.user_selections ?? {});
    } catch {
      setError("שגיאה ברענון הנתונים");
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
      await load();
    } catch (err: unknown) {
      setConfirmError(extractDetail(err) ?? "שגיאה באישור הייבוא");
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
                  <th className="text-right p-3">יחידה</th>
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
                      <td className="p-3">{row.full_name}</td>
                      <td className="p-3">{row.personal_number}</td>
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
                  <th className="text-right p-3">תאריכים</th>
                  <th className="text-right p-3">נדרש</th>
                  <th className="text-right p-3">מכסות יחידה</th>
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
                        {row.start_date} – {row.end_date}
                      </td>
                      <td className="p-3">{row.required_count}</td>
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
                  <th className="text-right p-3">סוג תורנות</th>
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">ראשי</th>
                  <th className="text-right p-3">רזרבה</th>
                  <th className="text-right p-3">ימים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {shift_templates.map((row: ShiftTemplateRow) => {
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
                                        `shift_templates:${row.row}`,
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
                            {pendingPick?.rowKey === `shift_templates:${row.row}` &&
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
                      <td className="p-3">{row.name}</td>
                      <td className="p-3">{row.required_primary}</td>
                      <td className="p-3">{row.required_reserve}</td>
                      <td className="p-3">{row.days_of_week?.join(", ")}</td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("shift_templates", row)}
                              onChange={(e) =>
                                setRowAction(
                                  "shift_templates",
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

        {tab === "assignments" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">מ&quot;א</th>
                  <th className="text-right p-3">סוג תורנות</th>
                  <th className="text-right p-3">מיקום</th>
                  <th className="text-right p-3">תאריכים</th>
                  <th className="text-right p-3">רזרבה</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {assignments.map((row: AssignmentRow) => {
                  const canToggle =
                    row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.full_name}</td>
                      <td className="p-3">{row.personal_number}</td>
                      <td className="p-3">{row.duty_type_name}</td>
                      <td className="p-3">{row.duty_location_name}</td>
                      <td className="p-3">
                        {row.start_date} – {row.end_date}
                      </td>
                      <td className="p-3">{row.is_reserve ? "כן" : "לא"}</td>
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
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {duty_locations.map((row: DutyLocationRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.name}</td>
                      <td className="p-3">{row.base}</td>
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
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {hierarchy.map((row: HierarchyImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.name}</td>
                      <td className="p-3">{row.level}</td>
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
    </Layout>
  );
}
