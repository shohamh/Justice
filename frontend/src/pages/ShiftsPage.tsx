import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../components/Layout";
import ShiftFormModal from "../components/ShiftFormModal";
import { DutyShift, deleteShift, listShifts } from "../api/shifts";
import { DutyType, DutyLocation, listDutyTypes, listLocations } from "../api/dutyConfig";

const FILL_COLORS: Record<string, string> = {
  empty: "bg-red-100 text-red-700",
  partial: "bg-amber-100 text-amber-700",
  full: "bg-green-100 text-green-700",
};

export default function ShiftsPage() {
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
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" dir="rtl" data-testid="shifts-page">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-semibold">{t("shifts.title")}</h2>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700"
          >
            {t("shifts.create")}
          </button>
        </div>

        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-2">
            {t("shifts.filter_from")}
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="border rounded p-1" />
          </label>
          <label className="flex items-center gap-2">
            {t("shifts.filter_to")}
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="border rounded p-1" />
          </label>
        </div>

        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-50 text-right">
              <th className="border px-2 py-1">{t("shifts.duty_type")}</th>
              <th className="border px-2 py-1">{t("shifts.location")}</th>
              <th className="border px-2 py-1">{t("shifts.start_date")}</th>
              <th className="border px-2 py-1">{t("shifts.end_date")}</th>
              <th className="border px-2 py-1">{t("shifts.required_count")}</th>
              <th className="border px-2 py-1">{t("shifts.assigned_count")}</th>
              <th className="border px-2 py-1">{t("shifts.status")}</th>
              <th className="border px-2 py-1">{t("shifts.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {shifts.length === 0 && (
              <tr><td colSpan={8} className="text-center text-gray-400 py-4">אין משמרות</td></tr>
            )}
            {shifts.map(shift => (
              <tr key={shift.id}>
                <td className="border px-2 py-1">{dtName(shift.duty_type_id)}</td>
                <td className="border px-2 py-1">{locName(shift.duty_location_id)}</td>
                <td className="border px-2 py-1">{shift.start_date}</td>
                <td className="border px-2 py-1">{shift.end_date}</td>
                <td className="border px-2 py-1 text-center">{shift.required_count}</td>
                <td className="border px-2 py-1 text-center">{shift.assigned_count}</td>
                <td className="border px-2 py-1">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${FILL_COLORS[shift.fill_status]}`}>
                    {t(`shifts.fill_${shift.fill_status}`)}
                  </span>
                </td>
                <td className="border px-2 py-1 space-x-2 space-x-reverse">
                  <button
                    type="button"
                    onClick={() => setEditShift(shift)}
                    className="text-blue-600 text-xs hover:underline"
                  >
                    {t("shifts.edit")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(shift)}
                    className="text-red-600 text-xs hover:underline"
                    disabled={shift.assigned_count > 0}
                  >
                    {t("shifts.delete")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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
    </Layout>
  );
}
