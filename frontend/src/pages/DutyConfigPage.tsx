import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import DutyTypeRequirementsEditor from "../components/DutyTypeRequirementsEditor";
import {
  DutyLocation,
  DutyType,
  ExemptionType,
  createDutyType,
  createExemptionType,
  createLocation,
  getExemptionDutyTypes,
  listDutyTypes,
  listExemptionTypes,
  listLocations,
  setExemptionDutyTypes,
  updateDutyType,
} from "../api/dutyConfig";

export default function DutyConfigPage() {
  const { t } = useTranslation();
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
  const [locations, setLocations] = useState<DutyLocation[]>([]);
  const [exTypes, setExTypes] = useState<ExemptionType[]>([]);
  const [dtName, setDtName] = useState("");
  const [dtScore, setDtScore] = useState("1.00");
  const [locName, setLocName] = useState("");
  const [exName, setExName] = useState("");
  const [mapSel, setMapSel] = useState<Record<string, string[]>>({});
  const [expandedDtId, setExpandedDtId] = useState<string | null>(null);

  async function refresh() {
    const [dts, locs, ets] = await Promise.all([listDutyTypes(), listLocations(), listExemptionTypes()]);
    setDutyTypes(dts);
    setLocations(locs);
    setExTypes(ets);
    const sel: Record<string, string[]> = {};
    for (const et of ets) sel[et.id] = await getExemptionDutyTypes(et.id);
    setMapSel(sel);
  }
  useEffect(() => { void refresh(); }, []);

  async function addDutyType(e: FormEvent) {
    e.preventDefault();
    await createDutyType({ name: dtName, score_per_day: dtScore });
    setDtName(""); setDtScore("1.00");
    await refresh();
  }
  async function addLocation(e: FormEvent) {
    e.preventDefault();
    await createLocation({ name: locName });
    setLocName("");
    await refresh();
  }
  async function addExType(e: FormEvent) {
    e.preventDefault();
    await createExemptionType({ name: exName });
    setExName("");
    await refresh();
  }
  async function toggleMap(etId: string, dtId: string) {
    const current = mapSel[etId] ?? [];
    const next = current.includes(dtId) ? current.filter((x) => x !== dtId) : [...current, dtId];
    await setExemptionDutyTypes(etId, next);
    setMapSel({ ...mapSel, [etId]: next });
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-8" data-testid="duty-config-page">
        <h2 className="text-xl font-semibold">{t("duty_config.title")}</h2>

        <div data-testid="duty-types-section">
          <h3 className="font-medium mb-2">{t("duty_config.duty_types")}</h3>
          <form onSubmit={addDutyType} className="flex items-end gap-2 mb-2" data-testid="duty-type-form">
            <label className="block"><span className="text-xs">{t("duty_config.name")}</span>
              <input className="block border rounded p-1" value={dtName} onChange={(e) => setDtName(e.target.value)} required data-testid="dt-name" /></label>
            <label className="block"><span className="text-xs">{t("duty_config.score_per_day")}</span>
              <input className="block border rounded p-1 w-24" value={dtScore} onChange={(e) => setDtScore(e.target.value)} data-testid="dt-score" /></label>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="dt-submit">{t("duty_config.add")}</button>
          </form>
          <div className="space-y-1 text-sm" data-testid="duty-type-list">
            {dutyTypes.map((d) => (
              <div key={d.id} data-testid={`dt-row-${d.name}`} className="border rounded p-2 space-y-2">
                <div className="flex items-center gap-2">
                  <span>{d.name} — {d.score_per_day}</span>
                  <button className="text-xs text-indigo-600" onClick={() => updateDutyType(d.id, { active: !d.active }).then(refresh)} data-testid={`dt-toggle-${d.name}`}>
                    {d.active ? t("duty_config.active") : "—"}
                  </button>
                  <button
                    type="button"
                    className="text-xs text-blue-600 underline ml-auto"
                    onClick={() => setExpandedDtId(expandedDtId === d.id ? null : d.id)}
                  >
                    {t("eligibility.title")}
                  </button>
                </div>
                {expandedDtId === d.id && (
                  <DutyTypeRequirementsEditor
                    dutyType={d}
                    onSaved={async () => { await refresh(); setExpandedDtId(null); }}
                  />
                )}
              </div>
            ))}
          </div>
        </div>

        <div data-testid="locations-section">
          <h3 className="font-medium mb-2">{t("duty_config.locations")}</h3>
          <form onSubmit={addLocation} className="flex items-end gap-2 mb-2" data-testid="location-form">
            <input className="border rounded p-1" value={locName} onChange={(e) => setLocName(e.target.value)} required data-testid="loc-name" placeholder={t("duty_config.name")} />
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="loc-submit">{t("duty_config.add")}</button>
          </form>
          <ul className="text-sm" data-testid="location-list">
            {locations.map((l) => <li key={l.id} data-testid={`loc-row-${l.name}`}>{l.name}</li>)}
          </ul>
        </div>

        <div data-testid="exemption-types-section">
          <h3 className="font-medium mb-2">{t("duty_config.exemption_types")}</h3>
          <form onSubmit={addExType} className="flex items-end gap-2 mb-2" data-testid="exemption-type-form">
            <input className="border rounded p-1" value={exName} onChange={(e) => setExName(e.target.value)} required data-testid="et-name" placeholder={t("duty_config.name")} />
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="et-submit">{t("duty_config.add")}</button>
          </form>
          <ul className="text-sm space-y-2" data-testid="exemption-type-list">
            {exTypes.map((et) => (
              <li key={et.id} data-testid={`et-row-${et.name}`}>
                <div>{et.name}</div>
                <div className="text-xs text-gray-500">{t("duty_config.exempts_from")}:</div>
                <div className="flex flex-wrap gap-2">
                  {dutyTypes.map((d) => (
                    <label key={d.id} className="text-xs flex items-center gap-1">
                      <input type="checkbox" checked={(mapSel[et.id] ?? []).includes(d.id)}
                             onChange={() => toggleMap(et.id, d.id)}
                             data-testid={`map-${et.name}-${d.name}`} />
                      {d.name}
                    </label>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </Layout>
  );
}
