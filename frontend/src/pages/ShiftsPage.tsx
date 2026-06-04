import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../components/Layout";
import ShiftFormModal from "../components/ShiftFormModal";
import { DutyShift, clearShiftAssignments, deleteShift, listShifts } from "../api/shifts";
import { clearAllAssignments } from "../api/assignments";
import { DutyType, DutyLocation, listDutyTypes, listLocations } from "../api/dutyConfig";
import { DataTable, type ColDef } from "../components/DataTable";

const FILL_COLORS: Record<string, string> = {
  empty: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300",
  partial: "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
  full: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
};

export function ShiftsContent() {
  const { t } = useTranslation();
  const [shifts, setShifts] = useState<DutyShift[]>([]);
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
  const [locations, setLocations] = useState<DutyLocation[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editShift, setEditShift] = useState<DutyShift | null>(null);

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

  async function handleClearAll() {
    if (!window.confirm(t("shifts.confirm_clear_all"))) return;
    await clearAllAssignments();
    await refresh();
  }

  async function handleClearAssignments(shift: DutyShift) {
    if (!window.confirm(t("shifts.confirm_clear_assignments"))) return;
    await clearShiftAssignments(shift.id);
    await refresh();
  }

  async function handleDelete(shift: DutyShift) {
    if (!window.confirm(t("shifts.confirm_delete"))) return;
    try {
      await deleteShift(shift.id);
      await refresh();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (detail === "has_assignments") alert(t("shifts.has_assignments_error"));
    }
  }

  const dtName = (id: string) => dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8);
  const locName = (id: string) => locations.find(l => l.id === id)?.name ?? id.slice(0, 8);

  return (
    <>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl" data-testid="shifts-page">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-semibold">{t("shifts.title")}</h2>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleClearAll}
              className="bg-red-600 text-white px-3 py-1 rounded text-sm hover:bg-red-700"
            >
              {t("shifts.clear_all_assignments")}
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

        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-2">
            {t("shifts.filter_from")}
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          </label>
          <label className="flex items-center gap-2">
            {t("shifts.filter_to")}
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          </label>
        </div>

        {(() => {
          const shiftCols: ColDef<DutyShift>[] = [
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
              id: "status",
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
              id: "actions",
              header: t("shifts.actions"),
              cell: (s) => (
                <span className="space-x-2 space-x-reverse">
                  <button
                    type="button"
                    onClick={() => setEditShift(s)}
                    className="text-blue-600 text-xs hover:underline"
                  >
                    {t("shifts.edit")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleClearAssignments(s)}
                    className="text-orange-600 text-xs hover:underline disabled:opacity-40"
                    disabled={s.assigned_count === 0}
                  >
                    {t("shifts.clear_assignments")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(s)}
                    className="text-red-600 text-xs hover:underline"
                    disabled={s.assigned_count > 0}
                  >
                    {t("shifts.delete")}
                  </button>
                </span>
              ),
            },
          ];
          return (
            <DataTable
              columns={shiftCols}
              data={shifts}
              filterPlaceholder={t("table.filter_placeholder")}
              emptyMessage="אין משמרות"
            />
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
    </>
  );
}

export default function ShiftsPage() {
  return <Layout><ShiftsContent /></Layout>;
}
