import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import Calendar from "react-calendar";
import "react-calendar/dist/Calendar.css";

import Layout from "../components/Layout";
import ExplanationModal from "../components/ExplanationModal";
import { useAuth } from "../auth/AuthContext";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { DutyLocation, DutyType, listDutyTypes, listLocations } from "../api/dutyConfig";
import { DataTable, type ColDef } from "../components/DataTable";

export default function MyDutiesPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [rows, setRows] = useState<EffectiveDuty[]>([]);
  const [types, setTypes] = useState<Record<string, string>>({});
  const [locs, setLocs] = useState<Record<string, string>>({});
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const [whyTarget, setWhyTarget] = useState<{ assignmentId: string } | null>(null);

  useEffect(() => {
    if (!user) return;
    void (async () => {
      const [as, dts, ls]: [EffectiveDuty[], DutyType[], DutyLocation[]] = await Promise.all([
        listEffectiveDuties(user.id),
        listDutyTypes().catch(() => [] as DutyType[]),
        listLocations().catch(() => [] as DutyLocation[]),
      ]);
      setRows(as);
      setTypes(Object.fromEntries(dts.map((d) => [d.id, d.name])));
      setLocs(Object.fromEntries(ls.map((l) => [l.id, l.name])));
    })();
  }, [user]);

  const dutyDates = useMemo(() => {
    const dates = new Set<string>();
    for (const r of rows) {
      const startParts = r.start_date.split("-").map(Number);
      const endParts = r.end_date.split("-").map(Number);
      const start = new Date(startParts[0], startParts[1] - 1, startParts[2]);
      const end = new Date(endParts[0], endParts[1] - 1, endParts[2]);
      for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        dates.add(`${y}-${m}-${day}`);
      }
    }
    return dates;
  }, [rows]);

  const filteredRows = useMemo(() => {
    if (!selectedDate) return rows;
    const y = selectedDate.getFullYear();
    const m = String(selectedDate.getMonth() + 1).padStart(2, "0");
    const day = String(selectedDate.getDate()).padStart(2, "0");
    const ds = `${y}-${m}-${day}`;
    return rows.filter((r) => r.start_date <= ds && r.end_date >= ds);
  }, [rows, selectedDate]);

  function tileClassName({ date }: { date: Date }) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    const ds = `${y}-${m}-${d}`;
    if (dutyDates.has(ds)) return "bg-indigo-100 rounded-full font-bold";
    return "";
  }

  function tileContent({ date }: { date: Date }) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    const ds = `${y}-${m}-${d}`;
    if (dutyDates.has(ds)) {
      return <div className="w-1.5 h-1.5 bg-indigo-500 rounded-full mx-auto" />;
    }
    return null;
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" data-testid="my-duties-page">
        <h2 className="text-xl font-semibold">{t("my_duties.title")}</h2>

        <div className="flex justify-center" data-testid="duty-calendar">
          <Calendar
            onChange={(value) => setSelectedDate(value as Date | null)}
            value={selectedDate}
            tileClassName={tileClassName}
            tileContent={tileContent}
            locale="he"
          />
        </div>

        {selectedDate && (
          <p className="text-sm text-gray-500">
            {t("my_duties.showing_for_date", "תורנויות לתאריך: {{date}}").replace("{{date}}", selectedDate.toLocaleDateString("he-IL"))}
            <button className="mr-2 text-indigo-600 text-xs" onClick={() => setSelectedDate(null)}>
              {t("my_duties.show_all")}
            </button>
          </p>
        )}

        {filteredRows.length === 0 ? (
          <p data-testid="my-duties-empty">{t("my_duties.none")}</p>
        ) : (() => {
          const dutyCols: ColDef<EffectiveDuty>[] = [
            {
              id: "duty_type",
              header: t("my_duties.duty_type"),
              cell: (a) => types[a.duty_type_id] ?? a.duty_type_id,
              sortValue: (a) => types[a.duty_type_id] ?? a.duty_type_id,
              filterValue: (a) => types[a.duty_type_id] ?? a.duty_type_id,
            },
            {
              id: "location",
              header: t("my_duties.location"),
              cell: (a) => locs[a.duty_location_id] ?? a.duty_location_id,
              sortValue: (a) => locs[a.duty_location_id] ?? a.duty_location_id,
              filterValue: (a) => locs[a.duty_location_id] ?? a.duty_location_id,
            },
            {
              id: "from",
              header: t("my_duties.from"),
              cell: (a) => a.start_date,
              sortValue: (a) => a.start_date,
            },
            {
              id: "to",
              header: t("my_duties.to"),
              cell: (a) => a.end_date,
              sortValue: (a) => a.end_date,
            },
            {
              id: "why",
              header: "",
              cell: (a) => (
                <button
                  type="button"
                  onClick={() => setWhyTarget({ assignmentId: a.assignment_id })}
                  className="text-xs text-blue-600 underline"
                >
                  {t("algorithm.why_button")}
                </button>
              ),
            },
          ];
          return (
            <DataTable
              columns={dutyCols}
              data={filteredRows}
              filterPlaceholder={t("table.filter_placeholder")}
            />
          );
        })()}
      </section>
      {whyTarget && (
        <ExplanationModal
          assignmentId={whyTarget.assignmentId}
          onClose={() => setWhyTarget(null)}
        />
      )}
    </Layout>
  );
}
