import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { DutyLocation, DutyType, listDutyTypes, listLocations } from "../api/dutyConfig";

export default function MyDutiesPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [rows, setRows] = useState<EffectiveDuty[]>([]);
  const [types, setTypes] = useState<Record<string, string>>({});
  const [locs, setLocs] = useState<Record<string, string>>({});

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

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" data-testid="my-duties-page">
        <h2 className="text-xl font-semibold">{t("my_duties.title")}</h2>
        {rows.length === 0 ? (
          <p data-testid="my-duties-empty">{t("my_duties.none")}</p>
        ) : (
          <table className="w-full text-sm text-right" data-testid="my-duties-table">
            <thead>
              <tr className="border-b">
                <th className="p-1">{t("my_duties.duty_type")}</th>
                <th className="p-1">{t("my_duties.location")}</th>
                <th className="p-1">{t("my_duties.from")}</th>
                <th className="p-1">{t("my_duties.to")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={`${a.assignment_id}-${a.start_date}`} data-testid={`my-duty-row-${a.assignment_id}-${a.start_date}`}>
                  <td className="p-1">{types[a.duty_type_id] ?? a.duty_type_id}</td>
                  <td className="p-1">{locs[a.duty_location_id] ?? a.duty_location_id}</td>
                  <td className="p-1">{a.start_date}</td>
                  <td className="p-1">{a.end_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </Layout>
  );
}
