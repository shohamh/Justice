import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import heLocale from "@fullcalendar/core/locales/he";
import type { EventClickArg } from "@fullcalendar/core";

import Layout from "../components/Layout";
import ExplanationModal from "../components/ExplanationModal";
import { useAuth } from "../auth/AuthContext";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { DutyLocation, DutyType, listDutyTypes, listLocations } from "../api/dutyConfig";
import { dutyTypeColor } from "../utils/dutyTypeColor";
import { downloadDutyICS } from "../utils/icsCalendar";

export default function MyDutiesPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [rows, setRows] = useState<EffectiveDuty[]>([]);
  const [types, setTypes] = useState<Record<string, string>>({});
  const [locs, setLocs] = useState<Record<string, string>>({});
  const [selectedDuty, setSelectedDuty] = useState<EffectiveDuty | null>(null);
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

  const events = useMemo(() =>
    rows.map((r) => {
      const endDate = new Date(r.end_date);
      endDate.setDate(endDate.getDate() + 1);
      const color = dutyTypeColor(r.duty_type_id);
      return {
        id: r.assignment_id,
        title: types[r.duty_type_id] ?? r.duty_type_id,
        start: r.start_date,
        end: endDate.toISOString().slice(0, 10),
        backgroundColor: color,
        borderColor: color,
      };
    }),
  [rows, types]);

  function handleEventClick(arg: EventClickArg) {
    const duty = rows.find((r) => r.assignment_id === arg.event.id);
    if (duty) setSelectedDuty(duty);
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" data-testid="my-duties-page" dir="rtl">
        <h2 className="text-xl font-semibold">{t("my_duties.title")}</h2>

        <div className="text-sm" data-testid="duty-calendar">
          <FullCalendar
            plugins={[dayGridPlugin, interactionPlugin]}
            initialView="dayGridMonth"
            events={events}
            eventClick={handleEventClick}
            locales={[heLocale]}
            locale="he"
            height="auto"
            headerToolbar={{ left: "prev,next today", center: "title", right: "dayGridMonth" }}
            buttonText={{ today: t("unit_calendar.today") || "היום" }}
            noEventsText={t("my_duties.none")}
            displayEventTime={false}
          />
        </div>

        {rows.length === 0 && (
          <p data-testid="my-duties-empty" className="text-gray-500 text-sm">{t("my_duties.none")}</p>
        )}

        {selectedDuty && (
          <div className="border rounded-lg p-4 text-sm space-y-2 bg-gray-50">
            <div className="flex justify-between items-start">
              <h3 className="font-medium">{types[selectedDuty.duty_type_id] ?? selectedDuty.duty_type_id}</h3>
              <button onClick={() => setSelectedDuty(null)} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
            </div>
            <p className="text-gray-600">{locs[selectedDuty.duty_location_id] ?? selectedDuty.duty_location_id}</p>
            <p>{selectedDuty.start_date} ← {selectedDuty.end_date}</p>
            <button
              type="button"
              onClick={() => setWhyTarget({ assignmentId: selectedDuty.assignment_id })}
              className="text-blue-600 underline text-xs"
            >
              {t("algorithm.why_button")}
            </button>
            <button
              type="button"
              onClick={() => downloadDutyICS(
                selectedDuty,
                types[selectedDuty.duty_type_id] ?? selectedDuty.duty_type_id,
                locs[selectedDuty.duty_location_id] ?? ""
              )}
              className="text-xs text-indigo-600 hover:underline flex items-center gap-1 mt-2"
            >
              📅 {t("my_duties.add_to_calendar")}
            </button>
          </div>
        )}
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
