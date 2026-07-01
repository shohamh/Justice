import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import Layout from "../components/Layout";
import DutyTypeFormModal from "../components/DutyTypeFormModal";
import AddRootNodeDialog from "../components/AddRootNodeDialog";
import HierarchyNodePickerModal from "../components/HierarchyNodePickerModal";
import { renameNode } from "../api/hierarchy";
import {
  type SessionDetail,
  type ConfirmSessionResult,
  type RowBase,
  getSession,
  reparseSession,
  saveSelections,
  confirmSession,
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

type TabKey = "soldiers" | "duty_shifts" | "shift_templates";

function extractDetail(err: unknown): string | undefined {
  return (err as { response?: { data?: { detail?: string } } })?.response?.data
    ?.detail;
}

function StatusChip({ action }: { action: ActionValue }) {
  return (
    <span
      className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_CHIP[action]}`}
    >
      {ACTION_LABEL[action]}
    </span>
  );
}

export default function ImportSessionReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("soldiers");
  const [selections, setSelections] = useState<Record<string, Record<string, string>>>({});
  const [confirming, setConfirming] = useState(false);
  const [confirmResult, setConfirmResult] = useState<ConfirmSessionResult | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  // dialog state
  const [dutyTypeModalOpen, setDutyTypeModalOpen] = useState(false);
  const [nodeCreateContext, setNodeCreateContext] = useState<{
    unresolvedName: string;
  } | null>(null);
  const [nodePickerContext, setNodePickerContext] = useState<{
    unresolvedName: string;
  } | null>(null);

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
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, []);

  const readOnly = detail ? detail.status !== "draft" : true;

  function setRowAction(group: TabKey, row: number, value: string) {
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

  async function handleNodePicked(pickedNodeId: string) {
    const context = nodePickerContext;
    setNodePickerContext(null);
    if (!context) return;
    try {
      await renameNode(pickedNodeId, context.unresolvedName);
      await handleReparse();
    } catch {
      setError("שגיאה בשינוי שם היחידה");
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

  function currentSelection(group: TabKey, row: RowBase): string {
    return selections[group]?.[String(row.row)] ?? row.action;
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

  const { soldiers, duty_shifts, shift_templates } = detail.parsed_state;

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
                  <th className="text-right p-3">מ"א</th>
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
                          <div className="flex items-center gap-2">
                            <span className="text-red-600">
                              {row.hierarchy_node_name}
                            </span>
                            {!readOnly && (
                              <>
                                <button
                                  className="text-indigo-600 hover:underline text-xs"
                                  onClick={() =>
                                    setNodeCreateContext({
                                      unresolvedName: row.hierarchy_node_name ?? "",
                                    })
                                  }
                                >
                                  צור יחידה
                                </button>
                                <button
                                  className="text-indigo-600 hover:underline text-xs"
                                  onClick={() =>
                                    setNodePickerContext({
                                      unresolvedName: row.hierarchy_node_name ?? "",
                                    })
                                  }
                                >
                                  שנה
                                </button>
                              </>
                            )}
                          </div>
                        ) : (
                          row.hierarchy_node_name
                        )}
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} />
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
                              <option value={row.action}>
                                {ACTION_LABEL[row.action]}
                              </option>
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
                          <div className="flex items-center gap-2">
                            <span className="text-red-600">
                              {row.duty_type_name}
                            </span>
                            {!readOnly && (
                              <button
                                className="text-indigo-600 hover:underline text-xs"
                                onClick={() => setDutyTypeModalOpen(true)}
                              >
                                צור סוג תורנות
                              </button>
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
                          {row.node_quotas.map((q, i) => (
                            <div key={i} className="flex items-center gap-2">
                              <span className={q.resolved ? "" : "text-red-600"}>
                                {q.node_name}:{q.count}
                              </span>
                              {!q.resolved && !readOnly && (
                                <>
                                  <button
                                    className="text-indigo-600 hover:underline text-xs"
                                    onClick={() =>
                                      setNodeCreateContext({
                                        unresolvedName: q.node_name,
                                      })
                                    }
                                  >
                                    צור
                                  </button>
                                  <button
                                    className="text-indigo-600 hover:underline text-xs"
                                    onClick={() =>
                                      setNodePickerContext({
                                        unresolvedName: q.node_name,
                                      })
                                    }
                                  >
                                    שנה
                                  </button>
                                </>
                              )}
                            </div>
                          ))}
                        </div>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} />
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
                              <option value={row.action}>
                                {ACTION_LABEL[row.action]}
                              </option>
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
                  <th className="text-right p-3">סוג</th>
                  <th className="text-right p-3">ימים</th>
                  <th className="text-right p-3">נדרש</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {shift_templates.map((row) => {
                  const canToggle =
                    row.action !== "error" && row.action !== "out_of_scope";
                  const unresolvedType = !row.resolved_duty_type_id;
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.name}</td>
                      <td className="p-3">
                        {unresolvedType ? (
                          <div className="flex items-center gap-2">
                            <span className="text-red-600">
                              {row.duty_type_name}
                            </span>
                            {!readOnly && (
                              <button
                                className="text-indigo-600 hover:underline text-xs"
                                onClick={() => setDutyTypeModalOpen(true)}
                              >
                                צור סוג תורנות
                              </button>
                            )}
                          </div>
                        ) : (
                          row.duty_type_name
                        )}
                      </td>
                      <td className="p-3">{row.days_of_week.join(",")}</td>
                      <td className="p-3">
                        {row.required_primary}+{row.required_reserve}
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} />
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
                              <option value={row.action}>
                                {ACTION_LABEL[row.action]}
                              </option>
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

      {dutyTypeModalOpen && (
        <DutyTypeFormModal
          onSaved={() => {
            setDutyTypeModalOpen(false);
            void handleReparse();
          }}
          onClose={() => setDutyTypeModalOpen(false)}
        />
      )}

      {nodeCreateContext && (
        <AddRootNodeDialog
          initialName={nodeCreateContext.unresolvedName}
          onCreated={() => {
            void handleReparse();
          }}
          onClose={() => setNodeCreateContext(null)}
        />
      )}

      {nodePickerContext && (
        <HierarchyNodePickerModal
          onPicked={(nodeId) => void handleNodePicked(nodeId)}
          onClose={() => setNodePickerContext(null)}
        />
      )}
    </Layout>
  );
}
