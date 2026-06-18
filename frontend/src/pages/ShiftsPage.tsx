import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../components/Layout";
import ShiftFormModal from "../components/ShiftFormModal";
import ShiftEditAssignmentsModal from "../components/ShiftEditAssignmentsModal";
import { BulkDeletePreview, BulkDeletePreviewShift, DutyShift, activateShift, bulkClearAssignments, bulkDeleteShifts, cancelShift, deleteShift, getBulkDeletePreview, listShifts } from "../api/shifts";
import { clearAllAssignments } from "../api/assignments";
import { DutyType, DutyLocation, listDutyTypes, listLocations } from "../api/dutyConfig";
import { DataTable, type ColDef } from "../components/DataTable";
import AlgorithmInlinePanel from "../components/AlgorithmInlinePanel";
import { listJobs } from "../api/algorithm";

const FILL_COLORS: Record<string, string> = {
  empty: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300",
  partial: "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
  full: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
};

type BulkAction = "clear" | "delete" | null;

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
          onClick={() => { if (window.confirm("לנקות את כל השיבוצים?")) { void clearAllAssignments().then(onClearedAll); } }}
          className="bg-red-600 text-white px-3 py-1.5 rounded text-sm hover:bg-red-700"
        >
          נקה את כל השיבוצים
        </button>
      </div>
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">ניקוי / מחיקה לפי טווח תאריכים</p>
      <div className="flex flex-wrap gap-4 items-end text-sm">
        <label className="flex items-center gap-2">
          <span className="text-gray-700 dark:text-gray-300">מתאריך</span>
          <input
            type="date"
            value={from}
            onChange={e => { setFrom(e.target.value); resetResult(); }}
            className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          />
        </label>
        <label className="flex items-center gap-2">
          <span className="text-gray-700 dark:text-gray-300">עד תאריך</span>
          <input
            type="date"
            value={to}
            onChange={e => { setTo(e.target.value); resetResult(); }}
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

export function ShiftsContent({ onJobSubmitted }: { onJobSubmitted?: (jobId: string) => void } = {}) {
  const { t } = useTranslation();
  const [shifts, setShifts] = useState<DutyShift[]>([]);
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
  const [locations, setLocations] = useState<DutyLocation[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editShift, setEditShift] = useState<DutyShift | null>(null);
  const [editAssignmentsShift, setEditAssignmentsShift] = useState<DutyShift | null>(null);
  const [selectedShiftIds, setSelectedShiftIds] = useState<string[]>([]);
  const [showAlgorithmPanel, setShowAlgorithmPanel] = useState(false);
  const [runningCount, setRunningCount] = useState(0);
  const [doneUnpublishedCount, setDoneUnpublishedCount] = useState(0);

  const refresh = useCallback(async () => {
    const [ss, dts, locs] = await Promise.all([
      listShifts({ date_from: dateFrom || undefined, date_to: dateTo || undefined }),
      listDutyTypes(),
      listLocations(),
    ]);
    setShifts(ss);
    setDutyTypes(dts);
    setLocations(locs);
  }, [dateFrom, dateTo]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    void listJobs(50, 0)
      .then((data) => {
        setRunningCount(data.items.filter((j) => j.status === "pending" || j.status === "running").length);
        setDoneUnpublishedCount(data.items.filter((j) => j.status === "done").length);
      })
      .catch(() => {});
  }, []);

  const handleCancel = useCallback(async (shift: DutyShift) => {
    if (!window.confirm(t("shifts.confirm_cancel"))) return;
    await cancelShift(shift.id);
    await refresh();
  }, [t, refresh]);

  const handleActivate = useCallback(async (shift: DutyShift) => {
    await activateShift(shift.id);
    await refresh();
  }, [refresh]);

  const handleDelete = useCallback(async (shift: DutyShift) => {
    if (!window.confirm(t("shifts.confirm_delete_permanent"))) return;
    try {
      await deleteShift(shift.id);
      await refresh();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (detail === "has_assignments") alert(t("shifts.has_assignments_error"));
    }
  }, [t, refresh]);

  const dtName = useCallback((id: string) => dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8), [dutyTypes]);
  const locName = useCallback((id: string) => locations.find(l => l.id === id)?.name ?? id.slice(0, 8), [locations]);

  const shiftCols: ColDef<DutyShift>[] = useMemo(() => [
    {
      id: "select",
      header: "",
      sortValue: (s) => s.fill_status === "full" ? 2 : selectedShiftIds.includes(s.id) ? 0 : 1,
      cell: (s) => (
        <input
          type="checkbox"
          checked={selectedShiftIds.includes(s.id)}
          disabled={s.fill_status === "full"}
          className={s.fill_status === "full" ? "opacity-30 cursor-not-allowed" : ""}
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
  ], [selectedShiftIds, t, dtName, locName, setEditShift, setEditAssignmentsShift, setSelectedShiftIds, handleCancel, handleActivate, handleDelete]);

  return (
    <>
      <BulkDeletePanel onDeleted={refresh} onClearedAll={refresh} />

      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl" data-testid="shifts-page">
        <div className="flex flex-wrap justify-between items-center gap-2">
          <h2 className="text-xl font-semibold">{t("shifts.title")}</h2>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setShowAlgorithmPanel(p => !p)}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                showAlgorithmPanel
                  ? "bg-indigo-600 text-white hover:bg-indigo-700"
                  : "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-200 dark:hover:bg-indigo-800"
              }`}
            >
              שיבוץ אוטומטי
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700"
            >
              {t("shifts.create")}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-x-4 gap-y-2 items-center text-sm">
          <label className="flex items-center gap-2">
            {t("shifts.filter_from")}
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          </label>
          <label className="flex items-center gap-2">
            {t("shifts.filter_to")}
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          </label>
          {shifts.length > 0 && (
            <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              <button
                type="button"
                onClick={() => setSelectedShiftIds(shifts.filter(s => s.fill_status !== "full").map(s => s.id))}
                className="text-blue-600 dark:text-blue-400 hover:underline"
              >
                בחר הכל ({shifts.filter(s => s.fill_status !== "full").length})
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
              {runningCount} ריצות פעילות
            </span>
          )}
          {doneUnpublishedCount > 0 && (
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300">
              {doneUnpublishedCount} הושלמו, ממתינות לפרסום
            </span>
          )}
        </div>

        {(() => {
          const algorithmPanel = showAlgorithmPanel ? (
            <AlgorithmInlinePanel
              selectedShiftIds={selectedShiftIds}
              onJobSubmitted={(jobId) => {
                onJobSubmitted?.(jobId);
                setShowAlgorithmPanel(false);
                setSelectedShiftIds([]);
              }}
              onClose={() => setShowAlgorithmPanel(false)}
            />
          ) : null;

          return (
            <>
              {algorithmPanel}
              <DataTable
                columns={shiftCols}
                data={shifts}
                rowClassName={(s) => s.status === "cancelled" ? "opacity-50" : ""}
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
    </>
  );
}

export default function ShiftsPage() {
  return <Layout><ShiftsContent /></Layout>;
}
