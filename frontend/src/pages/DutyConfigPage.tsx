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
  getAllExemptionDutyTypeMaps,
  listDutyTypes,
  listExemptionTypes,
  listLocations,
  setExemptionDutyTypes,
  updateDutyType,
  updateExemptionType,
} from "../api/dutyConfig";

export function DutyConfigContent() {
  const { t } = useTranslation();
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
  const [locations, setLocations] = useState<DutyLocation[]>([]);
  const [exTypes, setExTypes] = useState<ExemptionType[]>([]);
  const [dtName, setDtName] = useState("");
  const [dtScore, setDtScore] = useState("1.00");
  const [dtReserveRatio, setDtReserveRatio] = useState("0.000");
  const [dtReserveMin, setDtReserveMin] = useState("0");
  const [dtContactName, setDtContactName] = useState("");
  const [dtContactPhone, setDtContactPhone] = useState("");
  const [dtStartTime, setDtStartTime] = useState("");
  const [dtEndTime, setDtEndTime] = useState("");
  const [dtInstructions, setDtInstructions] = useState("");
  const [dtIsExternal, setDtIsExternal] = useState<"" | "true" | "false">("");
  const [locName, setLocName] = useState("");
  const [exName, setExName] = useState("");
  const [exGlobal, setExGlobal] = useState(false);
  const [exMedical, setExMedical] = useState(false);
  const [mapSel, setMapSel] = useState<Record<string, string[]>>({});
  const [expandedDtId, setExpandedDtId] = useState<string | null>(null);

  async function refresh() {
    const [dts, locs, ets, sel] = await Promise.all([
      listDutyTypes(),
      listLocations(),
      listExemptionTypes(),
      getAllExemptionDutyTypeMaps(),
    ]);
    setDutyTypes(dts);
    setLocations(locs);
    setExTypes(ets);
    setMapSel(sel);
  }
  useEffect(() => { void refresh(); }, []);

  async function addDutyType(e: FormEvent) {
    e.preventDefault();
    await createDutyType({
      name: dtName,
      score_per_day: dtScore,
      reserve_ratio: dtReserveRatio,
      reserve_minimum: parseInt(dtReserveMin) || 0,
      contact_name: dtContactName || null,
      contact_phone: dtContactPhone || null,
      start_time: dtStartTime || null,
      end_time: dtEndTime || null,
      instructions: dtInstructions || null,
      is_external: dtIsExternal === "true",
    });
    setDtName(""); setDtScore("1.00"); setDtReserveRatio("0.000"); setDtReserveMin("0");
    setDtContactName(""); setDtContactPhone(""); setDtStartTime(""); setDtEndTime("");
    setDtInstructions(""); setDtIsExternal("");
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
    await createExemptionType({ name: exName, is_global: exGlobal, is_medical: exMedical });
    setExName(""); setExGlobal(false); setExMedical(false);
    await refresh();
  }
  async function toggleMap(etId: string, dtId: string) {
    const current = mapSel[etId] ?? [];
    const next = current.includes(dtId) ? current.filter((x) => x !== dtId) : [...current, dtId];
    await setExemptionDutyTypes(etId, next);
    setMapSel({ ...mapSel, [etId]: next });
  }

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-8" data-testid="duty-config-page">
      <h2 className="text-xl font-semibold">{t("duty_config.title")}</h2>

      <div data-testid="duty-types-section">
        <h3 className="font-medium mb-2">{t("duty_config.duty_types")}</h3>
        <form onSubmit={addDutyType} className="space-y-2 mb-2" data-testid="duty-type-form">
          <div className="flex items-end gap-2 flex-wrap">
            <label className="block"><span className="text-xs">{t("duty_config.name")}</span>
              <input className="block border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtName} onChange={(e) => setDtName(e.target.value)} required data-testid="dt-name" /></label>
            <label className="block"><span className="text-xs">{t("duty_config.score_per_day")}</span>
              <input className="block border rounded p-1 w-24 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtScore} onChange={(e) => setDtScore(e.target.value)} data-testid="dt-score" /></label>
            <label className="block"><span className="text-xs">{t("reserve_ratio")}</span>
              <input type="number" min="0" max="1" step="0.001" className="block border rounded p-1 w-20 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtReserveRatio} onChange={(e) => setDtReserveRatio(e.target.value)} data-testid="dt-reserve-ratio" /></label>
            <label className="block"><span className="text-xs">{t("reserve_minimum")}</span>
              <input type="number" min="0" step="1" className="block border rounded p-1 w-16 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtReserveMin} onChange={(e) => setDtReserveMin(e.target.value)} data-testid="dt-reserve-min" /></label>
            <label className="block"><span className="text-xs">{t("duty_config.contact_name")}</span>
              <input className="block border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtContactName} onChange={(e) => setDtContactName(e.target.value)} data-testid="dt-contact-name" /></label>
            <label className="block"><span className="text-xs">{t("duty_config.contact_phone")}</span>
              <input className="block border rounded p-1 w-32 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtContactPhone} onChange={(e) => setDtContactPhone(e.target.value)} data-testid="dt-contact-phone" /></label>
            <label className="block"><span className="text-xs">{t("duty_config.start_time")}</span>
              <input type="time" className="block border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtStartTime} onChange={(e) => setDtStartTime(e.target.value)} data-testid="dt-start-time" /></label>
            <label className="block"><span className="text-xs">{t("duty_config.end_time")}</span>
              <input type="time" className="block border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtEndTime} onChange={(e) => setDtEndTime(e.target.value)} data-testid="dt-end-time" /></label>
            <label className="block"><span className="text-xs">{t("duty_config.is_external")} *</span>
              <select required className="block border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtIsExternal} onChange={(e) => setDtIsExternal(e.target.value as "" | "true" | "false")} data-testid="dt-is-external">
                <option value="" disabled>{t("duty_config.is_external_placeholder")}</option>
                <option value="false">{t("duty_config.is_external_internal")}</option>
                <option value="true">{t("duty_config.is_external_external")}</option>
              </select></label>
          </div>
          <label className="block">
            <span className="text-xs">{t("duty_config.instructions")} <span className="text-gray-400">({t("duty_config.instructions_hint")})</span></span>
            <textarea
              className="block border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              rows={3}
              value={dtInstructions}
              onChange={(e) => setDtInstructions(e.target.value)}
              data-testid="dt-instructions"
            />
          </label>
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="dt-submit">{t("duty_config.add")}</button>
        </form>
        <div className="space-y-1 text-sm" data-testid="duty-type-list">
          {dutyTypes.map((d) => (
            <div key={d.id} data-testid={`dt-row-${d.name}`} className="border dark:border-gray-600 rounded p-2 space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span>{d.name} — {d.score_per_day}</span>
                {d.reserve_ratio && parseFloat(d.reserve_ratio) > 0 && (
                  <span className="text-xs text-purple-600 dark:text-purple-400">ר:{d.reserve_ratio} מינ:{d.reserve_minimum ?? 0}</span>
                )}
                <span className={`text-xs px-1.5 py-0.5 rounded ${d.is_external ? "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200" : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"}`}>
                  {d.is_external ? t("duty_config.is_external_external") : t("duty_config.is_external_internal")}
                </span>
                <button className="text-xs text-indigo-600 dark:text-indigo-400" onClick={() => updateDutyType(d.id, { active: !d.active }).then(refresh)} data-testid={`dt-toggle-${d.name}`}>
                  {d.active ? t("duty_config.active") : "—"}
                </button>
                <button
                  type="button"
                  className="text-xs text-blue-600 dark:text-blue-400 underline ml-auto"
                  onClick={() => setExpandedDtId(expandedDtId === d.id ? null : d.id)}
                >
                  {t("eligibility.title")}
                </button>
              </div>
              {(d.contact_name || d.contact_phone || d.start_time || d.end_time || d.instructions) && (
                <div className="text-xs text-gray-500 dark:text-gray-400 space-y-0.5 mt-1">
                  {(d.contact_name || d.contact_phone) && (
                    <p>{t("duty_config.contact_name")}: {d.contact_name ?? "—"}{d.contact_phone ? ` | ${d.contact_phone}` : ""}</p>
                  )}
                  {(d.start_time || d.end_time) && (
                    <p>{t("duty_config.start_time")}: {d.start_time?.slice(0, 5) ?? "—"} — {d.end_time?.slice(0, 5) ?? "—"}</p>
                  )}
                  {d.instructions && <p>{t("duty_config.instructions")}: {d.instructions}</p>}
                </div>
              )}
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
          <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={locName} onChange={(e) => setLocName(e.target.value)} required data-testid="loc-name" placeholder={t("duty_config.name")} />
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="loc-submit">{t("duty_config.add")}</button>
        </form>
        <ul className="text-sm" data-testid="location-list">
          {locations.map((l) => <li key={l.id} data-testid={`loc-row-${l.name}`}>{l.name}</li>)}
        </ul>
      </div>

      <div data-testid="exemption-types-section">
        <h3 className="font-medium mb-2">{t("duty_config.exemption_types")}</h3>
        <form onSubmit={addExType} className="flex items-end gap-2 mb-2 flex-wrap" data-testid="exemption-type-form">
          <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={exName} onChange={(e) => setExName(e.target.value)} required data-testid="et-name" placeholder={t("duty_config.name")} />
          <label className="flex items-center gap-1 text-xs cursor-pointer">
            <input type="checkbox" checked={exGlobal} onChange={(e) => setExGlobal(e.target.checked)} data-testid="et-global" />
            {t("duty_config.global")}
          </label>
          <label className="flex items-center gap-1 text-xs cursor-pointer">
            <input type="checkbox" checked={exMedical} onChange={(e) => setExMedical(e.target.checked)} data-testid="et-medical" />
            🏥 {t("duty_config.medical")}
          </label>
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="et-submit">{t("duty_config.add")}</button>
        </form>
        <ul className="text-sm space-y-2" data-testid="exemption-type-list">
          {exTypes.map((et) => (
            <li key={et.id} data-testid={`et-row-${et.name}`} className="border dark:border-gray-600 rounded p-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span>{et.name}</span>
                {et.is_global && <span className="text-xs bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 px-2 py-0.5 rounded">{t("duty_config.global")}</span>}
                {et.is_medical && <span className="text-xs bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 px-2 py-0.5 rounded">🏥 {t("duty_config.medical")}</span>}
                <label className="flex items-center gap-1 text-xs cursor-pointer text-gray-500 dark:text-gray-400 mr-auto">
                  <input
                    type="checkbox"
                    checked={et.is_medical ?? false}
                    onChange={async (e) => {
                      await updateExemptionType(et.id, { is_medical: e.target.checked });
                      await refresh();
                    }}
                    data-testid={`et-medical-toggle-${et.name}`}
                  />
                  🏥 {t("duty_config.medical")}
                </label>
              </div>
              {et.is_global ? (
                <div className="text-xs text-gray-500 mt-1">{t("duty_config.global_exempt_desc")}</div>
              ) : (
                <>
                  <div className="text-xs text-gray-500 mt-1">{t("duty_config.exempts_from")}:</div>
                  <div className="flex flex-wrap gap-2 mt-1">
                    {dutyTypes.map((d) => (
                      <label key={d.id} className="text-xs flex items-center gap-1">
                        <input type="checkbox" checked={(mapSel[et.id] ?? []).includes(d.id)}
                               onChange={() => toggleMap(et.id, d.id)}
                               data-testid={`map-${et.name}-${d.name}`} />
                        {d.name}
                      </label>
                    ))}
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export default function DutyConfigPage() {
  return <Layout><DutyConfigContent /></Layout>;
}
