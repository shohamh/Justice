import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import ShiftFormModal from "../components/ShiftFormModal";
import ShiftEditAssignmentsModal from "../components/ShiftEditAssignmentsModal";
import ShiftTemplateFormModal from "../components/ShiftTemplateFormModal";
import SetResponsibleUnitsModal from "../components/SetResponsibleUnitsModal";
import SplitInUnitModal from "../components/SplitInUnitModal";
import AutoAssignResponsibilityModal from "../components/AutoAssignResponsibilityModal";
import { BulkDeletePreview, BulkDeletePreviewShift, DutyShift, activateShift, bulkClearAssignments, bulkDeleteShifts, cancelShift, clearShiftAssignments, deleteShift, getBulkDeletePreview, listShifts } from "../api/shifts";
import { clearAllAssignments } from "../api/assignments";
import { listDutyTypes, listLocations } from "../api/dutyConfig";
import { fetchFullTree, NodeDTO } from "../api/hierarchy";
import HierarchyNodeFilter from "../components/HierarchyNodeFilter";
import { type ColDef } from "../components/DataTable";
import AlgorithmInlinePanel from "../components/AlgorithmInlinePanel";
import { listJobs } from "../api/algorithm";
import { ShiftTemplate, listTemplates } from "../api/shiftTemplates";
import DateInput from "../components/DateInput";
import { PlanningTable } from "../components/planning";

const FILL_COLORS: Record<string, string> = {
  empty: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300",
  partial: "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
  full: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
};

type BulkAction = "clearAll" | "clear" | "delete" | null;

function Spinner() {
  return (
    <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
    </svg>
  );
}

function BulkDeletePanel({ onDeleted, onClearedAll }: { onDeleted: () => void; onClearedAll: () => void }) {
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [preview, setPreview] = useState<BulkDeletePreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<BulkAction>(null);
  const [error, setError] = useState<string | null>(null);
  const [resultMsg, setResultMsg] = useState<string | null>(null);

  function resetResult() { setPreview(null); setResultMsg(null); setError(null); }

  async function handlePreview() {
    if (!from || !to) return;
    setLoading(true);
    setError(null);
    setResultMsg(null);
    try {
      setPreview(await getBulkDeletePreview(from, to));
    } catch {
      setError("שגיאה בטעינת תצוגה מקדימה");
    } finally {
      setLoading(false);
    }
  }

  async function handleClearAll() {
    if (!window.confirm("לנקות את כל השיבוצים?")) return;
    setBusy("clearAll");
    setError(null);
    try {
      await clearAllAssignments();
      setResultMsg("כל השיבוצים נוקו בהצלחה ✓");
      onClearedAll();
    } catch {
      setError("שגיאה בניקוי שיבוצים");
    } finally {
      setBusy(null);
    }
  }

  async function handleClearAssignments() {
    if (!preview || preview.assignment_count === 0) return;
    if (!window.confirm(`לנקות ${preview.assignment_count} שיבוצים מ-${preview.shift_count} משמרות? המשמרות עצמן יישארו.`)) return;
    setBusy("clear");
    setError(null);
    try {
      const r = await bulkClearAssignments(from, to);
      setResultMsg(`נוקו ${r.cleared_assignments} שיבוצים. המשמרות נשמרו.`);
      setPreview(null);
      onDeleted();
    } catch {
      setError("שגיאה בניקוי שיבוצים");
    } finally {
      setBusy(null);
    }
  }

  async function handleDeleteShifts() {
    if (!preview || preview.shift_count === 0) return;
    if (!window.confirm(`למחוק ${preview.shift_count} משמרות ו-${preview.assignment_count} שיבוצים לצמיתות?`)) return;
    setBusy("delete");
    setError(null);
    try {
      const r = await bulkDeleteShifts(from, to);
      setResultMsg(`נמחקו ${r.deleted_shifts} משמרות ו-${r.deleted_assignments} שיבוצים.`);
      setPreview(null);
      onDeleted();
    } catch {
      setError("שגיאה במחיקה");
    } finally {
      setBusy(null);
    }
  }

  const canPreview = !!from && !!to && from <= to;

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex w-full justify-between items-center gap-2 text-right"
      >
        <span className="text-xl font-semibold">ניקוי שיבוצים</span>
        <span className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-sm px-2 py-1">
          {open ? "▲" : "▼"}
        </span>
      </button>

      {open && <div className="space-y-4">
      <div className="flex items-center justify-between py-2 border-b dark:border-gray-600">
        <span className="text-sm text-gray-600 dark:text-gray-300">נקה את כל השיבוצים מכל המשמרות</span>
        <button
          type="button"
          onClick={() => { void handleClearAll(); }}
          disabled={!!busy}
          className="bg-red-600 text-white px-3 py-1.5 rounded text-sm hover:bg-red-700 disabled:opacity-50 flex items-center gap-2"
        >
          {busy === "clearAll" && <Spinner />}
          {busy === "clearAll" ? "מנקה..." : "נקה את כל השיבוצים"}
        </button>
      </div>
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">ניקוי / מחיקה לפי טווח תאריכים</p>
      <div className="flex flex-wrap gap-4 items-end text-sm">
        <label className="flex items-center gap-2">
          <span className="text-gray-700 dark:text-gray-300">מתאריך</span>
          <DateInput
            value={from}
            onChange={iso => { setFrom(iso); resetResult(); }}
            max={to || undefined}
            className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          />
        </label>
        <label className="flex items-center gap-2">
          <span className="text-gray-700 dark:text-gray-300">עד תאריך</span>
          <DateInput
            value={to}
            onChange={iso => { setTo(iso); resetResult(); }}
            min={from || undefined}
            className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          />
        </label>
        <button
          type="button"
          onClick={handlePreview}
          disabled={!canPreview || loading}
          className="bg-gray-600 text-white px-3 py-1.5 rounded text-sm hover:bg-gray-700 disabled:opacity-40"
        >
          {loading ? "טוען..." : "תצוגה מקדימה"}
        </button>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      {resultMsg && (
        <div className="text-sm text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950 rounded p-3">
          {resultMsg}
        </div>
      )}

      {preview && (
        <div className="space-y-3">
          {/* Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center text-sm">
            {[
              { label: "משמרות", value: preview.shift_count, color: "text-red-700 dark:text-red-400" },
              { label: "שיבוצים", value: preview.assignment_count, color: "text-orange-700 dark:text-orange-400" },
              { label: "החלפות", value: preview.swap_count, color: "text-amber-700 dark:text-amber-400" },
              { label: "שחרורים", value: preview.dismissal_count, color: "text-yellow-700 dark:text-yellow-400" },
            ].map(({ label, value, color }) => (
              <div key={label} className="bg-gray-50 dark:bg-gray-700 rounded p-3">
                <div className={`text-2xl font-bold ${color}`}>{value}</div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">{label}</div>
              </div>
            ))}
          </div>

          {/* Shift list */}
          {preview.shifts.length > 0 && (
            <div className="max-h-56 overflow-y-auto border dark:border-gray-600 rounded">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 dark:bg-gray-700 sticky top-0">
                  <tr>
                    <th className="text-right p-2 font-medium">סוג תורנות</th>
                    <th className="text-right p-2 font-medium">מיקום</th>
                    <th className="text-right p-2 font-medium">התחלה</th>
                    <th className="text-right p-2 font-medium">סיום</th>
                    <th className="text-right p-2 font-medium">נדרש</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.shifts.map((s: BulkDeletePreviewShift) => (
                    <tr key={s.id} className="border-t dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700">
                      <td className="p-2">{s.duty_type_name}</td>
                      <td className="p-2">{s.duty_location_name}</td>
                      <td className="p-2" dir="ltr">{s.start_date}</td>
                      <td className="p-2" dir="ltr">{s.end_date}</td>
                      <td className="p-2">{s.required_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {preview.shift_count === 0 ? (
            <p className="text-sm text-gray-500">אין משמרות בטווח זה.</p>
          ) : (
            <div className="flex flex-wrap gap-3 pt-1">
              <button
                type="button"
                onClick={handleClearAssignments}
                disabled={!!busy || preview.assignment_count === 0}
                className="bg-orange-500 text-white px-4 py-2 rounded text-sm font-medium hover:bg-orange-600 disabled:opacity-40 flex items-center gap-2"
              >
                {busy === "clear" && <Spinner />}
                {busy === "clear" ? "מנקה..." : `נקה שיבוצים בלבד (${preview.assignment_count})`}
              </button>
              <button
                type="button"
                onClick={handleDeleteShifts}
                disabled={!!busy}
                className="bg-red-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-red-700 disabled:opacity-40 flex items-center gap-2"
              >
                {busy === "delete" && <Spinner />}
                {busy === "delete" ? "מוחק..." : `מחק משמרות ושיבוצים (${preview.shift_count})`}
              </button>
            </div>
          )}
        </div>
      )}
      </div>}
    </section>
  );
}

type BulkOp = "clear" | "cancel" | "delete" | null;

function BulkActionBar({ selectedShifts, onDone, onAutoAssign, showAlgorithmPanel, dtName, locName }: { selectedShifts: DutyShift[]; onDone: () => void; onAutoAssign?: () => void; showAlgorithmPanel?: boolean; dtName: (id: string) => string; locName: (id: string) => string }) {
  const [busy, setBusy] = useState<BulkOp>(null);
  const [openModal, setOpenModal] = useState<"setResponsible" | "splitInUnit" | "autoAssignResponsibility" | null>(null);

  async function handleClear() {
    const assignmentCount = selectedShifts.reduce((acc, s) => acc + (s.assigned_count ?? 0), 0);
    if (!window.confirm(`לנקות שיבוצים מ-${selectedShifts.length} משמרות (${assignmentCount} שיבוצים)?`)) return;
    setBusy("clear");
    try {
      await Promise.all(selectedShifts.map(s => clearShiftAssignments(s.id)));
      onDone();
    } finally {
      setBusy(null);
    }
  }

  async function handleCancel() {
    const active = selectedShifts.filter(s => s.status === "active");
    if (active.length === 0) return;
    if (!window.confirm(`לבטל ${active.length} משמרות פעילות?`)) return;
    setBusy("cancel");
    try {
      await Promise.all(active.map(s => cancelShift(s.id)));
      onDone();
    } finally {
      setBusy(null);
    }
  }

  async function handleDelete() {
    const withAssignments = selectedShifts.filter(s => (s.assigned_count ?? 0) > 0);
    const toDelete = selectedShifts.filter(s => (s.assigned_count ?? 0) === 0);
    let msg = `למחוק ${toDelete.length} משמרות לצמיתות?`;
    if (withAssignments.length > 0)
      msg = `${withAssignments.length} משמרות עם שיבוצים יידלגו. למחוק ${toDelete.length} משמרות ריקות לצמיתות?`;
    if (toDelete.length === 0) { alert("כל המשמרות הנבחרות מכילות שיבוצים ולא ניתן למחוק אותן."); return; }
    if (!window.confirm(msg)) return;
    setBusy("delete");
    try {
      await Promise.allSettled(toDelete.map(s => deleteShift(s.id)));
      onDone();
    } finally {
      setBusy(null);
    }
  }

  const activeCount = selectedShifts.filter(s => s.status === "active").length;

  return (
    <div className="flex flex-col gap-2 px-4 py-2.5 bg-indigo-50 dark:bg-indigo-950 rounded-lg border border-indigo-200 dark:border-indigo-800" dir="rtl">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium text-indigo-700 dark:text-indigo-300">{selectedShifts.length} נבחרו</span>
        {onAutoAssign && (
          <button
            type="button"
            onClick={onAutoAssign}
            className={`px-5 py-2 rounded text-base font-semibold transition-colors ${
              showAlgorithmPanel
                ? "bg-indigo-600 text-white hover:bg-indigo-700"
                : "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-200 dark:hover:bg-indigo-800"
            }`}
          >
            שיבוץ אוטומטי
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setOpenModal("setResponsible")}
          className="px-3 py-1 rounded text-sm font-medium bg-teal-600 text-white hover:bg-teal-700"
        >
          קביעת יחידה אחראית
        </button>
        <button
          type="button"
          onClick={() => setOpenModal("splitInUnit")}
          className="px-3 py-1 rounded text-sm font-medium bg-teal-600 text-white hover:bg-teal-700"
        >
          פיצול בתוך היחידה
        </button>
        <button
          type="button"
          onClick={() => setOpenModal("autoAssignResponsibility")}
          className="px-3 py-1 rounded text-sm font-medium bg-teal-700 text-white hover:bg-teal-800"
        >
          שיבוץ אוטומטי של אחריות יחידה
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => { void handleClear(); }}
          disabled={!!busy}
          className="flex items-center gap-1 px-3 py-1 rounded text-sm font-medium bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-40"
        >
          {busy === "clear" && <Spinner />}
          {busy === "clear" ? "מנקה..." : "נקה שיבוצים"}
        </button>
        <button
          type="button"
          onClick={() => { void handleCancel(); }}
          disabled={!!busy || activeCount === 0}
          className="flex items-center gap-1 px-3 py-1 rounded text-sm font-medium bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-40"
        >
          {busy === "cancel" && <Spinner />}
          {busy === "cancel" ? "מבטל..." : `בטל משמרות${activeCount < selectedShifts.length ? ` (${activeCount})` : ""}`}
        </button>
        <button
          type="button"
          onClick={() => { void handleDelete(); }}
          disabled={!!busy}
          className="flex items-center gap-1 px-3 py-1 rounded text-sm font-medium bg-red-600 text-white hover:bg-red-700 disabled:opacity-40"
        >
          {busy === "delete" && <Spinner />}
          {busy === "delete" ? "מוחק..." : "מחק משמרות"}
        </button>
      </div>
      {openModal === "setResponsible" && (
        <SetResponsibleUnitsModal
          selectedShifts={selectedShifts}
          onApplied={() => { setOpenModal(null); onDone(); }}
          onClose={() => setOpenModal(null)}
        />
      )}
      {openModal === "splitInUnit" && (
        <SplitInUnitModal
          selectedShifts={selectedShifts}
          onApplied={() => { setOpenModal(null); onDone(); }}
          onClose={() => setOpenModal(null)}
          dtName={dtName}
          locName={locName}
        />
      )}
      {openModal === "autoAssignResponsibility" && (
        <AutoAssignResponsibilityModal
          selectedShifts={selectedShifts}
          onApplied={() => { setOpenModal(null); onDone(); }}
          onClose={() => setOpenModal(null)}
          dtName={dtName}
          locName={locName}
        />
      )}
    </div>
  );
}

export function ShiftsContent({ onJobSubmitted }: { onJobSubmitted?: (jobId: string) => void } = {}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const autoAssignSectionRef = useRef<HTMLDivElement>(null);
  const [nodeFilterIds, setNodeFilterIds] = useState<string[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editShift, setEditShift] = useState<DutyShift | null>(null);
  const [editAssignmentsShift, setEditAssignmentsShift] = useState<DutyShift | null>(null);
  const [selectedShiftIds, setSelectedShiftIds] = useState<string[]>([]);
  const [showAlgorithmPanel, setShowAlgorithmPanel] = useState(false);
  const [viewTemplate, setViewTemplate] = useState<ShiftTemplate | null>(null);

  const shiftsParams = useMemo(
    () => ({ date_from: dateFrom || undefined, date_to: dateTo || undefined }),
    [dateFrom, dateTo],
  );

  const shiftsQuery = useQuery({
    queryKey: queryKeys.shifts(shiftsParams),
    queryFn: () => listShifts(shiftsParams),
  });
  const shifts = shiftsQuery.data ?? [];

  const dutyTypesQuery = useQuery({ queryKey: queryKeys.dutyTypes(), queryFn: listDutyTypes });
  const dutyTypes = useMemo(() => dutyTypesQuery.data ?? [], [dutyTypesQuery.data]);

  const locationsQuery = useQuery({ queryKey: queryKeys.dutyLocations(), queryFn: listLocations });
  const locations = useMemo(() => locationsQuery.data ?? [], [locationsQuery.data]);

  const templatesQuery = useQuery({ queryKey: queryKeys.shiftTemplatesAll(), queryFn: () => listTemplates(true) });
  const templates = useMemo(() => templatesQuery.data ?? [], [templatesQuery.data]);

  const treeQuery = useQuery({ queryKey: queryKeys.hierarchyTree(), queryFn: fetchFullTree });
  const nodeTree = useMemo(() => treeQuery.data ?? [], [treeQuery.data]);
  const nodeMap = useMemo(() => {
    const map = new Map<string, string>();
    function walk(nodes: NodeDTO[]) {
      for (const n of nodes) {
        map.set(n.id, n.name);
        if (n.children) walk(n.children);
      }
    }
    walk(nodeTree);
    return map;
  }, [nodeTree]);

  const jobsQuery = useQuery({ queryKey: queryKeys.algorithmJobs(50, 0), queryFn: () => listJobs(50, 0) });
  const runningCount = useMemo(
    () => (jobsQuery.data?.items ?? []).filter((j) => j.status === "pending" || j.status === "running").length,
    [jobsQuery.data],
  );
  const doneUnpublishedCount = useMemo(
    () => (jobsQuery.data?.items ?? []).filter((j) => j.status === "done").length,
    [jobsQuery.data],
  );

  const invalidateShifts = useCallback(
    () => queryClient.invalidateQueries({ queryKey: queryKeys.shiftsList() }),
    [queryClient],
  );

  const refresh = useCallback(async () => {
    await invalidateShifts();
  }, [invalidateShifts]);

  useEffect(() => {
    if (selectedShiftIds.length === 0) setShowAlgorithmPanel(false);
  }, [selectedShiftIds.length]);

  useEffect(() => {
    if (searchParams.get("autoAssign") === "1") {
      setShowAlgorithmPanel(true);
      setSearchParams({}, { replace: true });
      setTimeout(() => autoAssignSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 100);
    }
  }, [searchParams, setSearchParams]);

  const handleCancel = useCallback(async (shift: DutyShift) => {
    if (!window.confirm(t("shifts.confirm_cancel"))) return;
    await cancelShift(shift.id);
    await invalidateShifts();
  }, [t, invalidateShifts]);

  const handleActivate = useCallback(async (shift: DutyShift) => {
    await activateShift(shift.id);
    await invalidateShifts();
  }, [invalidateShifts]);

  const handleDelete = useCallback(async (shift: DutyShift) => {
    if (!window.confirm(t("shifts.confirm_delete_permanent"))) return;
    try {
      await deleteShift(shift.id);
      await invalidateShifts();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (detail === "has_assignments") alert(t("shifts.has_assignments_error"));
    }
  }, [t, invalidateShifts]);

  const dtName = useCallback((id: string) => dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8), [dutyTypes]);
  const locName = useCallback((id: string) => locations.find(l => l.id === id)?.name ?? id.slice(0, 8), [locations]);
  const eligibleUnitsLabel = useCallback((s: DutyShift) => {
    if (!s.eligible_node_ids?.length) return "כולם";
    return s.eligible_node_ids.map(id => nodeMap.get(id) ?? id.slice(0, 8)).join(", ");
  }, [nodeMap]);

  const shiftCols: ColDef<DutyShift>[] = useMemo(() => [
    {
      id: "select",
      header: "",
      sortValue: (s) => selectedShiftIds.includes(s.id) ? 0 : 1,
      cell: (s) => (
        <input
          type="checkbox"
          checked={selectedShiftIds.includes(s.id)}
          onChange={() =>
            setSelectedShiftIds(prev =>
              prev.includes(s.id) ? prev.filter(id => id !== s.id) : [...prev, s.id]
            )
          }
          onClick={e => e.stopPropagation()}
          aria-label="בחר משמרת"
        />
      ),
    },
    {
      id: "duty_type",
      header: t("shifts.duty_type"),
      cell: (s) => dtName(s.duty_type_id),
      sortValue: (s) => dtName(s.duty_type_id),
      filterValue: (s) => dtName(s.duty_type_id),
    },
    {
      id: "location",
      header: t("shifts.location"),
      cell: (s) => locName(s.duty_location_id),
      sortValue: (s) => locName(s.duty_location_id),
      filterValue: (s) => locName(s.duty_location_id),
    },
    {
      id: "eligible_units",
      header: t("shifts.eligible_units"),
      cell: (s) => eligibleUnitsLabel(s),
      sortValue: (s) => eligibleUnitsLabel(s),
      filterValue: (s) => eligibleUnitsLabel(s),
      customColumnFilter: {
        isActive: nodeFilterIds.length > 0,
        dropdown: (
          <HierarchyNodeFilter
            nodes={nodeTree}
            selected={nodeFilterIds}
            onChange={setNodeFilterIds}
          />
        ),
        fn: (s) =>
          nodeFilterIds.length === 0 ||
          (s.eligible_node_ids?.length
            ? s.eligible_node_ids.some((id) => nodeFilterIds.includes(id))
            : true),
      },
    },
    {
      id: "start_date",
      header: t("shifts.start_date"),
      cell: (s) => s.start_date,
      sortValue: (s) => s.start_date,
    },
    {
      id: "end_date",
      header: t("shifts.end_date"),
      cell: (s) => s.end_date,
      sortValue: (s) => s.end_date,
    },
    {
      id: "required",
      header: t("shifts.required_count"),
      cell: (s) => s.required_count,
      sortValue: (s) => s.required_count,
    },
    {
      id: "assigned",
      header: t("shifts.assigned_count"),
      cell: (s) => (s.assigned_count ?? 0) - (s.reserve_assigned_count ?? 0),
      sortValue: (s) => (s.assigned_count ?? 0) - (s.reserve_assigned_count ?? 0),
    },
    {
      id: "reserve_needed",
      header: t("shifts.reserve_needed"),
      cell: (s) => s.calculated_reserve_count ?? 0,
      sortValue: (s) => s.calculated_reserve_count ?? 0,
    },
    {
      id: "reserve_assigned",
      header: t("shifts.reserve_assigned"),
      cell: (s) => s.reserve_assigned_count ?? 0,
      sortValue: (s) => s.reserve_assigned_count ?? 0,
    },
    {
      id: "fill_status",
      header: t("shifts.status"),
      cell: (s) => (
        <span className={`px-2 py-0.5 rounded text-xs font-medium ${FILL_COLORS[s.fill_status]}`}>
          {t(`shifts.fill_${s.fill_status}`)}
        </span>
      ),
      sortValue: (s) => s.fill_status,
      filterValue: (s) => t(`shifts.fill_${s.fill_status}`),
    },
    {
      id: "weapon_ineligible",
      header: "",
      cell: (s) =>
        s.ineligible_count > 0 ? (
          <span
            title={`${s.ineligible_count} חייל/ים לא כשירים מבחינת הכשרת נשק`}
            className="text-amber-500 dark:text-amber-400"
          >
            ⚠️
          </span>
        ) : null,
      sortValue: (s) => s.ineligible_count,
    },
    {
      id: "shift_status",
      header: t("shifts.shift_status"),
      cell: (s) => s.status === "cancelled"
        ? (
          <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400">
            {t("shifts.cancelled")}
          </span>
        )
        : (
          <span className="px-2 py-0.5 rounded text-xs font-medium bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300">
            {t("shifts.active")}
          </span>
        ),
      sortValue: (s) => s.status,
      filterValue: (s) => s.status === "cancelled" ? t("shifts.cancelled") : t("shifts.active"),
    },
    {
      id: "template",
      header: "תבנית",
      cell: (s) => s.generated_from_template_id ? (
        <button
          type="button"
          onClick={() => {
            const tmpl = templates.find(t => t.id === s.generated_from_template_id);
            if (tmpl) setViewTemplate(tmpl);
          }}
          className="text-blue-600 dark:text-blue-400 underline hover:text-blue-800 dark:hover:text-blue-300 text-xs text-right"
        >
          {s.generated_from_template_name ?? "תבנית"}
        </button>
      ) : null,
      sortValue: (s) => s.generated_from_template_name ?? "",
      filterValue: (s) => s.generated_from_template_name ?? "",
    },
    {
      id: "actions",
      header: "",
      minWidth: 260,
      cell: (s) => (
        <span className="flex gap-1 items-center">
          <button
            type="button"
            onClick={() => setEditShift(s)}
            title={t("shifts.edit")}
            className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-300 hover:bg-blue-200 dark:hover:bg-blue-800"
          >
            ✏️ עריכה
          </button>
          {s.status === "active" && (
            <button
              type="button"
              onClick={() => setEditAssignmentsShift(s)}
              title="ערוך שיבוצים"
              className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-indigo-100 dark:bg-indigo-900/40 text-indigo-800 dark:text-indigo-300 hover:bg-indigo-200 dark:hover:bg-indigo-800"
            >
              🛠️ שיבוצים
            </button>
          )}
          {s.status === "cancelled" ? (
            <button
              type="button"
              onClick={() => handleActivate(s)}
              title={t("shifts.activate")}
              className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-300 hover:bg-green-200 dark:hover:bg-green-800"
            >
              ▶️ הפעלה
            </button>
          ) : (
            <button
              type="button"
              onClick={() => handleCancel(s)}
              title={t("shifts.cancel")}
              className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-800"
            >
              🚫 ביטול
            </button>
          )}
          <button
            type="button"
            onClick={() => handleDelete(s)}
            title={t("shifts.delete_tooltip")}
            className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-800 disabled:opacity-40"
            disabled={s.assigned_count > 0}
          >
            🗑️ מחיקה
          </button>
        </span>
      ),
    },
  ], [selectedShiftIds, t, dtName, locName, eligibleUnitsLabel, nodeFilterIds, nodeTree, setNodeFilterIds, setEditShift, setEditAssignmentsShift, setSelectedShiftIds, handleCancel, handleActivate, handleDelete, templates, setViewTemplate]);

  return (
    <>
      <BulkDeletePanel onDeleted={refresh} onClearedAll={refresh} />

      <section ref={autoAssignSectionRef} className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl" data-testid="shifts-page">
        <div className="flex flex-wrap justify-between items-center gap-2">
          <h2 className="text-xl font-semibold">{t("shifts.title")}</h2>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700"
          >
            {t("shifts.create")}
          </button>
        </div>

        <div className="flex flex-wrap gap-x-4 gap-y-2 items-center text-sm">
          <label className="flex items-center gap-2">
            {t("shifts.filter_from")}
            <DateInput value={dateFrom} onChange={iso => { setDateFrom(iso); if (iso && dateTo && iso > dateTo) setDateTo(iso); }} max={dateTo || undefined} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          </label>
          <label className="flex items-center gap-2">
            {t("shifts.filter_to")}
            <DateInput value={dateTo} onChange={iso => { setDateTo(iso); if (iso && dateFrom && iso < dateFrom) setDateFrom(iso); }} min={dateFrom || undefined} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          </label>
          {shifts.length > 0 && (
            <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              <button
                type="button"
                onClick={() => setSelectedShiftIds(shifts.map(s => s.id))}
                className="text-blue-600 dark:text-blue-400 hover:underline"
              >
                בחר הכל ({shifts.length})
              </button>
              {selectedShiftIds.length > 0 && (
                <>
                  <span>·</span>
                  <button
                    type="button"
                    onClick={() => setSelectedShiftIds([])}
                    className="text-blue-600 dark:text-blue-400 hover:underline"
                  >
                    בטל בחירה
                  </button>
                  <span className="text-indigo-600 dark:text-indigo-300 font-medium">
                    {selectedShiftIds.length} נבחרו
                  </span>
                </>
              )}
            </div>
          )}
        </div>

        <div className="flex gap-2 mb-2 flex-wrap" dir="rtl">
          {runningCount > 0 && (
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300">
              {runningCount} {t("shifts.algorithm_running_badge")}
            </span>
          )}
          {doneUnpublishedCount > 0 && (
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300">
              {doneUnpublishedCount} {t("shifts.algorithm_done_badge")}
            </span>
          )}
        </div>

        {selectedShiftIds.length > 0 && (
          <BulkActionBar
            selectedShifts={shifts.filter(s => selectedShiftIds.includes(s.id))}
            onDone={() => { setSelectedShiftIds([]); void refresh(); }}
            onAutoAssign={() => setShowAlgorithmPanel(p => !p)}
            showAlgorithmPanel={showAlgorithmPanel}
            dtName={dtName}
            locName={locName}
          />
        )}

        {(() => {
          const fullSelectedIds = shifts
            .filter(s => s.fill_status === "full" && selectedShiftIds.includes(s.id))
            .map(s => s.id);
          const algorithmShiftIds = selectedShiftIds.filter(id => !fullSelectedIds.includes(id));

          const algorithmPanel = showAlgorithmPanel ? (
            <>
              {fullSelectedIds.length > 0 && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 text-sm" dir="rtl">
                  <span className="text-amber-800 dark:text-amber-200">
                    {fullSelectedIds.length} משמרות מלאות נבחרו — הן לא ישובצו אוטומטית.
                  </span>
                  <button
                    type="button"
                    onClick={() => setSelectedShiftIds(prev => prev.filter(id => !fullSelectedIds.includes(id)))}
                    className="text-amber-700 dark:text-amber-300 underline hover:no-underline text-xs whitespace-nowrap"
                  >
                    הסר מהבחירה
                  </button>
                </div>
              )}
              <AlgorithmInlinePanel
                selectedShiftIds={algorithmShiftIds}
                onJobSubmitted={(jobId) => {
                  onJobSubmitted?.(jobId);
                  setShowAlgorithmPanel(false);
                  setSelectedShiftIds([]);
                }}
                onClose={() => setShowAlgorithmPanel(false)}
              />
            </>
          ) : null;

          return (
            <>
              {algorithmPanel}
              <PlanningTable<DutyShift>
                columns={shiftCols.map(column => ({
                  key: column.id,
                  label: column.header,
                  render: column.cell,
                  sortValue: column.sortValue,
                  filterValue: column.filterValue,
                  columnFilter: column.columnFilter,
                  customColumnFilter: column.customColumnFilter,
                  minWidth: column.minWidth,
                  sortDescFirst: column.sortDescFirst,
                }))}
                rows={shifts}
                getRowId={shift => shift.id}
                getRowLabel={shift => `${dtName(shift.duty_type_id)} ${shift.start_date}`}
                onRowClick={setEditShift}
                rowClassName={shift => shift.status === "cancelled" ? "opacity-50" : ""}
                filterPlaceholder={t("table.filter_placeholder")}
                emptyMessage="אין משמרות"
              />
            </>
          );
        })()}
      </section>

      {showCreate && (
        <ShiftFormModal
          dutyTypes={dutyTypes}
          locations={locations}
          onSaved={async () => { setShowCreate(false); await refresh(); }}
          onClose={() => setShowCreate(false)}
        />
      )}
      {editShift && (
        <ShiftFormModal
          dutyTypes={dutyTypes}
          locations={locations}
          existing={editShift}
          onSaved={async () => { setEditShift(null); await refresh(); }}
          onClose={() => setEditShift(null)}
        />
      )}
      {editAssignmentsShift && (
        <ShiftEditAssignmentsModal
          shift={editAssignmentsShift}
          dutyTypes={dutyTypes}
          onSaved={async () => { setEditAssignmentsShift(null); await refresh(); }}
          onClose={() => setEditAssignmentsShift(null)}
        />
      )}
      {viewTemplate && (
        <ShiftTemplateFormModal
          dutyTypes={dutyTypes}
          locations={locations}
          initial={viewTemplate}
          onSubmit={async () => {
            setViewTemplate(null);
            await Promise.all([
              invalidateShifts(),
              queryClient.invalidateQueries({ queryKey: queryKeys.shiftTemplatesAll() }),
            ]);
          }}
          onClose={() => setViewTemplate(null)}
        />
      )}
    </>
  );
}

export default function ShiftsPage() {
  return <Layout><ShiftsContent /></Layout>;
}
